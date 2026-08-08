"""ReviewBrief 服务 — 结构化意图解释的创建、确认与快照管理。"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.review_brief import ReviewBrief
from app.models.workspace import Workspace
from app.schemas.review import InterpretedIntent, ReviewBriefCreate


class BriefServiceError(Exception):
    """ReviewBrief 操作错误。"""


def create_review_brief(
    db: Session,
    *,
    workspace_id: int,
    owner_user_id: int,
    data: ReviewBriefCreate,
) -> ReviewBrief:
    """创建 ReviewBrief（draft 状态）。

    仅 engineering 工作区可以创建。版本自动递增。
    """
    workspace = db.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.owner_user_id == owner_user_id,
            Workspace.deleted_at.is_(None),
        )
    )
    if workspace is None:
        raise BriefServiceError("工作区不存在或无权访问")
    if workspace.workspace_type != "engineering":
        raise BriefServiceError("仅 engineering 工作区可以创建 ReviewBrief")

    # 校验 interpreted
    intent = data.interpreted

    # required 与 excluded 冲突检测
    required_set = set(intent.required_check_types)
    excluded_set = set(intent.excluded_check_types)
    conflicts = required_set & excluded_set
    if conflicts:
        raise BriefServiceError(
            f"required_check_types 与 excluded_check_types 冲突：{sorted(conflicts)}"
        )

    # 有追问时只能 draft 或 needs_clarification
    has_clarifications = bool(intent.clarification_questions)

    # 计算下一版本
    max_version = db.scalar(
        select(func.max(ReviewBrief.version)).where(
            ReviewBrief.workspace_id == workspace_id,
        )
    ) or 0
    next_version = max_version + 1

    interpreted_json = json.dumps(
        intent.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    content_hash = _compute_content_hash(data.raw_requirements, interpreted_json)

    brief = ReviewBrief(
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        version=next_version,
        raw_requirements=data.raw_requirements,
        interpreted_json=interpreted_json,
        status="needs_clarification" if has_clarifications else "draft",
        interpreter_type=data.interpreter_type,
        clarification_questions_json=(
            json.dumps(intent.clarification_questions, ensure_ascii=False)
            if has_clarifications
            else None
        ),
        content_hash=content_hash,
        model_provider=None,
        model_name=None,
        prompt_version=None,
    )
    db.add(brief)
    db.commit()
    db.refresh(brief)
    return brief


def confirm_review_brief(
    db: Session,
    *,
    brief_id: int,
    owner_user_id: int,
) -> ReviewBrief:
    """确认 ReviewBrief。有追问时拒绝确认。确认新版本时旧 confirmed 变为 superseded。"""
    brief = db.scalar(
        select(ReviewBrief).where(
            ReviewBrief.id == brief_id,
            ReviewBrief.owner_user_id == owner_user_id,
        )
    )
    if brief is None:
        raise BriefServiceError("ReviewBrief 不存在或无权访问")

    if brief.status == "confirmed":
        raise BriefServiceError("ReviewBrief 已确认，无需重复确认")
    if brief.status == "superseded":
        raise BriefServiceError("已废弃的 ReviewBrief 不能确认")

    # 检查是否有追问
    if brief.clarification_questions_json:
        questions = json.loads(brief.clarification_questions_json)
        if questions:
            raise BriefServiceError("存在未解决的澄清问题，不能确认")

    # 旧 confirmed 版本 → superseded
    old_confirmed = db.scalar(
        select(ReviewBrief).where(
            ReviewBrief.workspace_id == brief.workspace_id,
            ReviewBrief.status == "confirmed",
        )
    )
    if old_confirmed is not None:
        old_confirmed.status = "superseded"

    brief.status = "confirmed"
    brief.confirmed_at = func.now()
    brief.confirmed_by = owner_user_id
    db.commit()
    db.refresh(brief)
    return brief


def get_review_brief(
    db: Session,
    *,
    brief_id: int,
    owner_user_id: int,
) -> ReviewBrief | None:
    """获取指定 ReviewBrief。"""
    return db.scalar(
        select(ReviewBrief).where(
            ReviewBrief.id == brief_id,
            ReviewBrief.owner_user_id == owner_user_id,
        )
    )


def get_confirmed_brief(
    db: Session,
    *,
    workspace_id: int,
    owner_user_id: int,
) -> ReviewBrief | None:
    """获取工作区当前 confirmed 的 ReviewBrief。"""
    return db.scalar(
        select(ReviewBrief).where(
            ReviewBrief.workspace_id == workspace_id,
            ReviewBrief.owner_user_id == owner_user_id,
            ReviewBrief.status == "confirmed",
        )
    )


def _compute_content_hash(raw_requirements: str, interpreted_json: str) -> str:
    """计算 ReviewBrief 内容哈希。"""
    payload = json.dumps(
        {"raw": raw_requirements, "interpreted": interpreted_json},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
