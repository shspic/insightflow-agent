"""工程 Verification 候选证据人工决策记录（阶段 4C-3）。

只追加式审计：
- 同一 (review_tool_call_id, candidate_rank) 只允许一条最终决策（唯一约束）；
- 不提供更新和删除接口；
- candidate_snapshot_json 保存服务端重新校验后的候选快照，
  不保存磁盘绝对路径、API Key、Token、堆栈或原始模型输出；
- workspace 永久删除时由数据库级联清除；
- evidence_id 在 Evidence 被单独删除时 SET NULL，保留审计行。
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timeutils import utcnow
from app.db.base import Base


class ReviewCandidateDecision(Base):
    __tablename__ = "review_candidate_decisions"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('accept', 'reject')",
            name="ck_review_candidate_decisions_decision",
        ),
        UniqueConstraint(
            "review_tool_call_id",
            "candidate_rank",
            name="uq_review_candidate_decisions_call_rank",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    verification_run_id: Mapped[int] = mapped_column(
        ForeignKey("review_verification_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    review_tool_call_id: Mapped[int] = mapped_column(
        ForeignKey("review_tool_calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    review_finding_id: Mapped[int] = mapped_column(
        ForeignKey("review_findings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    review_run_id: Mapped[int] = mapped_column(
        ForeignKey("review_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_chunk_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    candidate_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidences.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    verification_run = relationship("ReviewVerificationRun")
    review_tool_call = relationship("ReviewToolCall")
    review_finding = relationship("ReviewFinding")
    review_run = relationship("ReviewRun")
    workspace = relationship("Workspace")
    owner = relationship("User")
    evidence = relationship("Evidence")
