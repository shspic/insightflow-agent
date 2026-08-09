from datetime import datetime
from app.core.timeutils import utcnow

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ReviewRun(Base):
    __tablename__ = "review_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_review_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
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
    review_template_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    rule_pack_id: Mapped[str] = mapped_column(String(200), nullable=False)
    rule_pack_version: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_pack_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    review_brief_id: Mapped[int | None] = mapped_column(
        ForeignKey("review_briefs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    review_brief_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_brief_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_brief_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    # input snapshot：pipeline 在真实字段抽取完成后自动生成规范 JSON 并计算哈希；
    # Quality Gate 复算校验，评测脚本禁止手工写入。
    input_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    retrieval_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    workspace = relationship("Workspace")
    owner = relationship("User")
    review_brief = relationship("ReviewBrief")
