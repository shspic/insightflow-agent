"""工程 Verification Agent（阶段 4C-2）：规划层。

职责：
- 对已完成 ReviewRun 的 Finding 生成检索计划（retrieve / skip 决策）
- 确定性 fallback planner 与 DeepSeek planner 双模式
- Agent 只选择"是否检索、检索什么"，不能修改 Finding、风险等级或合规结论
- 不读取黄金答案文件，不含硬编码答案

规则：
- 只能引用当前 ReviewRun 的 Finding
- query 长度 1～500，最多 5 次检索，重复 query 去重
- excluded_check_types 中的检查不能被重新加入
- DeepSeek 输出必须通过严格 Pydantic 校验；失败用确定性 fallback
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.llm_service import LLMResult, call_llm

PROMPT_VERSION = "4c2.3"
MAX_RETRIEVALS = 5
RETRIEVAL_MODES = ("bm25", "dense", "hybrid_rrf")

# DeepSeek 输出上限：足够容纳全部 Finding 决策（12+ 条），不超过 2400
DEEPSEEK_MAX_TOKENS = 2400

# 确定性 fallback 优先检索的 issue_code / 规则类型
PRIORITY_ISSUE_MARKERS = ("cross_file_equal", "evidence_required")

# 需要跳过的决策也必须在 plan 中记录 reason（证明 Agent 做过决策）


class VerificationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: int = Field(ge=1)
    issue_code: str = Field(min_length=1, max_length=200)
    decision: Literal["retrieve", "skip"]
    reason: str = Field(min_length=1, max_length=500)
    query: str | None = Field(default=None, min_length=1, max_length=500)
    retrieval_mode: Literal["bm25", "dense", "hybrid_rrf"] = "hybrid_rrf"
    top_k: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def _check_query_required_for_retrieve(self) -> "VerificationDecision":
        if self.decision == "retrieve" and not self.query:
            raise ValueError("retrieve 决策必须提供 query")
        if self.decision == "skip" and self.query:
            raise ValueError("skip 决策不应提供 query")
        return self


class VerificationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[VerificationDecision] = Field(max_length=MAX_RETRIEVALS + 20)

    @model_validator(mode="after")
    def _check_retrieval_budget(self) -> "VerificationPlan":
        retrieves = [d for d in self.decisions if d.decision == "retrieve"]
        if len(retrieves) > MAX_RETRIEVALS:
            raise ValueError(f"最多 {MAX_RETRIEVALS} 次检索，实际 {len(retrieves)}")
        queries = [d.query for d in retrieves]
        if len(queries) != len(set(queries)):
            raise ValueError("检索 query 重复")
        return self


class PlannerInput:
    """规划输入（从 ReviewRun + Findings + Evidence 组装，不含原文全文）。"""

    def __init__(
        self,
        *,
        findings: list[dict[str, Any]],
        rule_summaries: list[dict[str, str]],
        brief_summary: str,
        excluded_check_types: list[str],
        max_retrievals: int = MAX_RETRIEVALS,
    ):
        self.findings = findings
        self.rule_summaries = rule_summaries
        self.brief_summary = brief_summary
        self.excluded_check_types = excluded_check_types
        self.max_retrievals = max_retrievals

    def finding_by_id(self, finding_id: int) -> dict[str, Any] | None:
        for f in self.findings:
            if f["id"] == finding_id:
                return f
        return None

    def rule_title(self, issue_code: str) -> str:
        for r in self.rule_summaries:
            if r.get("rule_id") == issue_code:
                return r.get("title", "")
        return ""


# ── 确定性 fallback planner ─────────────────────────────────────────


def deterministic_plan(
    planner_input: PlannerInput,
    *,
    max_tool_calls: int,
) -> tuple[VerificationPlan, str | None]:
    """确定性 fallback：按优先级选择检索，其余 skip。

    至少对以下 Finding 考虑检索：
    - cross_file_equal / evidence_required 类 issue_code
    - 高风险且现有 Evidence 数量不足（< 2 条）

    query 只由真实字段组合：Finding.title / conclusion / issue_code / 规则标题。
    """
    retrievable: list[tuple[int, dict[str, Any]]] = []
    skipped: list[tuple[int, dict[str, Any], str]] = []

    for finding in planner_input.findings:
        finding_id = int(finding["id"])
        issue_code = str(finding["issue_code"])
        severity = str(finding.get("severity", "medium"))
        evidence_ids = finding.get("evidence_ids", []) or []

        # excluded_check_types 中的检查不能被重新加入
        if issue_code in planner_input.excluded_check_types:
            skipped.append((finding_id, finding, "Brief 排除的检查类型，不补充检索"))
            continue

        marker_hit = any(m in issue_code for m in PRIORITY_ISSUE_MARKERS)
        high_risk_low_evidence = (
            severity == "high" and len(evidence_ids) < 2
        )
        if marker_hit or high_risk_low_evidence:
            retrievable.append((finding_id, finding))
        else:
            reason = (
                "高风险但已有足够证据" if severity == "high"
                else "非优先级类型且已有定位证据"
            )
            skipped.append((finding_id, finding, reason))

    # 按优先级排序：cross_file_equal/evidence_required 优先，其次高风险
    def _priority(item):
        finding = item[1]
        issue_code = str(finding["issue_code"])
        if "evidence_required" in issue_code:
            return 0
        if "cross_file_equal" in issue_code:
            return 1
        if str(finding.get("severity", "medium")) == "high":
            return 2
        return 3

    retrievable.sort(key=_priority)

    # 预算约束：每次检索最多 3 次调用（原 + prepare + retry），至少预留 1 次
    max_by_budget = max(1, max_tool_calls // 2)
    retrievable = retrievable[: min(max_by_budget, planner_input.max_retrievals)]

    # 重复 query 去重
    seen_queries: set[str] = set()
    decisions: list[VerificationDecision] = []
    for finding_id, finding in retrievable:
        query = _build_query(finding, planner_input)
        if query in seen_queries:
            skipped.append((finding_id, finding, "与已有检索 query 重复，去重"))
            continue
        seen_queries.add(query)
        decisions.append(
            VerificationDecision(
                finding_id=finding_id,
                issue_code=str(finding["issue_code"]),
                decision="retrieve",
                reason="需要补充检索定位证据",
                query=query,
                retrieval_mode="hybrid_rrf",
                top_k=5,
            )
        )

    for finding_id, finding, reason in skipped:
        decisions.append(
            VerificationDecision(
                finding_id=finding_id,
                issue_code=str(finding["issue_code"]),
                decision="skip",
                reason=reason,
            )
        )

    fallback_reason = None
    # 全部 skip（无检索）也算有效计划；fallback 仅在 DeepSeek 失败时置位
    return VerificationPlan(decisions=decisions), fallback_reason


def _build_query(finding: dict[str, Any], planner_input: PlannerInput) -> str:
    """query 只能由真实字段组合生成（禁止硬编码黄金答案/ground_truth）。"""
    title = str(finding.get("title", ""))[:60]
    conclusion = str(finding.get("conclusion", ""))[:80]
    issue_code = str(finding.get("issue_code", ""))
    rule_title = planner_input.rule_title(issue_code)

    if title and conclusion:
        return f"{title} {conclusion}"
    if rule_title:
        return f"{issue_code} {rule_title}"
    return f"{issue_code} {title}".strip()[:500] or "补充证据检索"


# ── DeepSeek planner ────────────────────────────────────────────────


def _build_deepseek_prompt(planner_input: PlannerInput, max_tool_calls: int) -> list[dict[str, str]]:
    """构造模型输入：只包含 Brief 快照摘要、规则摘要、Finding 摘要、
    现有 Evidence locator 和允许工具；不传完整原文、API Key、磁盘路径。"""
    finding_lines = []
    for f in planner_input.findings:
        evidence_locs = f.get("evidence_locations", []) or []
        finding_lines.append(
            {
                "id": f["id"],
                "issue_code": f["issue_code"],
                "title": str(f["title"])[:80],
                "severity": f.get("severity"),
                "conclusion": str(f.get("conclusion", ""))[:120],
                "suggestion": str(f.get("suggestion", ""))[:60],
                "evidence_locations": evidence_locs[:6],
            }
        )

    system = (
        "你是工程审查 Verification Agent。你的唯一职责是决定对哪些审查发现"
        "（Finding）需要补充检索，以及用什么 query 检索。\n"
        "约束：\n"
        f"1. 最多 {planner_input.max_retrievals} 次检索；每次检索 top_k 1-10；"
        "retrieval_mode 只能是 bm25/dense/hybrid_rrf。\n"
        "2. 只能引用输入中真实存在的 finding id 和 issue_code。\n"
        "3. 你只能决定是否检索和检索什么，不能修改 Finding 的结论、风险等级或合规判定。\n"
        "4. 输出必须是严格 JSON：{\"decisions\": [{\"finding_id\": int, "
        "\"issue_code\": str, \"decision\": \"retrieve\"|\"skip\", \"reason\": str, "
        "\"query\": str|null, \"retrieval_mode\": str, \"top_k\": int}]}。\n"
        "5. 每个 Finding 都必须有且仅有一个决策；跳过也要给出理由。\n"
        "6. 不允许生成任意工具名，不允许执行代码、SQL 或文件操作。\n"
        "7. 输出必须是纯 JSON：不要使用 markdown 代码围栏，"
        "不要附加任何解释文字或前后缀。\n"
        "8. 控制输出长度：reason 控制在 60 个汉字以内；query 控制在 200 个字符以内；"
        "skip 决策不要输出无用长文本，一行即可。\n"
        "9. 不要输出任何推理过程或解释文字，直接输出 JSON 结果。"
    )

    user = (
        f"ReviewBrief 摘要：\n{planner_input.brief_summary[:1500]}\n\n"
        f"被排除的检查类型：{planner_input.excluded_check_types or []}\n\n"
        f"规则摘要：\n{json.dumps(planner_input.rule_summaries, ensure_ascii=False)[:2500]}\n\n"
        f"Finding 摘要：\n{json.dumps(finding_lines, ensure_ascii=False)[:8000]}\n\n"
        f"工具预算（最大工具调用数）：{max_tool_calls}。"
        "直接输出 JSON，不要思考过程。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


class DeepSeekPlanResult:
    def __init__(
        self,
        *,
        plan: VerificationPlan | None,
        llm: LLMResult | None,
        fallback_used: bool,
        fallback_reason: str | None,
    ):
        self.plan = plan
        self.llm = llm
        self.fallback_used = fallback_used
        self.fallback_reason = fallback_reason


def _parse_json_object_safe(raw: str) -> dict | None:
    """安全解析模型输出为一个顶层 JSON object。

    接受：
    - 纯 JSON
    - 仅由一个 ```json ... ``` 围栏包裹的 JSON
    - 带 BOM / 首尾空白

    拒绝：
    - 多个顶层 JSON object（禁止拼接猜测）
    - 任何无法解析的内容（不通过正则修补残缺 JSON，不猜测被截断字段）

    返回 dict 或 None（None 表示不可解析，由调用方走 fallback）。
    """
    if not raw:
        return None
    text = raw.lstrip("﻿").strip()

    # 单个 ```json ... ``` 围栏包裹
    if text.startswith("```"):
        lines = text.splitlines()
        if not lines:
            return None
        fence = lines[0].strip().lower()
        if not fence.startswith("```"):
            return None
        if not lines[-1].strip().startswith("```"):
            return None  # 未闭合围栏
        body_lines = lines[1:]
        if body_lines and body_lines[-1].strip().startswith("```"):
            body_lines = body_lines[:-1]
        text = "\n".join(body_lines).strip()
        # 围栏后仍有内容 → 拒绝（只能是单个围栏）
        remainder = text[len(text):]  # noqa: F841 — 已裁剪

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def deepseek_plan(
    planner_input: PlannerInput,
    *,
    max_tool_calls: int,
) -> DeepSeekPlanResult:
    """调用 DeepSeek 生成计划；任何失败走确定性 fallback。

    每个 VerificationRun 最多调用 DeepSeek 一次（本函数只调用一次 call_llm）。
    """
    messages = _build_deepseek_prompt(planner_input, max_tool_calls)
    # 官方 JSON 模式：thinking 关闭 + response_format=json_object。
    # Verification Plan 是受限分类与工具参数生成，不需要 reasoning 模式。
    # 仍保持单次调用（每 VerificationRun 最多调用 DeepSeek 一次）。
    llm = call_llm(
        messages,
        temperature=0,
        max_tokens=DEEPSEEK_MAX_TOKENS,
        timeout_seconds=120,
        response_format="json_object",
        thinking="disabled",
    )

    if not llm.success or not llm.content:
        fallback_plan, _ = deterministic_plan(planner_input, max_tool_calls=max_tool_calls)
        return DeepSeekPlanResult(
            plan=fallback_plan,
            llm=llm,
            fallback_used=True,
            fallback_reason="DEEPSEEK_EMPTY_CONTENT",
        )

    if llm.finish_reason == "length":
        fallback_plan, _ = deterministic_plan(planner_input, max_tool_calls=max_tool_calls)
        return DeepSeekPlanResult(
            plan=fallback_plan,
            llm=llm,
            fallback_used=True,
            fallback_reason="DEEPSEEK_OUTPUT_TRUNCATED",
        )

    data = _parse_json_object_safe(llm.content)
    if data is None:
        fallback_plan, _ = deterministic_plan(planner_input, max_tool_calls=max_tool_calls)
        return DeepSeekPlanResult(
            plan=fallback_plan,
            llm=llm,
            fallback_used=True,
            fallback_reason="DEEPSEEK_JSON_INVALID",
        )

    try:
        plan = VerificationPlan.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        fallback_plan, _ = deterministic_plan(planner_input, max_tool_calls=max_tool_calls)
        return DeepSeekPlanResult(
            plan=fallback_plan,
            llm=llm,
            fallback_used=True,
            fallback_reason="DEEPSEEK_SCHEMA_INVALID",
        )

    # 语义校验：只引用真实 Finding、预算约束
    violation = _validate_plan_against_input(plan, planner_input, max_tool_calls)
    if violation:
        fallback_plan, _ = deterministic_plan(planner_input, max_tool_calls=max_tool_calls)
        return DeepSeekPlanResult(
            plan=fallback_plan,
            llm=llm,
            fallback_used=True,
            fallback_reason="DEEPSEEK_PLAN_POLICY_VIOLATION",
        )

    return DeepSeekPlanResult(plan=plan, llm=llm, fallback_used=False, fallback_reason=None)


def _validate_plan_against_input(
    plan: VerificationPlan,
    planner_input: PlannerInput,
    max_tool_calls: int,
) -> str | None:
    """校验模型计划：每个 Finding 恰好一次、issue_code 对应、
    excluded 检查不得被重新加入、预算约束 → 违规返回原因。"""
    seen_finding_ids = {int(f["id"]) for f in planner_input.findings}
    seen_queries: set[str] = set()
    retrieve_count = 0
    covered_finding_ids: set[int] = set()

    for d in plan.decisions:
        if d.finding_id not in seen_finding_ids:
            return f"模型引用了不存在的 finding_id={d.finding_id}"
        if d.finding_id in covered_finding_ids:
            return f"模型重复决策 finding_id={d.finding_id}"
        covered_finding_ids.add(d.finding_id)

        finding = planner_input.finding_by_id(d.finding_id)
        if finding is None or d.issue_code != str(finding["issue_code"]):
            return f"模型 issue_code 与 finding {d.finding_id} 不匹配"

        # excluded_check_types 中的检查不得被重新加入（retrieve 即重新加入）
        if (
            d.decision == "retrieve"
            and d.issue_code in planner_input.excluded_check_types
        ):
            return f"模型重新加入被排除的检查 {d.issue_code}"

        if d.decision == "retrieve":
            retrieve_count += 1
            if d.query in seen_queries:
                return "模型计划包含重复 query"
            seen_queries.add(d.query)

    # 每个当前 Finding 都必须恰好有一个决策
    missing = seen_finding_ids - covered_finding_ids
    if missing:
        return f"模型遗漏 Finding: {sorted(missing)}"

    if retrieve_count > min(max_tool_calls, planner_input.max_retrievals):
        return f"检索次数超预算（{retrieve_count} > {max_tool_calls}）"
    return None
