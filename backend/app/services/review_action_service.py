"""审查操作服务 — ReviewRun 生命周期、Evidence 创建、Finding 持久化和人工操作追加。"""

from __future__ import annotations

import json
from datetime import datetime
from app.core.timeutils import utcnow

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.models.file import File
from app.models.review_action import ReviewAction
from app.models.review_brief import ReviewBrief
from app.models.review_finding import ReviewFinding
from app.models.review_run import ReviewRun
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.schemas.review import (
    EvidenceCreate,
    ReviewRulePack,
    StructuredReviewInput,
)


class ReviewServiceError(Exception):
    """审查服务操作错误。"""


# ── ReviewRun ────────────────────────────────────────────────────


def create_review_run(
    db: Session,
    *,
    workspace_id: int,
    owner_user_id: int,
    rule_pack: ReviewRulePack,
    rule_snapshot: str,
    rule_pack_hash: str,
    review_brief_id: int,
) -> ReviewRun:
    """创建一次审查运行。必须绑定 confirmed ReviewBrief。"""
    workspace = db.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.owner_user_id == owner_user_id,
            Workspace.deleted_at.is_(None),
        )
    )
    if workspace is None:
        raise ReviewServiceError("工作区不存在或无权访问")
    if workspace.workspace_type != "engineering":
        raise ReviewServiceError("仅 engineering 工作区可以运行工程审查")
    if workspace.review_template_key != "engineering_bid_review_v1":
        raise ReviewServiceError("工作区未设置工程审查模板")

    # 校验 ReviewBrief
    brief = db.scalar(
        select(ReviewBrief).where(
            ReviewBrief.id == review_brief_id,
            ReviewBrief.workspace_id == workspace_id,
            ReviewBrief.owner_user_id == owner_user_id,
        )
    )
    if brief is None:
        raise ReviewServiceError("ReviewBrief 不存在或不属于当前工作区/用户")
    if brief.status != "confirmed":
        raise ReviewServiceError(
            f"ReviewBrief 状态为 {brief.status}，只有 confirmed 可以创建新运行"
        )

    # 生成 Brief 快照
    brief_snapshot = json.dumps(
        {
            "id": brief.id,
            "version": brief.version,
            "raw_requirements": brief.raw_requirements,
            "interpreted_json": brief.interpreted_json,
            "content_hash": brief.content_hash,
            "status": brief.status,
            "interpreter_type": brief.interpreter_type,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    brief_hash = _compute_sha256(brief_snapshot)

    run = ReviewRun(
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        review_template_key="engineering_bid_review_v1",
        review_brief_id=brief.id,
        review_brief_version=brief.version,
        review_brief_hash=brief_hash,
        review_brief_snapshot_json=brief_snapshot,
        status="pending",
        rule_pack_id=rule_pack.pack_id,
        rule_pack_version=rule_pack.version,
        rule_pack_hash=rule_pack_hash,
        rule_snapshot_json=rule_snapshot,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def start_review_run(db: Session, run: ReviewRun) -> ReviewRun:
    """将 ReviewRun 标记为 running。"""
    if run.status != "pending":
        raise ReviewServiceError(f"ReviewRun {run.id} 状态为 {run.status}，无法启动")
    run.status = "running"
    run.started_at = utcnow()
    db.commit()
    db.refresh(run)
    return run


def complete_review_run(db: Session, run: ReviewRun) -> ReviewRun:
    """将 ReviewRun 标记为 completed。"""
    run.status = "completed"
    run.completed_at = utcnow()
    db.commit()
    db.refresh(run)
    return run


def fail_review_run(
    db: Session,
    run: ReviewRun,
    error_code: str,
    error_message: str,
) -> ReviewRun:
    """将 ReviewRun 标记为 failed。"""
    run.status = "failed"
    run.error_code = error_code
    run.error_message = error_message
    run.completed_at = utcnow()
    db.commit()
    db.refresh(run)
    return run


# ── Evidence ────────────────────────────────────────────────────


def create_evidence(
    db: Session,
    *,
    review_run_id: int,
    workspace_id: int,
    owner_user_id: int,
    evidence: EvidenceCreate,
    commit: bool = True,
) -> Evidence:
    """创建单条 Evidence。校验 ReviewRun、Workspace、File 真实归属。

    commit=False 时只 flush 不提交，由调用方把 Evidence 与其他写入
    放进同一个事务（阶段 4C-3 候选采纳闭环使用）；默认保持旧行为。
    """
    from app.services.evidence_provenance import compute_file_sha256_safe
    from app.services.review_engine_service import _compute_evidence_hash

    # 1. 校验 ReviewRun
    run = db.scalar(
        select(ReviewRun).where(
            ReviewRun.id == review_run_id,
            ReviewRun.workspace_id == workspace_id,
            ReviewRun.owner_user_id == owner_user_id,
        )
    )
    if run is None:
        raise ReviewServiceError("ReviewRun 不存在或归属不匹配")

    # 2. 校验 Workspace 为 engineering
    workspace = db.scalar(select(Workspace).where(Workspace.id == workspace_id))
    if workspace is None or workspace.workspace_type != "engineering":
        raise ReviewServiceError("仅 engineering 工作区可以创建 Evidence")

    # 3. 校验 File 真实存在且属于该 workspace/owner
    file_record = db.scalar(
        select(File).where(File.id == evidence.file_id)
    )
    if file_record is None:
        raise ReviewServiceError(f"文件 {evidence.file_id} 不存在")
    if file_record.owner_user_id != owner_user_id:
        raise ReviewServiceError("文件不属于当前用户")

    # 4. 校验 WorkspaceFile 关联
    wf = db.scalar(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == workspace_id,
            WorkspaceFile.file_id == evidence.file_id,
        )
    )
    if wf is None:
        raise ReviewServiceError(f"文件 {evidence.file_id} 未关联到工作区 {workspace_id}")

    # 计算哈希并持久化
    # content_hash：证据记录规范哈希（保持既有公式不变）；
    # source_file_hash：来源文件字节 SHA-256，由服务端根据安全解析后的
    # 当前文件计算，禁止信任客户端传入。文件不可安全读取时保持 NULL，
    # 由 Quality Gate 按 EVIDENCE_PROVENANCE_MISSING 阻断。
    evidence_data = {
        "file_id": evidence.file_id,
        "locator_type": evidence.locator_type,
        "page_number": evidence.page_number,
        "sheet_name": evidence.sheet_name,
        "cell_range": evidence.cell_range,
        "chunk_id": evidence.chunk_id,
        "quote": evidence.quote,
    }
    content_hash = _compute_evidence_hash(evidence_data)
    source_file_hash = compute_file_sha256_safe(file_record.file_path)

    record = Evidence(
        review_run_id=review_run_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        file_id=evidence.file_id,
        locator_type=evidence.locator_type,
        page_number=evidence.page_number,
        sheet_name=evidence.sheet_name,
        cell_range=evidence.cell_range,
        chunk_id=evidence.chunk_id,
        quote=evidence.quote,
        content_hash=content_hash,
        provenance_type=evidence.provenance_type,
        source_file_hash=source_file_hash,
        source_chunk_id=evidence.source_chunk_id if evidence.provenance_type == "corpus_chunk" else None,
        source_chunk_hash=evidence.source_chunk_hash if evidence.provenance_type == "corpus_chunk" else None,
        parser_name=evidence.parser_name,
        parser_version=evidence.parser_version,
    )
    db.add(record)
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(record)
    return record


def get_evidence_by_ids(
    db: Session,
    evidence_ids: list[int],
    review_run_id: int,
    workspace_id: int,
    owner_user_id: int,
) -> list[Evidence]:
    """批量获取 Evidence，校验所有权。"""
    if not evidence_ids:
        return []
    records = list(
        db.scalars(
            select(Evidence).where(
                Evidence.id.in_(evidence_ids),
                Evidence.review_run_id == review_run_id,
                Evidence.workspace_id == workspace_id,
                Evidence.owner_user_id == owner_user_id,
            )
        ).all()
    )
    if len(records) != len(set(evidence_ids)):
        missing = set(evidence_ids) - {r.id for r in records}
        raise ReviewServiceError(f"Evidence ID 不存在或无权访问：{sorted(missing)}")
    return records


# ── Finding ──────────────────────────────────────────────────────


def create_review_finding(
    db: Session,
    *,
    review_run_id: int,
    workspace_id: int,
    owner_user_id: int,
    issue_code: str,
    title: str,
    category: str,
    severity: str,
    conclusion: str,
    suggestion: str,
    rule_id: str,
    rule_version: str,
    evidence_ids: list[int],
    source_step_id: str | None = None,
) -> ReviewFinding:
    """创建 ReviewFinding。校验 evidence_ids 全部存在且归属正确。"""
    if not evidence_ids:
        raise ReviewServiceError("Finding 必须至少关联一个 Evidence")

    # 校验证据
    get_evidence_by_ids(db, evidence_ids, review_run_id, workspace_id, owner_user_id)

    finding = ReviewFinding(
        review_run_id=review_run_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        issue_code=issue_code,
        title=title,
        category=category,
        severity=severity,
        conclusion=conclusion,
        suggestion=suggestion,
        rule_id=rule_id,
        rule_version=rule_version,
        evidence_ids_json=json.dumps(sorted(evidence_ids), ensure_ascii=False),
        status="pending_review",
        source_step_id=source_step_id,
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return finding


# ── 人工操作 ─────────────────────────────────────────────────────


def execute_review_action(
    db: Session,
    *,
    finding_id: int,
    owner_user_id: int,
    action_type: str,
    review_note: str | None = None,
    modified_conclusion: str | None = None,
    modified_suggestion: str | None = None,
) -> tuple[ReviewFinding, ReviewAction]:
    """对 Finding 执行人工操作。

    - confirm：确认发现
    - reject：驳回发现
    - modify：修改结论/建议（保留 before/after）
    - resolve：标记已解决

    操作在同一事务中追加 Action 并更新 Finding 状态。
    """
    finding = db.scalar(
        select(ReviewFinding).where(
            ReviewFinding.id == finding_id,
            ReviewFinding.owner_user_id == owner_user_id,
        )
    )
    if finding is None:
        raise ReviewServiceError("Finding 不存在或无权操作")

    valid_actions = {"confirm", "reject", "modify", "resolve"}
    if action_type not in valid_actions:
        raise ReviewServiceError(f"action_type 必须为 {sorted(valid_actions)} 之一")

    before = {
        "status": finding.status,
        "conclusion": finding.conclusion,
        "suggestion": finding.suggestion,
    }
    after = dict(before)

    if action_type == "confirm":
        finding.status = "confirmed"
        after["status"] = "confirmed"
    elif action_type == "reject":
        finding.status = "rejected"
        after["status"] = "rejected"
    elif action_type == "modify":
        if modified_conclusion is not None:
            finding.conclusion = modified_conclusion
            after["conclusion"] = modified_conclusion
        if modified_suggestion is not None:
            finding.suggestion = modified_suggestion
            after["suggestion"] = modified_suggestion
        finding.status = "modified"
        after["status"] = "modified"
    elif action_type == "resolve":
        finding.status = "resolved"
        after["status"] = "resolved"

    finding.reviewed_at = utcnow()
    finding.reviewed_by = owner_user_id
    finding.review_note = review_note

    action = ReviewAction(
        review_finding_id=finding.id,
        review_run_id=finding.review_run_id,
        workspace_id=finding.workspace_id,
        owner_user_id=owner_user_id,
        action_type=action_type,
        before_json=json.dumps(before, ensure_ascii=False),
        after_json=json.dumps(after, ensure_ascii=False),
        review_note=review_note,
    )
    db.add(action)
    db.commit()
    db.refresh(finding)
    db.refresh(action)
    return finding, action


def list_actions_for_finding(
    db: Session,
    finding_id: int,
    owner_user_id: int,
) -> list[ReviewAction]:
    """列出某个 Finding 的所有操作记录（按时间正序）。"""
    return list(
        db.scalars(
            select(ReviewAction)
            .where(
                ReviewAction.review_finding_id == finding_id,
                ReviewAction.owner_user_id == owner_user_id,
            )
            .order_by(ReviewAction.created_at.asc())
        ).all()
    )


# ── 内部辅助 ────────────────────────────────────────────────────


def _compute_sha256(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
