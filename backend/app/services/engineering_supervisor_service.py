"""工程 Supervisor 编排与确定性质量门（阶段 5B）。

确定性状态机：Extraction → Verification → Quality Review → Reporting。
不新增第二次 LLM 规划；DeepSeek 仅沿用 Verification Agent 已有规划能力。
Supervisor 只根据结构化状态、错误码和质量门结果决定下一步。

约束：
- 不修改 Finding/Evidence/历史 Report；不自动接受候选证据
- 相同稳定输入幂等复用；因暂时错误进入 needs_human/failed 的运行不伪装成功复用
- 质量门失败或 needs_information 时严禁生成报告
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timeutils import utcnow
from app.models.evidence import Evidence
from app.models.file import File
from app.models.review_finding import ReviewFinding
from app.models.review_report import ReviewReport
from app.models.review_run import ReviewRun
from app.models.review_supervisor_run import ReviewSupervisorRun
from app.models.review_supervisor_step import ReviewSupervisorStep
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.services.engineering_retrieval_service import (
    build_workspace_corpus,
    get_index_status,
)
from app.services.engineering_verification_service import (
    MCP_PREFLIGHT_VERSION,
    MCP_TOOL_CONTRACT_VERSION,
    PROMPT_VERSION as VERIFICATION_PROMPT_VERSION,
    compute_input_state_hash as verification_hash,
    run_verification,
)
from app.services.review_report_service import (
    ReviewReportError,
    generate_review_report,
)
from app.services.review_rule_service import (
    RuleLoadError,
    load_rule_pack_from_snapshot,
)

GRAPH_VERSION = "5b.1"
QUALITY_GATE_VERSION = "1.0"
MAX_STEP_RETRIES_DEFAULT = 1

SUPERVISOR_NODE_ORDER = ("extraction", "verification", "quality_review", "reporting")

COMPLETED_STATUSES = (
    "completed", "completed_with_warnings", "ready_to_report",
)
NEEDS_HUMAN_STATUSES = ("needs_human", "failed")

# 稳定质量门失败类型
GATE_EVIDENCE_MISSING = "EVIDENCE_MISSING"
GATE_EVIDENCE_INVALID = "EVIDENCE_INVALID"
GATE_EVIDENCE_STALE = "EVIDENCE_STALE"
GATE_RULE_NOT_FOUND = "RULE_NOT_FOUND"
GATE_RULE_VERSION_MISMATCH = "RULE_VERSION_MISMATCH"
GATE_RULE_INPUT_MISSING = "RULE_INPUT_MISSING"
GATE_NUMERIC_PROVENANCE_MISSING = "NUMERIC_PROVENANCE_MISSING"
GATE_PERMANENT = "PERMANENT_VALIDATION_ERROR"


class SupervisorServiceError(Exception):
    """工程 Supervisor 服务异常（带稳定错误码）。"""

    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ── input_state_hash ──────────────────────────────────────────────


def compute_supervisor_input_hash(
    *,
    review_run_id: int,
    review_brief_hash: str | None,
    rule_pack_hash: str,
    findings: list[ReviewFinding],
    evidences: list[Evidence],
    corpus_sha256: str,
    index_sha256: str,
    mcp_enabled: bool,
    use_deepseek: bool,
    max_verification_tool_calls: int,
    max_step_retries: int,
    generate_report: bool,
) -> str:
    """规范 JSON sort_keys SHA-256（覆盖 Supervisor 全部稳定输入）。"""
    payload: dict[str, Any] = {
        "review_run_id": review_run_id,
        "review_brief_hash": review_brief_hash,
        "rule_pack_hash": rule_pack_hash,
        "findings": [
            {
                "id": f.id, "issue_code": f.issue_code, "status": f.status,
                "conclusion": f.conclusion, "suggestion": f.suggestion,
                "evidence_ids": _parse_json_list(f.evidence_ids_json),
            }
            for f in findings
        ],
        "evidences": [
            {
                "id": e.id, "file_id": e.file_id, "locator_type": e.locator_type,
                "page_number": e.page_number, "sheet_name": e.sheet_name,
                "cell_range": e.cell_range, "content_hash": e.content_hash,
            }
            for e in evidences
        ],
        "corpus_sha256": corpus_sha256,
        "index_sha256": index_sha256,
        "mcp_enabled": mcp_enabled,
        "mcp_tool_contract_version": MCP_TOOL_CONTRACT_VERSION,
        "mcp_preflight_version": MCP_PREFLIGHT_VERSION,
        "verification_prompt_version": VERIFICATION_PROMPT_VERSION,
        "supervisor_graph_version": GRAPH_VERSION,
        "quality_gate_version": QUALITY_GATE_VERSION,
        "use_deepseek": use_deepseek,
        "max_verification_tool_calls": max_verification_tool_calls,
        "max_step_retries": max_step_retries,
        "generate_report": generate_report,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _parse_json_list(raw: str) -> list[int]:
    try:
        data = json.loads(raw or "[]")
        return [int(x) for x in data] if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


# ── 主入口 ─────────────────────────────────────────────────────────


def run_supervisor(
    db: Session,
    *,
    workspace_id: int,
    owner_user_id: int,
    review_run_id: int,
    actor_user_id: int | None = None,
    use_deepseek: bool = False,
    max_verification_tool_calls: int = 5,
    max_step_retries: int = MAX_STEP_RETRIES_DEFAULT,
    generate_report: bool = False,
) -> tuple[dict[str, Any], bool]:
    """执行 Supervisor 状态机；返回 (result, reused)。"""
    caller_user_id = actor_user_id if actor_user_id is not None else owner_user_id
    run = db.scalar(
        select(ReviewRun).where(
            ReviewRun.id == review_run_id,
            ReviewRun.workspace_id == workspace_id,
            ReviewRun.owner_user_id == owner_user_id,
        )
    )
    if run is None:
        raise SupervisorServiceError(
            "SUPERVISOR_RUN_NOT_FOUND", "ReviewRun 不存在或无权访问", status_code=404
        )
    if run.status != "completed":
        raise SupervisorServiceError(
            "SUPERVISOR_RUN_NOT_COMPLETED",
            "ReviewRun 必须为 completed 才能执行 Supervisor",
        )
    if not run.rule_snapshot_json or not run.rule_pack_hash:
        raise SupervisorServiceError(
            "SUPERVISOR_SNAPSHOT_INVALID", "ReviewRun 快照不完整"
        )

    findings = list(
        db.scalars(
            select(ReviewFinding)
            .where(ReviewFinding.review_run_id == run.id)
            .order_by(ReviewFinding.id.asc())
        ).all()
    )
    evidences = list(
        db.scalars(
            select(Evidence)
            .where(Evidence.review_run_id == run.id)
            .order_by(Evidence.id.asc())
        ).all()
    )
    corpus_sha, index_sha = _index_state(db, workspace_id, owner_user_id)
    mcp_enabled = settings.engineering_mcp_enabled

    state_hash = compute_supervisor_input_hash(
        review_run_id=run.id,
        review_brief_hash=run.review_brief_hash,
        rule_pack_hash=run.rule_pack_hash,
        findings=findings,
        evidences=evidences,
        corpus_sha256=corpus_sha,
        index_sha256=index_sha,
        mcp_enabled=mcp_enabled,
        use_deepseek=use_deepseek,
        max_verification_tool_calls=max_verification_tool_calls,
        max_step_retries=max_step_retries,
        generate_report=generate_report,
    )

    # 幂等复用：同 run + 同 hash + 成功状态（needs_human/failed 不伪装复用）
    existing = db.scalar(
        select(ReviewSupervisorRun)
        .where(
            ReviewSupervisorRun.review_run_id == run.id,
            ReviewSupervisorRun.input_state_hash == state_hash,
            ReviewSupervisorRun.workspace_id == workspace_id,
            ReviewSupervisorRun.owner_user_id == owner_user_id,
            ReviewSupervisorRun.status.in_(COMPLETED_STATUSES),
        )
        .order_by(ReviewSupervisorRun.id.desc())
    )
    if existing is not None:
        return _build_result(db, existing, reused=True), True

    supervisor = ReviewSupervisorRun(
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        review_run_id=run.id,
        status="planning",
        input_state_hash=state_hash,
        graph_version=GRAPH_VERSION,
        quality_gate_version=QUALITY_GATE_VERSION,
        current_step=None,
        max_step_retries=max(0, min(2, max_step_retries)),
        retry_count=0,
        started_at=utcnow(),
    )
    db.add(supervisor)
    db.commit()
    db.refresh(supervisor)

    t0 = time.perf_counter()
    try:
        _execute_supervisor(
            db, supervisor, run, findings, evidences,
            use_deepseek=use_deepseek,
            max_verification_tool_calls=max_verification_tool_calls,
            generate_report=generate_report,
            actor_user_id=caller_user_id,
        )
    except SupervisorServiceError:
        raise
    except Exception:
        supervisor.status = "failed"
        supervisor.error_code = "SUPERVISOR_INTERNAL_ERROR"
        supervisor.error_message = "Supervisor 执行失败"
        supervisor.completed_at = utcnow()
        db.commit()
        raise SupervisorServiceError(
            "SUPERVISOR_INTERNAL_ERROR", "Supervisor 执行失败", status_code=500
        )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    supervisor.completed_at = utcnow()
    db.commit()
    result = _build_result(db, supervisor, reused=False, latency_ms=latency_ms)
    return result, False


# ── 状态机执行 ─────────────────────────────────────────────────────


def _execute_supervisor(
    db: Session,
    supervisor: ReviewSupervisorRun,
    run: ReviewRun,
    findings: list[ReviewFinding],
    evidences: list[Evidence],
    *,
    use_deepseek: bool,
    max_verification_tool_calls: int,
    generate_report: bool,
    actor_user_id: int,
) -> None:
    """确定性顺序执行四节点；局部重试仅针对失败节点。"""
    supervisor.status = "running"
    db.commit()

    # 1. Extraction readiness
    supervisor.current_step = "extraction"
    extraction_ok, clarification = _run_extraction_readiness(
        db, supervisor, run, findings, evidences, actor_user_id)
    if not extraction_ok:
        supervisor.status = "needs_human"
        supervisor.current_step = "extraction"
        supervisor.clarification_json = json.dumps(clarification, ensure_ascii=False)
        supervisor.completed_at = utcnow()
        db.commit()
        return

    # 2. Verification（复用 run_verification；MCP 暂时故障只重试本节点）
    # 每次尝试都记录 Step；重试的 Step 通过 retry_of_id 指向首次尝试，构成可追溯链。
    verification_run_id = None
    verification_retries = 0
    retry_chain_head_id: int | None = None
    while True:
        try:
            v_result, _ = run_verification(
                db, workspace_id=run.workspace_id, owner_user_id=run.owner_user_id,
                review_run_id=run.id, use_deepseek=use_deepseek,
                max_tool_calls=max_verification_tool_calls,
                actor_user_id=actor_user_id,
            )
            verification_run_id = v_result["verification_run_id"]
            supervisor.verification_run_id = verification_run_id
            # MCP 永久故障：verification 以 completed_with_warnings 返回且
            # mcp_context 存在未解决错误 → 不得继续，进入 needs_human
            if _verification_mcp_unresolved(v_result):
                _write_step(db, supervisor, run, "verification", "verification",
                            attempt=verification_retries + 1,
                            retry_of_id=retry_chain_head_id, status="failed",
                            output={"verification_run_id": verification_run_id},
                            error_code="VERIFICATION_MCP_FAILED",
                            error_message="MCP 核验上下文不完整", reused=False)
                supervisor.status = "needs_human"
                supervisor.current_step = "verification"
                supervisor.error_code = "VERIFICATION_MCP_FAILED"
                supervisor.error_message = "MCP 服务不可用，请检查后重试"
                supervisor.completed_at = utcnow()
                db.commit()
                return
            _write_step(db, supervisor, run, "verification", "verification",
                        attempt=verification_retries + 1,
                        retry_of_id=retry_chain_head_id,
                        status="success", output={"verification_run_id": verification_run_id},
                        reused=False)
            break
        except Exception:
            if verification_retries >= supervisor.max_step_retries:
                _write_step(db, supervisor, run, "verification", "verification",
                            attempt=verification_retries + 1,
                            retry_of_id=retry_chain_head_id, status="failed",
                            error_code="VERIFICATION_FAILED",
                            error_message="Verification 节点多次失败，已用尽重试次数",
                            reused=False)
                supervisor.status = "needs_human"
                supervisor.current_step = "verification"
                supervisor.error_code = "VERIFICATION_FAILED"
                supervisor.error_message = "Verification 多次失败，请检查 MCP 服务后重试"
                supervisor.completed_at = utcnow()
                db.commit()
                return
            verification_retries += 1
            supervisor.retry_count += 1
            db.commit()
            failed_step = _write_step(
                db, supervisor, run, "verification", "verification",
                attempt=verification_retries, retry_of_id=retry_chain_head_id,
                status="failed", error_code="VERIFICATION_RETRYABLE_FAILURE",
                error_message="Verification 节点执行失败，将自动重试", reused=False)
            if retry_chain_head_id is None:
                retry_chain_head_id = failed_step.id

    supervisor.verification_run_id = verification_run_id
    supervisor.current_step = "quality_review"
    db.commit()

    # 3. Quality Review（确定性质量门）
    gate = _run_quality_gate(db, supervisor, run, findings, evidences, actor_user_id)
    supervisor.quality_gate_json = json.dumps(gate, ensure_ascii=False)
    db.commit()

    if gate["status"] != "passed":
        supervisor.status = "needs_human"
        supervisor.current_step = "quality_review"
        supervisor.error_code = gate["errors"][0] if gate["errors"] else GATE_PERMANENT
        supervisor.error_message = "质量门未通过，请检查后重试"
        # 结构化的 clarification：只包含安全消息（Finding 编号/错误码），不含内容或路径
        supervisor.clarification_json = json.dumps({
            "code": "QUALITY_GATE_BLOCKED",
            "message": "质量门未通过，请检查后重试",
            "issues": [
                {"check_code": c["check_code"], "finding_id": c["finding_id"],
                 "evidence_id": c["evidence_id"], "safe_message": c["safe_message"]}
                for c in gate["checks"] if c["status"] == "fail"
            ],
        }, ensure_ascii=False)
        supervisor.completed_at = utcnow()
        db.commit()
        return

    # 4. Reporting
    if not generate_report:
        supervisor.status = "ready_to_report"
        supervisor.current_step = "reporting"
        supervisor.completed_at = utcnow()
        db.commit()
        return

    try:
        report, reused = generate_review_report(
            db, run=run, workspace_id=run.workspace_id, owner_user_id=run.owner_user_id)
        supervisor.report_id = report.id
        _write_step(db, supervisor, run, "reporting", "reporting",
                    attempt=1, status="success",
                    output={"report_id": report.id, "reused": reused}, reused=reused)
    except ReviewReportError:
        # 不把内部异常消息透传出去（可能包含路径等细节），统一固定文案
        _write_step(db, supervisor, run, "reporting", "reporting",
                    attempt=1, status="failed",
                    error_code="REPORTING_FAILED",
                    error_message="报告生成失败，请检查后重试", reused=False)
        supervisor.status = "needs_human"
        supervisor.current_step = "reporting"
        supervisor.error_code = "REPORTING_FAILED"
        supervisor.error_message = "报告生成失败，请检查后重试"
        supervisor.completed_at = utcnow()
        db.commit()
        return

    supervisor.status = "completed"
    supervisor.current_step = "reporting"
    supervisor.completed_at = utcnow()
    db.commit()


# ── Extraction readiness ───────────────────────────────────────────


def _run_extraction_readiness(
    db: Session,
    supervisor: ReviewSupervisorRun,
    run: ReviewRun,
    findings: list[ReviewFinding],
    evidences: list[Evidence],
    actor_user_id: int,
) -> tuple[bool, dict[str, Any]]:
    """复用现有材料/Profile/Evidence/规则快照服务检查就绪性。

    信息不足时生成结构化 clarification 并进入 needs_human，不编造字段。
    """
    from app.services.review_rule_service import load_rule_pack_from_snapshot

    issues: list[str] = []
    try:
        load_rule_pack_from_snapshot(run.rule_snapshot_json, run.rule_pack_hash)
    except RuleLoadError:
        issues.append("规则快照不可用")
    if not run.review_brief_snapshot_json:
        issues.append("Brief 快照缺失")

    # 五类必要角色：必须恰好一个文件满足全部条件——
    # user_confirmed_role 为必要角色、FileProfile 存在且 ready、
    # confirmed_role 与 user_confirmed_role 一致、File 属于当前 owner/workspace。
    # 缺文件、重复文件、Profile 未就绪或不一致都不得冒充完成。
    from app.models.file_profile import FileProfile
    from app.services.engineering_review_pipeline_service import REQUIRED_ROLES

    ws_files = db.scalars(
        select(WorkspaceFile).where(WorkspaceFile.workspace_id == run.workspace_id)
    ).all()
    file_ids = [wf.file_id for wf in ws_files]
    files_map: dict[int, Any] = {}
    if file_ids:
        files_map = {
            f_obj.id: f_obj
            for f_obj in db.scalars(select(File).where(File.id.in_(file_ids))).all()
        }
    profiles_by_file: dict[int, list[Any]] = {}
    if file_ids:
        for p in db.scalars(
            select(FileProfile).where(
                FileProfile.workspace_id == run.workspace_id,
                FileProfile.file_id.in_(file_ids),
            )
        ).all():
            profiles_by_file.setdefault(p.file_id, []).append(p)

    for role in sorted(REQUIRED_ROLES):
        role_files = [wf for wf in ws_files if wf.user_confirmed_role == role]
        if not role_files:
            issues.append(f"缺少必要角色 {role}")
            continue
        if len(role_files) > 1:
            issues.append(f"角色 {role} 存在重复文件记录")
            continue
        wf = role_files[0]
        f_obj = files_map.get(wf.file_id)
        if f_obj is None or f_obj.owner_user_id != actor_user_id:
            issues.append(f"角色 {role} 的文件归属异常")
            continue
        ps = profiles_by_file.get(wf.file_id) or []
        if not ps:
            issues.append(f"角色 {role} 缺少 Profile")
            continue
        ready = [p for p in ps if p.status == "ready"]
        if not ready:
            issues.append(f"角色 {role} 的 Profile 未就绪")
            continue
        if any(p.confirmed_role != role for p in ready):
            issues.append(f"角色 {role} 的 Profile 角色确认不一致")
            continue

    # Evidence 归属与 locator 有效性
    for ev in evidences:
        if ev.workspace_id != run.workspace_id or ev.owner_user_id != actor_user_id:
            issues.append(f"Evidence {ev.id} 归属异常")
        if ev.locator_type not in ("pdf_page", "spreadsheet_cell", "text_chunk"):
            issues.append(f"Evidence {ev.id} locator 类型无效")
        if ev.locator_type == "spreadsheet_cell" and (not ev.sheet_name or not ev.cell_range):
            issues.append(f"Evidence {ev.id} 表格定位不完整")

    _write_step(db, supervisor, run, "extraction", "extraction",
                attempt=1, status="success" if not issues else "failed",
                output={"ready": not issues, "issues": issues[:5]}, reused=False)

    if issues:
        clarification = {
            "code": "EXTRACTION_INFORMATION_MISSING",
            "issues": issues[:10],
            "message": "材料或快照信息不足，需要补充后再继续",
        }
        return False, clarification
    return True, {}


# ── Quality Gate（纯确定性）───────────────────────────────────────


def _run_quality_gate(
    db: Session,
    supervisor: ReviewSupervisorRun,
    run: ReviewRun,
    findings: list[ReviewFinding],
    evidences: list[Evidence],
    actor_user_id: int,
) -> dict[str, Any]:
    """确定性质量门：验证 Finding 证据/规则/数字来源。不调用 LLM。"""
    evidence_by_id = {e.id: e for e in evidences}
    ws_file_ids = {
        wf.file_id for wf in db.scalars(
            select(WorkspaceFile).where(WorkspaceFile.workspace_id == run.workspace_id)
        ).all()
    }

    # 从 Run 不可变快照解析规则
    try:
        pack = load_rule_pack_from_snapshot(run.rule_snapshot_json, run.rule_pack_hash)
        rule_by_id = {r.rule_id: r for r in pack.rules}
    except RuleLoadError:
        rule_by_id = {}

    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    reportable: list[int] = []
    need_more_info: list[int] = []
    warnings: list[str] = []
    related_file_ids: list[int] = []

    # 当前 Workspace Corpus 定位索引（复用检索服务，懒构建一次）；
    # 构建失败返回 None → 所有证据保守判定 STALE（无法核对当前语料）。
    corpus_locator_index = None

    def _stale_reason(ev: Evidence) -> str | None:
        """Evidence 在当前 Corpus 中精确定位；返回 None 表示未过期，否则返回安全原因。"""
        nonlocal corpus_locator_index
        if corpus_locator_index is None:
            try:
                chunks, _warnings = build_workspace_corpus(
                    db, run.workspace_id, run.owner_user_id)
                index: dict[tuple, list[Any]] = {}
                for c in chunks:
                    if c.locator_type == "pdf_page":
                        key = (c.file_id, "pdf_page", c.page_number)
                    elif c.locator_type == "spreadsheet_cell":
                        key = (c.file_id, "spreadsheet_cell", c.sheet_name, c.cell_range)
                    elif c.locator_type == "text_chunk":
                        key = (c.file_id, "text_chunk", c.text_chunk_index)
                    else:
                        continue
                    index.setdefault(key, []).append(c)
                corpus_locator_index = index
            except Exception:
                corpus_locator_index = None
        if corpus_locator_index is None:
            return "无法核对当前语料，视为过期"

        if ev.locator_type == "pdf_page":
            key = (ev.file_id, "pdf_page", ev.page_number)
        elif ev.locator_type == "spreadsheet_cell":
            key = (ev.file_id, "spreadsheet_cell", ev.sheet_name, ev.cell_range)
        elif ev.locator_type == "text_chunk":
            key = (ev.file_id, "text_chunk", ev.chunk_id)
        else:
            return "定位类型无效"
        matches = corpus_locator_index.get(key) or []
        if not matches:
            return "定位在当前语料中不存在"
        if len(matches) > 1:
            return "定位在当前语料中不再唯一"
        if matches[0].content_hash != ev.content_hash:
            return "当前内容哈希与证据不一致"
        return None

    for f in findings:
        if f.status in ("rejected", "resolved"):
            continue  # 按现有产品语义跳过
        ev_ids = _parse_json_list(f.evidence_ids_json)
        safe_msg = f"Finding {f.id} ({f.issue_code})"

        # rule_id/version 与快照一致
        if f.rule_id not in rule_by_id:
            checks.append(_gate_check(GATE_RULE_NOT_FOUND, f.id, None,
                                      retryable=False, msg=f"{safe_msg} 规则不存在"))
            errors.append(GATE_RULE_NOT_FOUND)
            continue
        rule = rule_by_id[f.rule_id]
        if f.rule_version != rule.version:
            checks.append(_gate_check(GATE_RULE_VERSION_MISMATCH, f.id, None,
                                      retryable=False, msg=f"{safe_msg} 规则版本不符"))
            errors.append(GATE_RULE_VERSION_MISMATCH)
            continue

        # 至少一个正式 evidence_id
        if not ev_ids:
            checks.append(_gate_check(GATE_EVIDENCE_MISSING, f.id, None,
                                      retryable=False, msg=f"{safe_msg} 缺少正式证据"))
            errors.append(GATE_EVIDENCE_MISSING)
            continue

        valid_evidence = True
        for eid in ev_ids:
            ev = evidence_by_id.get(eid)
            if ev is None:
                checks.append(_gate_check(GATE_EVIDENCE_MISSING, f.id, eid,
                                          retryable=False, msg=f"{safe_msg} 证据 {eid} 不存在"))
                errors.append(GATE_EVIDENCE_MISSING)
                valid_evidence = False
                continue
            # Evidence 属于当前 review_run/workspace/owner
            if (ev.review_run_id != run.id or ev.workspace_id != run.workspace_id
                    or ev.owner_user_id != actor_user_id):
                checks.append(_gate_check(GATE_EVIDENCE_INVALID, f.id, eid,
                                          retryable=False, msg=f"{safe_msg} 证据 {eid} 归属异常"))
                errors.append(GATE_EVIDENCE_INVALID)
                valid_evidence = False
                continue
            # Evidence 引用的 File 仍属于当前 Workspace
            if ev.file_id not in ws_file_ids:
                checks.append(_gate_check(GATE_EVIDENCE_INVALID, f.id, eid,
                                          retryable=False, msg=f"{safe_msg} 证据 {eid} 文件不在工作区"))
                errors.append(GATE_EVIDENCE_INVALID)
                valid_evidence = False
                continue
            # locator 字段有效性
            if ev.locator_type == "pdf_page" and (not ev.page_number or ev.page_number < 1):
                checks.append(_gate_check(GATE_EVIDENCE_INVALID, f.id, eid,
                                          retryable=True, retry_step="extraction",
                                          msg=f"{safe_msg} 证据 {eid} 页码无效"))
                errors.append(GATE_EVIDENCE_INVALID)
                valid_evidence = False
                continue
            # EVIDENCE_STALE：与当前 Corpus 精确定位并核对内容哈希
            stale = _stale_reason(ev)
            if stale is not None:
                checks.append(_gate_check(GATE_EVIDENCE_STALE, f.id, eid,
                                          retryable=False,
                                          msg=f"{safe_msg} 证据 {eid} {stale}"))
                errors.append(GATE_EVIDENCE_STALE)
                valid_evidence = False
                continue
            # 只有完全有效的 Evidence 才计入 related_file_ids
            related_file_ids.append(ev.file_id)

        if not valid_evidence:
            need_more_info.append(f.id)
            continue

        # 规则声明了必需的结构化输入，但 ReviewRun 没有输入快照 → 阻断
        if rule.inputs and not run.input_snapshot_hash:
            checks.append(_gate_check(GATE_RULE_INPUT_MISSING, f.id, ev_ids[0],
                                      retryable=False,
                                      msg=f"{safe_msg} 规则所需结构化输入缺失"))
            errors.append(GATE_RULE_INPUT_MISSING)
            need_more_info.append(f.id)
            continue

        # 数字结论来源：规则类型为 numeric_threshold 且无可靠计算来源 → 阻断
        if rule.type == "numeric_threshold" and not _has_numeric_provenance(f, ev_ids):
            checks.append(_gate_check(GATE_NUMERIC_PROVENANCE_MISSING, f.id, ev_ids[0],
                                      retryable=False,
                                      msg=f"{safe_msg} 数字结论缺少可靠计算来源"))
            errors.append(GATE_NUMERIC_PROVENANCE_MISSING)
            need_more_info.append(f.id)
            continue

        checks.append(_gate_check("OK", f.id, ev_ids[0], retryable=False,
                                  msg=f"{safe_msg} 证据与规则校验通过"))
        reportable.append(f.id)

    gate_status = "passed" if not errors else "failed"
    # Quality Review 必须独立记录 Step，不能只藏在 SupervisorRun JSON 中；
    # gate 结果（含未通过原因）作为该 Step 的输出供轨迹展示。
    _write_step(db, supervisor, run, "quality_review", "quality_review",
                attempt=1, status="success",
                output={"gate_status": gate_status,
                        "reportable_finding_ids": reportable,
                        "need_more_information_finding_ids": need_more_info,
                        "errors": errors,
                        "related_file_ids": sorted(set(related_file_ids))},
                reused=False)
    # 顶层 retryable 由失败检查项的真实 retryable 语义计算；
    # 永久错误（stale/invalid/缺失/来源不足）不得显示为可自动重试。
    gate_retryable = any(
        c["retryable"] for c in checks if c["status"] == "fail"
    )
    return {
        "gate_version": QUALITY_GATE_VERSION,
        "status": gate_status,
        "checks": checks,
        "reportable_finding_ids": reportable,
        "need_more_information_finding_ids": need_more_info,
        "retryable": gate_retryable,
        "retry_step_id": None,
        "related_file_ids": sorted(set(related_file_ids)),
        "errors": errors,
        "warnings": warnings,
    }


def _has_numeric_provenance(finding: ReviewFinding, ev_ids: list[int]) -> bool:
    """数字结论必须有可靠计算来源：source_step_id=engine:<rule_id>。

    不靠正则猜数字、不因“文本中出现数字”或“有正式证据”放行；
    只认可确定性 Review Engine 产生的来源（engine:<rule_id>）。
    """
    return bool(finding.source_step_id and finding.source_step_id.startswith("engine:"))


def _gate_check(code: str, finding_id: int, evidence_id: int | None, *,
                retryable: bool, msg: str, retry_step: str | None = None) -> dict[str, Any]:
    return {
        "check_code": code, "status": "fail" if code != "OK" else "pass",
        "finding_id": finding_id, "evidence_id": evidence_id,
        "safe_message": msg, "retryable": retryable, "retry_step_id": retry_step,
    }


# ── 步骤轨迹 ───────────────────────────────────────────────────────


def _verification_mcp_unresolved(v_result: dict[str, Any]) -> bool:
    """Verification 结果中 MCP 是否存在未解决错误（mcp_context.errors 非空）。"""
    if v_result.get("status") != "completed_with_warnings":
        return False
    plan = v_result.get("plan") or {}
    ctx = plan.get("mcp_context")
    if not isinstance(ctx, dict):
        return False
    return bool(ctx.get("errors"))


def _write_step(
    db: Session,
    supervisor: ReviewSupervisorRun,
    run: ReviewRun,
    step_id: str,
    node_name: str,
    *,
    attempt: int = 1,
    retry_of_id: int | None = None,
    status: str = "success",
    input_data: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    reused: bool = False,
    error_code: str | None = None,
    error_message: str | None = None,
    latency_ms: int | None = None,
) -> ReviewSupervisorStep:
    step = ReviewSupervisorStep(
        supervisor_run_id=supervisor.id,
        workspace_id=run.workspace_id,
        owner_user_id=run.owner_user_id,
        review_run_id=run.id,
        step_id=step_id,
        node_name=node_name,
        attempt_number=attempt,
        retry_of_id=retry_of_id,
        status=status,
        input_json=json.dumps(input_data or {}, ensure_ascii=False)[:8000],
        output_json=json.dumps(output or {}, ensure_ascii=False)[:30000],
        reused=reused,
        error_code=error_code,
        error_message=error_message,
        latency_ms=latency_ms,
        completed_at=utcnow(),
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def _index_state(db: Session, workspace_id: int, owner_user_id: int) -> tuple[str, str]:
    try:
        info = get_index_status(db, workspace_id, owner_user_id)
        return info.corpus_sha256 or "", info.index_sha256 or ""
    except Exception:
        return "", ""


# ── 结果组装 ───────────────────────────────────────────────────────


def _build_result(
    db: Session,
    supervisor: ReviewSupervisorRun,
    *,
    reused: bool,
    latency_ms: int | None = None,
) -> dict[str, Any]:
    steps = list(db.scalars(
        select(ReviewSupervisorStep)
        .where(ReviewSupervisorStep.supervisor_run_id == supervisor.id)
        .order_by(ReviewSupervisorStep.id.asc())
    ).all())
    gate = {}
    if supervisor.quality_gate_json:
        try:
            gate = json.loads(supervisor.quality_gate_json)
        except json.JSONDecodeError:
            gate = {}
    clarification = {}
    if supervisor.clarification_json:
        try:
            clarification = json.loads(supervisor.clarification_json)
        except json.JSONDecodeError:
            clarification = {}
    return {
        "supervisor_run_id": supervisor.id,
        "status": supervisor.status,
        "reused": reused,
        "workspace_id": supervisor.workspace_id,
        "owner_user_id": supervisor.owner_user_id,
        "review_run_id": supervisor.review_run_id,
        "input_state_hash": supervisor.input_state_hash,
        "graph_version": supervisor.graph_version,
        "quality_gate_version": supervisor.quality_gate_version,
        "current_step": supervisor.current_step,
        "max_step_retries": supervisor.max_step_retries,
        "retry_count": supervisor.retry_count,
        "verification_run_id": supervisor.verification_run_id,
        "report_id": supervisor.report_id,
        "quality_gate": gate,
        "clarification": clarification,
        "error_code": supervisor.error_code,
        "error_message": supervisor.error_message,
        "steps": [
            {
                "id": s.id, "step_id": s.step_id, "node_name": s.node_name,
                "attempt_number": s.attempt_number, "retry_of_id": s.retry_of_id,
                "status": s.status, "reused": s.reused,
                "output": _safe_json(s.output_json),
                "error_code": s.error_code, "error_message": s.error_message,
                "latency_ms": s.latency_ms,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in steps
        ],
        "latency_ms": latency_ms,
        "created_at": supervisor.created_at.isoformat() if supervisor.created_at else None,
        "completed_at": supervisor.completed_at.isoformat() if supervisor.completed_at else None,
    }


def _safe_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def list_supervisor_runs(
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
        raise SupervisorServiceError(
            "SUPERVISOR_RUN_NOT_FOUND", "ReviewRun 不存在或无权访问", status_code=404
        )
    runs = list(db.scalars(
        select(ReviewSupervisorRun)
        .where(
            ReviewSupervisorRun.review_run_id == review_run_id,
            ReviewSupervisorRun.workspace_id == workspace_id,
            ReviewSupervisorRun.owner_user_id == owner_user_id,
        )
        .order_by(ReviewSupervisorRun.id.desc())
    ).all())
    return [_build_result(db, r, reused=False) for r in runs]


def get_supervisor_run(
    db: Session, workspace_id: int, owner_user_id: int,
    review_run_id: int, supervisor_run_id: int,
) -> dict[str, Any]:
    run = db.scalar(
        select(ReviewRun).where(
            ReviewRun.id == review_run_id,
            ReviewRun.workspace_id == workspace_id,
            ReviewRun.owner_user_id == owner_user_id,
        )
    )
    if run is None:
        raise SupervisorServiceError(
            "SUPERVISOR_RUN_NOT_FOUND", "ReviewRun 不存在或无权访问", status_code=404
        )
    supervisor = db.scalar(
        select(ReviewSupervisorRun).where(
            ReviewSupervisorRun.id == supervisor_run_id,
            ReviewSupervisorRun.review_run_id == review_run_id,
            ReviewSupervisorRun.workspace_id == workspace_id,
            ReviewSupervisorRun.owner_user_id == owner_user_id,
        )
    )
    if supervisor is None:
        raise SupervisorServiceError(
            "SUPERVISOR_RUN_NOT_FOUND", "SupervisorRun 不存在或无权访问", status_code=404
        )
    return _build_result(db, supervisor, reused=False)


def list_supervisor_steps(
    db: Session, workspace_id: int, owner_user_id: int,
    review_run_id: int, supervisor_run_id: int,
) -> list[dict[str, Any]]:
    get_supervisor_run(db, workspace_id, owner_user_id, review_run_id, supervisor_run_id)
    steps = list(db.scalars(
        select(ReviewSupervisorStep)
        .where(
            ReviewSupervisorStep.supervisor_run_id == supervisor_run_id,
            ReviewSupervisorStep.workspace_id == workspace_id,
            ReviewSupervisorStep.owner_user_id == owner_user_id,
        )
        .order_by(ReviewSupervisorStep.id.asc())
    ).all())
    return [
        {
            "id": s.id, "supervisor_run_id": s.supervisor_run_id,
            "step_id": s.step_id, "node_name": s.node_name,
            "attempt_number": s.attempt_number, "retry_of_id": s.retry_of_id,
            "status": s.status, "reused": s.reused,
            "output": _safe_json(s.output_json),
            "error_code": s.error_code, "error_message": s.error_message,
            "latency_ms": s.latency_ms,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        }
        for s in steps
    ]
