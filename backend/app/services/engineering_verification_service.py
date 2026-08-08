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
from app.core.timeutils import utcnow
from app.models.evidence import Evidence
from app.models.review_finding import ReviewFinding
from app.models.review_run import ReviewRun
from app.models.review_tool_call import ReviewToolCall
from app.models.review_verification_run import ReviewVerificationRun
from app.services.engineering_retrieval_service import get_index_status
from app.services.review_rule_service import load_rule_pack

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
    }
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
) -> tuple[dict[str, Any], bool]:
    """执行 Verification Agent；返回 (result, reused)。

    reused=True 表示命中幂等复用，未创建新运行。
    """
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
        return _build_result(db, existing, reused=True), True

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
        _execute_verification(db, verification, run, findings, use_deepseek, warnings)
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


def _execute_verification(
    db: Session,
    verification: ReviewVerificationRun,
    run: ReviewRun,
    findings: list[ReviewFinding],
    use_deepseek: bool,
    warnings: list[str],
) -> None:
    """规划 → 执行工具 → 局部重试 → 候选收集。"""
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

    verification.plan_json = json.dumps(
        plan.model_dump(), ensure_ascii=False
    )
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
        "success_count": success_count,
        "failed_count": failed_count,
        "retry_count": retry_count,
        "candidate_count": verification.candidate_count,
        "warning_count": verification.warning_count,
        "warnings": _warnings_from_tool_calls(tool_calls),
        "index_sha256": index_sha,
        "corpus_sha256": corpus_sha,
        "latency_ms": latency_ms,
        "created_at": verification.created_at.isoformat() if verification.created_at else None,
        "completed_at": verification.completed_at.isoformat() if verification.completed_at else None,
    }


def _warnings_from_tool_calls(tool_calls: list[ReviewToolCall]) -> list[str]:
    items: list[str] = []
    for t in tool_calls:
        if t.status == "failed" and t.error_code:
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
