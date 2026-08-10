"""工程 Verification Agent 服务（阶段 4C-2）：执行层。

流程：
    已完成 ReviewRun → 组装 PlannerInput → 规划（确定性/DeepSeek）
    → 执行检索工具 → 局部重试（仅 INDEX_MISSING / INDEX_STALE）
    → 保存候选证据（candidate_only，不写正式 Finding/Evidence）
    → 幂等复用（同 review_run_id + input_state_hash）

约束：
- 同一 ReviewRun、同一 input_state_hash 的成功运行幂等复用
- 不允许跨 workspace、跨 owner 复用
- 不把候选证据写入正式 Finding/Evidence；不修改 Finding status
- 失败后 VerificationRun 可为 completed_with_warnings，不得把 ReviewRun 改 failed
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.engineering_tool_registry import (
    ENGINEERING_TOOL_HYBRID_RETRIEVAL,
    ENGINEERING_TOOL_INDEX_PREPARE,
    ALLOWED_AGENT_TYPE,
    EngineeringToolError,
    execute_engineering_tool,
)
from app.agents.engineering_verification_agent import (
    PROMPT_VERSION,
    PlannerInput,
    VerificationPlan,
    deepseek_plan,
    deterministic_plan,
)
from app.core.config import settings
from app.core.timeutils import utcnow
from app.mcp.capability_tokens import issue_capability_token
from app.mcp.errors import (
    MCPError,
    MCPErrorCode,
)
from app.mcp.review_tools_client import ReviewToolsMCPClient
from app.mcp.review_tools_server import ALLOWED_MCP_TOOL_NAMES
from app.models.evidence import Evidence
from app.models.review_finding import ReviewFinding
from app.models.review_run import ReviewRun
from app.models.review_tool_call import ReviewToolCall
from app.models.review_verification_run import ReviewVerificationRun
from app.services.engineering_retrieval_service import get_index_status
from app.services.review_rule_service import load_rule_pack

# MCP preflight 契约版本（进入 input_state_hash）
MCP_TOOL_CONTRACT_VERSION = "1.0"
MCP_PREFLIGHT_VERSION = "5a2.1"

# MCP preflight 独立固定预算
MCP_INITIAL_CALLS = 2
MCP_MAX_RETRIES_PER_CALL = 1
MCP_MAX_TOTAL_CALLS = 4

# MCP 瞬时错误：仅重试一次
MCP_RETRYABLE_CODES = frozenset({
    MCPErrorCode.UNAVAILABLE,
    MCPErrorCode.TIMEOUT,
})

# 只对这几种检索错误执行一次局部恢复
RETRYABLE_ERROR_CODES = frozenset({
    "ENGINEERING_RETRIEVAL_INDEX_MISSING",
    "ENGINEERING_RETRIEVAL_INDEX_STALE",
})

COMPLETED_STATUSES = ("completed", "completed_with_warnings")


class VerificationServiceError(Exception):
    """工程 Verification 服务异常（带稳定错误码）。"""

    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def compute_input_state_hash(
    *,
    review_run_id: int,
    review_brief_hash: str | None,
    rule_pack_hash: str,
    findings: list[ReviewFinding],
    corpus_sha256: str,
    index_sha256: str,
    use_deepseek: bool,
    max_tool_calls: int,
    mcp_enabled: bool = False,
) -> str:
    """input_state_hash：规范 JSON 排序后 SHA-256。

    覆盖：review_run_id / brief hash / rule pack hash / Finding 的
    id/issue_code/status/conclusion/suggestion/evidence_ids /
    当前 corpus_sha256 / index_sha256 或状态 / use_deepseek /
    max_tool_calls / Prompt version。
    """
    payload: dict[str, Any] = {
        "review_run_id": review_run_id,
        "review_brief_hash": review_brief_hash,
        "rule_pack_hash": rule_pack_hash,
        "findings": [
            {
                "id": f.id,
                "issue_code": f.issue_code,
                "status": f.status,
                "conclusion": f.conclusion,
                "suggestion": f.suggestion,
                "evidence_ids": _parse_evidence_ids(f.evidence_ids_json),
            }
            for f in findings
        ],
        "corpus_sha256": corpus_sha256,
        "index_sha256": index_sha256,
        "use_deepseek": use_deepseek,
        "max_tool_calls": max_tool_calls,
        "prompt_version": PROMPT_VERSION,
        # 阶段 5A-2：MCP 语义输入（关闭时保持与原 hash 完全一致——不写入键）
        "mcp_enabled": mcp_enabled,
        "mcp_tool_contract_version": MCP_TOOL_CONTRACT_VERSION,
        "mcp_preflight_version": MCP_PREFLIGHT_VERSION,
    }
    # MCP 关闭时移除 MCP 相关键，保证 disabled 行为与 4C-2 完全一致
    if not mcp_enabled:
        payload.pop("mcp_enabled", None)
        payload.pop("mcp_tool_contract_version", None)
        payload.pop("mcp_preflight_version", None)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _parse_evidence_ids(raw: str) -> list[int]:
    try:
        data = json.loads(raw or "[]")
        return [int(x) for x in data] if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def _snapshot_index_state(
    db: Session, workspace_id: int, owner_user_id: int
) -> tuple[str, str]:
    """当前 corpus_sha256 / index_sha256（未构建时 index_sha 为空）。"""
    try:
        info = get_index_status(db, workspace_id, owner_user_id)
    except Exception:
        return "", ""
    return info.corpus_sha256 or "", info.index_sha256 or ""


def _build_planner_input(
    db: Session,
    run: ReviewRun,
    findings: list[ReviewFinding],
) -> PlannerInput:
    """组装规划输入：Finding 摘要 + 规则摘要 + Brief 摘要 + 排除检查类型。"""
    finding_dicts: list[dict[str, Any]] = []
    for f in findings:
        evidence_ids = _parse_evidence_ids(f.evidence_ids_json)
        locators: list[dict[str, Any]] = []
        if evidence_ids:
            evs = list(
                db.scalars(
                    select(Evidence).where(
                        Evidence.id.in_(evidence_ids),
                        Evidence.review_run_id == run.id,
                    )
                ).all()
            )
            locators = [
                {
                    "locator_type": e.locator_type,
                    "page_number": e.page_number,
                    "sheet_name": e.sheet_name,
                    "cell_range": e.cell_range,
                }
                for e in evs
            ]
        finding_dicts.append({
            "id": f.id,
            "issue_code": f.issue_code,
            "title": f.title,
            "severity": f.severity,
            "conclusion": f.conclusion,
            "suggestion": f.suggestion,
            "evidence_ids": evidence_ids,
            "evidence_locations": locators,
        })

    rule_summaries: list[dict[str, str]] = []
    try:
        pack = load_rule_pack(run.review_template_key)
        rule_summaries = [
            {"rule_id": r.rule_id, "title": r.title, "severity": r.severity,
             "suggestion": r.suggestion}
            for r in pack.rules
        ]
    except Exception:
        rule_summaries = []

    brief_summary = ""
    excluded_check_types: list[str] = []
    if run.review_brief_snapshot_json:
        try:
            brief_data = json.loads(run.review_brief_snapshot_json)
            interpreted = brief_data.get("interpreted_json")
            if isinstance(interpreted, str):
                interpreted = json.loads(interpreted)
            if isinstance(interpreted, dict):
                brief_summary = json.dumps(interpreted, ensure_ascii=False)
                excluded_check_types = list(
                    interpreted.get("excluded_check_types", []) or []
                )
        except (json.JSONDecodeError, ValueError):
            brief_summary = run.review_brief_snapshot_json[:800]

    return PlannerInput(
        findings=finding_dicts,
        rule_summaries=rule_summaries,
        brief_summary=brief_summary,
        excluded_check_types=excluded_check_types,
    )


def _validate_run_snapshot(db: Session, run: ReviewRun) -> None:
    """ReviewRun 快照完整性校验；异常时拒绝。"""
    if run.status != "completed":
        raise VerificationServiceError(
            "REVIEW_RUN_NOT_COMPLETED",
            "ReviewRun 必须为 completed 才能运行 Verification Agent",
        )
    if not run.rule_snapshot_json:
        raise VerificationServiceError(
            "REVIEW_RUN_SNAPSHOT_INVALID",
            "ReviewRun 缺少规则快照",
        )
    actual_hash = hashlib.sha256(run.rule_snapshot_json.encode("utf-8")).hexdigest()
    if actual_hash != run.rule_pack_hash:
        raise VerificationServiceError(
            "REVIEW_RUN_SNAPSHOT_INVALID",
            "ReviewRun 规则快照哈希不一致",
        )


def run_verification(
    db: Session,
    *,
    workspace_id: int,
    owner_user_id: int,
    review_run_id: int,
    use_deepseek: bool = False,
    max_tool_calls: int = 5,
    actor_user_id: int | None = None,
) -> tuple[dict[str, Any], bool]:
    """执行 Verification Agent；返回 (result, reused)。

    reused=True 表示命中幂等复用，未创建新运行。

    actor_user_id 为 API 层当前已认证用户的 id（5A-2：MCP 调用者身份）。
    为空时回退到 owner_user_id（保持 4C-2 直接调用兼容）。
    """
    caller_user_id = actor_user_id if actor_user_id is not None else owner_user_id
    run = db.scalar(
        select(ReviewRun).where(
            ReviewRun.id == review_run_id,
            ReviewRun.workspace_id == workspace_id,
            ReviewRun.owner_user_id == owner_user_id,
        )
    )
    if run is None:
        raise VerificationServiceError(
            "REVIEW_RUN_NOT_FOUND", "ReviewRun 不存在或无权访问", status_code=404
        )
    _validate_run_snapshot(db, run)

    findings = list(
        db.scalars(
            select(ReviewFinding)
            .where(ReviewFinding.review_run_id == run.id)
            .order_by(ReviewFinding.id.asc())
        ).all()
    )

    corpus_sha, index_sha = _snapshot_index_state(db, workspace_id, owner_user_id)
    state_hash = compute_input_state_hash(
        review_run_id=run.id,
        review_brief_hash=run.review_brief_hash,
        rule_pack_hash=run.rule_pack_hash,
        findings=findings,
        corpus_sha256=corpus_sha,
        index_sha256=index_sha,
        use_deepseek=use_deepseek,
        max_tool_calls=max_tool_calls,
        mcp_enabled=settings.engineering_mcp_enabled,
    )

    # 幂等复用：同 run + 同 hash + 成功状态（仅限本 workspace/owner）
    existing = db.scalar(
        select(ReviewVerificationRun)
        .where(
            ReviewVerificationRun.review_run_id == run.id,
            ReviewVerificationRun.input_state_hash == state_hash,
            ReviewVerificationRun.workspace_id == workspace_id,
            ReviewVerificationRun.owner_user_id == owner_user_id,
            ReviewVerificationRun.status.in_(COMPLETED_STATUSES),
        )
        .order_by(ReviewVerificationRun.id.desc())
    )
    if existing is not None:
        # 5A-2：因瞬时 MCP 错误导致的 warning run 不参与幂等复用，
        # 允许用户再次尝试（mcp_context.errors 含瞬时错误码）。
        if _run_has_transient_mcp_error(existing):
            existing = None
        else:
            return _build_result(db, existing, reused=True), True

    mcp_enabled = settings.engineering_mcp_enabled

    verification = ReviewVerificationRun(
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        review_run_id=run.id,
        status="planning",
        input_state_hash=state_hash,
        planner_type="deterministic",
        fallback_used=False,
        tool_budget=max(1, min(5, max_tool_calls)),
        tool_calls_used=0,
        candidate_count=0,
        warning_count=0,
        started_at=utcnow(),
    )
    db.add(verification)
    db.commit()
    db.refresh(verification)

    t0 = time.perf_counter()
    warnings: list[str] = []
    try:
        _execute_verification(
            db, verification, run, findings, use_deepseek, warnings,
            mcp_enabled=mcp_enabled, actor_user_id=caller_user_id,
        )
    except VerificationServiceError:
        raise
    except Exception as e:
        verification.status = "failed"
        verification.error_code = "ENGINEERING_VERIFICATION_ERROR"
        verification.error_message = "Verification 执行失败"
        verification.completed_at = utcnow()
        db.commit()
        raise VerificationServiceError(
            "ENGINEERING_VERIFICATION_ERROR", "Verification 执行失败", status_code=500
        ) from e

    latency_ms = int((time.perf_counter() - t0) * 1000)
    verification.completed_at = utcnow()
    if verification.warning_count > 0 or warnings:
        verification.status = "completed_with_warnings"
    else:
        verification.status = "completed"
    db.commit()
    result = _build_result(db, verification, reused=False, latency_ms=latency_ms)
    return result, False


def _persisted_mcp_enabled(plan_data: dict[str, Any]) -> bool:
    """从持久化 plan_json.mcp_context 读取历史 mcp_enabled（不读当前 settings）。"""
    ctx = plan_data.get("mcp_context")
    if not isinstance(ctx, dict):
        return False
    return bool(ctx.get("enabled", False))


def _mcp_unresolved_errors(plan_data: dict[str, Any]) -> list[str]:
    """mcp_context 中未解决的错误（两次均失败或非重试错误）。"""
    ctx = plan_data.get("mcp_context")
    if not isinstance(ctx, dict):
        return []
    errors = ctx.get("errors") or []
    return [e for e in errors if isinstance(e, str)]


def _run_has_transient_mcp_error(verification: ReviewVerificationRun) -> bool:
    """判定 Run 是否因瞬时 MCP 错误而 warning（不参与幂等复用）。"""
    if verification.status != "completed_with_warnings":
        return False
    if not verification.plan_json:
        return False
    try:
        plan = json.loads(verification.plan_json)
    except json.JSONDecodeError:
        return False
    ctx = plan.get("mcp_context")
    if not isinstance(ctx, dict):
        return False
    # 仅当存在“未解决”的瞬时错误时才不参与幂等；
    # 已恢复（attempt2 成功）的错误不在 errors 中（见 recovered_errors）。
    errors = _mcp_unresolved_errors(plan)
    return any(e in MCP_RETRYABLE_CODES for e in errors)


def _execute_verification(
    db: Session,
    verification: ReviewVerificationRun,
    run: ReviewRun,
    findings: list[ReviewFinding],
    use_deepseek: bool,
    warnings: list[str],
    *,
    mcp_enabled: bool = False,
    actor_user_id: int | None = None,
) -> None:
    """MCP preflight → 规划 → 执行工具 → 局部重试 → 候选收集。"""
    mcp_context: dict[str, Any] | None = None
    if mcp_enabled:
        mcp_context = _run_mcp_preflight(
            db, verification, run, actor_user_id or run.owner_user_id, warnings,
        )

    planner_input = _build_planner_input(db, run, findings)

    verification.status = "running"
    db.commit()

    if use_deepseek:
        result = deepseek_plan(planner_input, max_tool_calls=verification.tool_budget)
        plan = result.plan
        if plan is None:
            plan, _ = deterministic_plan(planner_input, max_tool_calls=verification.tool_budget)
        # planner_type 三态语义：
        #   deepseek               → 模型返回合法计划（fallback_used=false）
        #   deterministic_fallback → 模型被尝试但失败，最终决策来自确定性 fallback
        verification.planner_type = (
            "deepseek" if not result.fallback_used else "deterministic_fallback"
        )
        verification.fallback_used = result.fallback_used
        verification.fallback_reason = result.fallback_reason
        verification.model_provider = _llm_provider_label(result.llm)
        verification.model_name = _llm_model_name(result.llm)
        verification.prompt_version = PROMPT_VERSION
        verification.token_usage_json = (
            json.dumps(result.llm.token_usage, ensure_ascii=False)
            if result.llm and result.llm.token_usage
            else None
        )
        if result.fallback_used and result.fallback_reason:
            warnings.append(f"DeepSeek fallback: {result.fallback_reason}")
    else:
        plan, _ = deterministic_plan(planner_input, max_tool_calls=verification.tool_budget)
        verification.planner_type = "deterministic"
        verification.fallback_used = False

    plan_data = plan.model_dump()
    if mcp_context is not None:
        plan_data["mcp_context"] = mcp_context
    verification.plan_json = json.dumps(plan_data, ensure_ascii=False)
    db.commit()

    finding_map = {f.id: f for f in findings}
    candidate_total = 0
    success_count = 0
    failed_count = 0
    retry_count = 0

    for decision in plan.decisions:
        if decision.decision != "retrieve":
            continue
        finding = finding_map.get(decision.finding_id)
        if finding is None:
            warnings.append(f"计划引用不存在的 finding_id={decision.finding_id}")
            verification.warning_count += 1
            continue

        tool_input = {
            "finding_id": decision.finding_id,
            "query": decision.query,
            "top_k": decision.top_k,
            "retrieval_mode": decision.retrieval_mode,
            "reason": decision.reason,
        }

        # attempt 1（预算耗尽等 EngineeringToolError 按 warning 记录，不穿透为 500）
        try:
            output1, tc1 = execute_engineering_tool(
                db,
                agent_type=ALLOWED_AGENT_TYPE,
                tool_name=ENGINEERING_TOOL_HYBRID_RETRIEVAL,
                input_data=tool_input,
                verification_run=verification,
                review_run_id=run.id,
                review_finding_id=finding.id,
                workspace_id=run.workspace_id,
                owner_user_id=run.owner_user_id,
                node_name="verification",
                attempt_number=1,
            )
        except EngineeringToolError as e:
            warnings.append(f"findings[{finding.id}] 检索被拒: {e.code}")
            verification.warning_count += 1
            continue

        if output1.get("status") == "failed":
            error_code = output1.get("error_code", "")
            failed_count += 1
            if error_code in RETRYABLE_ERROR_CODES:
                # 局部恢复：prepare 索引 → 仅重试该检索（attempt 2）
                try:
                    prepare_input = {
                        "rebuild": True,
                        "reason": f"检索失败 {error_code}，准备索引后重试",
                    }
                    prepare_out, _ = execute_engineering_tool(
                        db,
                        agent_type=ALLOWED_AGENT_TYPE,
                        tool_name=ENGINEERING_TOOL_INDEX_PREPARE,
                        input_data=prepare_input,
                        verification_run=verification,
                        review_run_id=run.id,
                        review_finding_id=finding.id,
                        workspace_id=run.workspace_id,
                        owner_user_id=run.owner_user_id,
                        node_name="verification_retry",
                        attempt_number=1,
                    )
                    if prepare_out.get("status") == "failed":
                        warnings.append(
                            f"findings[{finding.id}] 索引准备失败: "
                            f"{prepare_out.get('error_code', '')}"
                        )
                        verification.warning_count += 1
                        continue
                except EngineeringToolError as e:
                    warnings.append(
                        f"findings[{finding.id}] 索引准备被拒: {e.code}"
                    )
                    verification.warning_count += 1
                    continue

                # attempt 2：仅重试原检索，retry_of_id 指向 attempt 1
                try:
                    output2, tc2 = execute_engineering_tool(
                        db,
                        agent_type=ALLOWED_AGENT_TYPE,
                        tool_name=ENGINEERING_TOOL_HYBRID_RETRIEVAL,
                        input_data=tool_input,
                        verification_run=verification,
                        review_run_id=run.id,
                        review_finding_id=finding.id,
                        workspace_id=run.workspace_id,
                        owner_user_id=run.owner_user_id,
                        node_name="verification_retry",
                        attempt_number=2,
                        retry_of_id=tc1.id,
                    )
                except EngineeringToolError as e:
                    warnings.append(
                        f"findings[{finding.id}] 重试被拒: {e.code}"
                    )
                    verification.warning_count += 1
                    continue
                retry_count += 1
                if output2.get("status") == "failed":
                    warnings.append(
                        f"findings[{finding.id}] 重试仍失败: "
                        f"{output2.get('error_code', '')}"
                    )
                    verification.warning_count += 1
                    continue
                _collect_candidates(output2, verification)
                candidate_total += len(output2.get("results", []))
                success_count += 1
            else:
                # MODEL_UNAVAILABLE / INDEX_ERROR / QUERY_INVALID / BUDGET：不重试
                warnings.append(
                    f"findings[{finding.id}] 检索失败: {error_code}（不重试）"
                )
                verification.warning_count += 1
        else:
            _collect_candidates(output1, verification)
            candidate_total += len(output1.get("results", []))
            success_count += 1

    verification.candidate_count = candidate_total
    verification.warning_count = len(warnings)
    verification.tool_calls_used = verification.tool_calls_used  # registry 已累加
    db.commit()


# ── MCP preflight（阶段 5A-2）─────────────────────────────────────


def _write_mcp_tool_call(
    db: Session,
    *,
    verification: ReviewVerificationRun,
    run: ReviewRun,
    tool_name: str,
    attempt_number: int,
    retry_of_id: int | None,
    input_data: dict[str, Any],
    status: str,
    output_data: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    latency_ms: int | None = None,
) -> ReviewToolCall:
    """写一条 MCP ToolCall（只追加；input 不含 token/secret）。"""
    record = ReviewToolCall(
        verification_run_id=verification.id,
        review_run_id=run.id,
        review_finding_id=None,
        workspace_id=run.workspace_id,
        owner_user_id=run.owner_user_id,
        node_name="mcp_preflight",
        tool_name=tool_name,
        attempt_number=attempt_number,
        retry_of_id=retry_of_id,
        status=status,
        input_json=json.dumps(input_data, ensure_ascii=False)[:8000],
        output_json=(
            json.dumps(output_data, ensure_ascii=False)[:30000]
            if output_data is not None else None
        ),
        error_code=error_code,
        error_message=error_message,
        latency_ms=latency_ms,
        completed_at=utcnow() if status != "running" else None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _build_mcp_search_query(
    findings: list[ReviewFinding], run: ReviewRun
) -> str:
    """确定性构建 search_review_rules 的 query（不超过 500 字符）。

    优先级从当前 ReviewRun 的不可变 rule_snapshot_json 解析规则类型，
    并通过 Finding.rule_id 映射：
        evidence_required > cross_file_equal > high severity > 其余
    同优先级按 Finding.id 稳定排序。
    不读取磁盘最新规则包；快照损坏或 rule_id 无法映射时按确定性安全策略
    （把该 Finding 视为“其余”级别，不因单条无法映射而失败）。
    """
    if not findings:
        return "工程审查规则"

    # 从 Run 固化快照解析规则类型（失败时全部视为未知，走安全策略）
    rule_type_by_id: dict[str, str] = {}
    try:
        from app.services.review_rule_service import load_rule_pack_from_snapshot

        pack = load_rule_pack_from_snapshot(run.rule_snapshot_json, run.rule_pack_hash)
        rule_type_by_id = {r.rule_id: r.type for r in pack.rules}
    except Exception:
        rule_type_by_id = {}

    def _priority(f: ReviewFinding) -> int:
        rtype = rule_type_by_id.get(f.rule_id, "")
        if rtype == "evidence_required":
            return 0
        if rtype == "cross_file_equal":
            return 1
        if f.severity == "high":
            return 2
        return 3

    # 稳定排序：优先级 + Finding.id
    top = sorted(findings, key=lambda f: (_priority(f), f.id))[0]
    parts = [top.issue_code, top.title]
    conclusion = (top.conclusion or "").strip()
    if conclusion and len(conclusion) <= 200:
        parts.append(conclusion)
    query = " ".join(dict.fromkeys(parts)).strip()
    return query[:500] or "工程审查规则"


def _run_mcp_preflight(
    db: Session,
    verification: ReviewVerificationRun,
    run: ReviewRun,
    actor_user_id: int,
    warnings: list[str],
) -> dict[str, Any]:
    """每个新 VerificationRun 在 planner 前执行固定 MCP preflight。

    第一步 run_bid_consistency_checks；第二步 search_review_rules。
    独立预算：MCP_INITIAL_CALLS=2，每工具最多重试 1 次，总上限 4。
    仅 UNAVAILABLE/TIMEOUT 重试一次；其余错误不重试。
    返回 mcp_context 结构；失败时由 warnings 说明。
    """
    mcp_context: dict[str, Any] = {
        "enabled": True,
        "contract_version": MCP_TOOL_CONTRACT_VERSION,
        "preflight_version": MCP_PREFLIGHT_VERSION,
        "results": {},
        "errors": [],
        "warnings": [],
        "recovered_errors": [],
    }
    total_calls = 0

    try:
        capability_token = issue_capability_token(actor_user_id)
        client = ReviewToolsMCPClient(
            internal_token=capability_token,
            timeout_seconds=settings.engineering_mcp_timeout_seconds,
            require_enabled=False,
        )
    except Exception:
        warnings.append("MCP context 不完整：无法签发调用者凭据")
        mcp_context.setdefault("errors", []).append("capability_issue_error")
        mcp_context.setdefault("warnings", []).append(
            "MCP 调用者凭据签发失败，核验上下文不完整")
        verification.warning_count += 1
        return mcp_context

    # 发现并校验工具（不成功则整个 preflight 记为不完整）
    try:
        tools = client.discover_tools_sync()
        if set(tools) != set(ALLOWED_MCP_TOOL_NAMES):
            raise MCPError(MCPErrorCode.DISCOVERY_ERROR, "MCP 工具清单不符合预期")
        mcp_context["discovered_tools"] = sorted(tools)
    except MCPError as exc:
        warnings.append(f"MCP context 不完整：工具发现失败（{exc.code}）")
        mcp_context.setdefault("errors", []).append(exc.code)
        mcp_context.setdefault("warnings", []).append(
            "MCP 工具发现失败，核验上下文不完整")
        verification.warning_count += 1
        return mcp_context

    # 第一步：run_bid_consistency_checks
    total_calls = _mcp_call_with_retry(
        db, verification, run, client,
        tool_name="run_bid_consistency_checks",
        arguments={"workspace_id": run.workspace_id, "review_run_id": run.id,
                   "request_id": f"v5a2-consistency-{verification.id}"},
        mcp_context=mcp_context, warnings=warnings, total_calls=total_calls,
    )

    # 第二步：search_review_rules
    findings = list(
        db.scalars(
            select(ReviewFinding)
            .where(ReviewFinding.review_run_id == run.id)
            .order_by(ReviewFinding.id.asc())
        ).all()
    )
    query = _build_mcp_search_query(findings, run)
    total_calls = _mcp_call_with_retry(
        db, verification, run, client,
        tool_name="search_review_rules",
        arguments={"workspace_id": run.workspace_id, "review_run_id": run.id,
                   "query": query, "top_k": 5,
                   "request_id": f"v5a2-rules-{verification.id}"},
        mcp_context=mcp_context, warnings=warnings, total_calls=total_calls,
    )

    mcp_context["total_calls"] = total_calls
    return mcp_context


def _mcp_call_with_retry(
    db: Session,
    verification: ReviewVerificationRun,
    run: ReviewRun,
    client: ReviewToolsMCPClient,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    mcp_context: dict[str, Any],
    warnings: list[str],
    total_calls: int,
) -> int:
    """执行单个 MCP 工具（含一次瞬时错误重试）。返回累计调用数。"""
    if total_calls >= MCP_MAX_TOTAL_CALLS:
        warnings.append(f"MCP context 不完整：MCP 调用预算耗尽（{tool_name} 跳过）")
        mcp_context.setdefault("errors", []).append("mcp_budget_exceeded")
        mcp_context.setdefault("warnings", []).append(
            "MCP 调用预算耗尽，部分核验未执行")
        verification.warning_count += 1
        return total_calls

    # attempt 1
    total_calls += 1
    first, first_err, first_latency = _execute_mcp_call(client, tool_name, arguments)
    if first_err is None:
        _write_mcp_tool_call(
            db, verification=verification, run=run, tool_name=tool_name,
            attempt_number=1, retry_of_id=None, input_data=arguments,
            status="success", output_data=first, latency_ms=first_latency,
        )
        mcp_context["results"][tool_name] = first
        return total_calls

    failed_record = _write_mcp_tool_call(
        db, verification=verification, run=run, tool_name=tool_name,
        attempt_number=1, retry_of_id=None, input_data=arguments,
        status="failed", error_code=first_err.code, error_message=first_err.message,
        latency_ms=first_latency,
    )

    # 仅瞬时错误重试一次
    if first_err.code in MCP_RETRYABLE_CODES and total_calls < MCP_MAX_TOTAL_CALLS:
        total_calls += 1
        second, second_err, second_latency = _execute_mcp_call(client, tool_name, arguments)
        if second_err is None:
            _write_mcp_tool_call(
                db, verification=verification, run=run, tool_name=tool_name,
                attempt_number=2, retry_of_id=failed_record.id, input_data=arguments,
                status="success", output_data=second, latency_ms=second_latency,
            )
            # 已恢复错误：attempt1 失败保留在 ToolCall 审计链，
            # 但不进入 mcp_context.errors（记录在 recovered_errors）
            mcp_context.setdefault("recovered_errors", []).append({
                "tool_name": tool_name, "error_code": first_err.code,
                "attempt_number": 1,
            })
            mcp_context["results"][tool_name] = second
            return total_calls
        _write_mcp_tool_call(
            db, verification=verification, run=run, tool_name=tool_name,
            attempt_number=2, retry_of_id=failed_record.id, input_data=arguments,
            status="failed", error_code=second_err.code, error_message=second_err.message,
            latency_ms=second_latency,
        )
        # 未解决错误：保留在 errors
        mcp_context.setdefault("errors", []).append(first_err.code)
        mcp_context.setdefault("errors", []).append(second_err.code)
        warnings.append(f"MCP context 不完整：{tool_name} 重试仍失败（{second_err.code}）")
        verification.warning_count += 1
        return total_calls

    # 非重试错误：未解决，保留在 errors
    mcp_context.setdefault("errors", []).append(first_err.code)
    warnings.append(f"MCP context 不完整：{tool_name} 失败（{first_err.code}）")
    verification.warning_count += 1
    return total_calls


def _execute_mcp_call(
    client: ReviewToolsMCPClient, tool_name: str, arguments: dict[str, Any]
) -> tuple[dict[str, Any] | None, MCPError | None, int | None]:
    """执行一次 MCP 调用，返回 (output, error, latency_ms)。"""
    import time as _time

    start = _time.perf_counter()
    try:
        output = client.call_tool_sync(tool_name, arguments)
        latency = int((_time.perf_counter() - start) * 1000)
        return output, None, latency
    except MCPError as exc:
        latency = int((_time.perf_counter() - start) * 1000)
        return None, exc, latency
    except Exception:
        latency = int((_time.perf_counter() - start) * 1000)
        return None, MCPError(MCPErrorCode.TOOL_ERROR, "MCP 工具执行失败"), latency


def _collect_candidates(output: dict[str, Any], verification: ReviewVerificationRun) -> None:
    """检索命中只作为候选证据（candidate_only 已在工具输出标注）。"""
    # 候选计数已由调用方按 results 数累加；此处不做任何 Finding/Evidence 写入
    return None


def _llm_provider_label(llm_result: Any) -> str | None:
    if llm_result is None:
        return None
    from app.core.config import settings
    return settings.llm_provider if settings.llm_provider else "deepseek"


def _llm_model_name(llm_result: Any) -> str | None:
    from app.core.config import settings
    return settings.llm_model or None


# ── 结果组装 ─────────────────────────────────────────────────────────


def _build_result(
    db: Session,
    verification: ReviewVerificationRun,
    *,
    reused: bool,
    latency_ms: int | None = None,
) -> dict[str, Any]:
    plan_data = {}
    if verification.plan_json:
        try:
            plan_data = json.loads(verification.plan_json)
        except json.JSONDecodeError:
            plan_data = {}

    tool_calls = list(
        db.scalars(
            select(ReviewToolCall)
            .where(ReviewToolCall.verification_run_id == verification.id)
            .order_by(ReviewToolCall.id.asc())
        ).all()
    )
    success_count = sum(1 for t in tool_calls if t.status == "success")
    failed_count = sum(1 for t in tool_calls if t.status == "failed")
    retry_count = sum(1 for t in tool_calls if t.attempt_number > 1)
    # 合并 mcp_context 未解决错误与失败 ToolCall 警告（去重、稳定排序）
    merged_warnings: list[str] = []
    for code in sorted(set(_mcp_unresolved_errors(plan_data))):
        merged_warnings.append(_MCP_ERROR_WARNING_TEMPLATE.get(code, f"MCP 核验未完成（{code}）"))
    for w in _warnings_from_tool_calls(tool_calls):
        if w not in merged_warnings:
            merged_warnings.append(w)
    # 阶段 5A-2：分离 MCP 与候选检索计数（按 node_name 动态计算，无迁移）
    mcp_calls = [t for t in tool_calls if t.node_name == "mcp_preflight"]
    retrieval_calls = [t for t in tool_calls if t.node_name != "mcp_preflight"]
    mcp_tool_call_count = len(mcp_calls)
    retrieval_tool_call_count = len(retrieval_calls)
    mcp_retry_count = sum(1 for t in mcp_calls if t.attempt_number > 1)

    index_sha = ""
    corpus_sha = ""
    for t in tool_calls:
        if t.index_sha256:
            index_sha = t.index_sha256
        if t.corpus_sha256:
            corpus_sha = t.corpus_sha256

    return {
        "verification_run_id": verification.id,
        "status": verification.status,
        "reused": reused,
        "workspace_id": verification.workspace_id,
        "owner_user_id": verification.owner_user_id,
        "review_run_id": verification.review_run_id,
        "planner_type": verification.planner_type,
        "fallback_used": verification.fallback_used,
        "fallback_reason": verification.fallback_reason,
        "model_provider": verification.model_provider,
        "model_name": verification.model_name,
        "prompt_version": verification.prompt_version,
        "token_usage": (
            json.loads(verification.token_usage_json)
            if verification.token_usage_json
            else None
        ),
        "input_state_hash": verification.input_state_hash,
        "plan": plan_data,
        "tool_budget": verification.tool_budget,
        "tool_calls_used": verification.tool_calls_used,
        # 阶段 5A-2：预算分离（向后兼容扩展，旧字段语义不变）
        "retrieval_budget": verification.tool_budget,
        "retrieval_tool_call_count": retrieval_tool_call_count,
        "mcp_tool_call_count": mcp_tool_call_count,
        "total_tool_call_count": len(tool_calls),
        "mcp_retry_count": mcp_retry_count,
        # 历史 mcp_enabled 从持久化 plan_json.mcp_context.enabled 读取；
        # 旧 4C-2 记录无 mcp_context 时安全返回 false。
        "mcp_enabled": _persisted_mcp_enabled(plan_data),
        "success_count": success_count,
        "failed_count": failed_count,
        "retry_count": retry_count,
        "candidate_count": verification.candidate_count,
        "warning_count": verification.warning_count,
        "warnings": merged_warnings,
        "index_sha256": index_sha,
        "corpus_sha256": corpus_sha,
        "latency_ms": latency_ms,
        "created_at": verification.created_at.isoformat() if verification.created_at else None,
        "completed_at": verification.completed_at.isoformat() if verification.completed_at else None,
    }


_MCP_ERROR_WARNING_TEMPLATE = {
    "ENGINEERING_MCP_UNAVAILABLE": "MCP 服务不可用，核验上下文不完整；可稍后重试",
    "ENGINEERING_MCP_TIMEOUT": "MCP 服务响应超时，核验上下文不完整；可稍后重试",
    "ENGINEERING_MCP_DISCOVERY_ERROR": "MCP 工具发现失败，核验上下文不完整",
    "ENGINEERING_MCP_TOOL_NOT_ALLOWED": "MCP 工具未授权，核验上下文不完整",
    "ENGINEERING_MCP_REQUEST_INVALID": "MCP 请求参数不合法，核验上下文不完整",
    "ENGINEERING_MCP_RESPONSE_INVALID": "MCP 响应不合法，核验上下文不完整",
    "ENGINEERING_MCP_TOOL_ERROR": "MCP 工具执行失败，核验上下文不完整",
    "mcp_budget_exceeded": "MCP 调用预算耗尽，部分核验未执行",
    "capability_issue_error": "MCP 调用者凭据签发失败，核验上下文不完整",
}


def _warnings_from_tool_calls(tool_calls: list[ReviewToolCall]) -> list[str]:
    """失败 ToolCall → 安全警告；已被成功 retry 覆盖的失败 attempt 不视为未解决。

    识别方式：attempt_number>1 且 status=success 的 ToolCall.retry_of_id
    指向的失败 attempt 视为已恢复，不产生警告。
    """
    recovered_ids: set[int] = set()
    for t in tool_calls:
        if t.attempt_number > 1 and t.status == "success" and t.retry_of_id:
            recovered_ids.add(t.retry_of_id)

    items: list[str] = []
    for t in tool_calls:
        if t.status == "failed" and t.error_code:
            if t.id in recovered_ids:
                continue  # 已恢复（attempt2 成功）
            items.append(
                f"{t.tool_name} (attempt {t.attempt_number}) 失败: {t.error_code}"
            )
    return items


def list_verification_runs(
    db: Session, workspace_id: int, owner_user_id: int, review_run_id: int
) -> list[dict[str, Any]]:
    run = db.scalar(
        select(ReviewRun).where(
            ReviewRun.id == review_run_id,
            ReviewRun.workspace_id == workspace_id,
            ReviewRun.owner_user_id == owner_user_id,
        )
    )
    if run is None:
        raise VerificationServiceError(
            "REVIEW_RUN_NOT_FOUND", "ReviewRun 不存在或无权访问", status_code=404
        )
    runs = list(
        db.scalars(
            select(ReviewVerificationRun)
            .where(
                ReviewVerificationRun.review_run_id == review_run_id,
                ReviewVerificationRun.workspace_id == workspace_id,
                ReviewVerificationRun.owner_user_id == owner_user_id,
            )
            .order_by(ReviewVerificationRun.id.desc())
        ).all()
    )
    return [_build_result(db, r, reused=False) for r in runs]


def get_verification_run(
    db: Session,
    workspace_id: int,
    owner_user_id: int,
    review_run_id: int,
    verification_run_id: int,
) -> dict[str, Any]:
    run = db.scalar(
        select(ReviewRun).where(
            ReviewRun.id == review_run_id,
            ReviewRun.workspace_id == workspace_id,
            ReviewRun.owner_user_id == owner_user_id,
        )
    )
    if run is None:
        raise VerificationServiceError(
            "REVIEW_RUN_NOT_FOUND", "ReviewRun 不存在或无权访问", status_code=404
        )
    verification = db.scalar(
        select(ReviewVerificationRun).where(
            ReviewVerificationRun.id == verification_run_id,
            ReviewVerificationRun.review_run_id == review_run_id,
            ReviewVerificationRun.workspace_id == workspace_id,
            ReviewVerificationRun.owner_user_id == owner_user_id,
        )
    )
    if verification is None:
        raise VerificationServiceError(
            "VERIFICATION_RUN_NOT_FOUND",
            "VerificationRun 不存在或无权访问",
            status_code=404,
        )
    return _build_result(db, verification, reused=False)


def list_verification_tool_calls(
    db: Session,
    workspace_id: int,
    owner_user_id: int,
    review_run_id: int,
    verification_run_id: int,
) -> list[dict[str, Any]]:
    get_verification_run(db, workspace_id, owner_user_id, review_run_id, verification_run_id)
    calls = list(
        db.scalars(
            select(ReviewToolCall)
            .where(
                ReviewToolCall.verification_run_id == verification_run_id,
                ReviewToolCall.workspace_id == workspace_id,
                ReviewToolCall.owner_user_id == owner_user_id,
            )
            .order_by(ReviewToolCall.id.asc())
        ).all()
    )
    return [
        {
            "id": t.id,
            "verification_run_id": t.verification_run_id,
            "review_run_id": t.review_run_id,
            "review_finding_id": t.review_finding_id,
            "node_name": t.node_name,
            "tool_name": t.tool_name,
            "attempt_number": t.attempt_number,
            "retry_of_id": t.retry_of_id,
            "status": t.status,
            "input": _safe_json(t.input_json),
            "output": _safe_json(t.output_json),
            "error_code": t.error_code,
            "error_message": t.error_message,
            "latency_ms": t.latency_ms,
            "index_sha256": t.index_sha256,
            "corpus_sha256": t.corpus_sha256,
            "model_revision": t.model_revision,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }
        for t in calls
    ]


def _safe_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
