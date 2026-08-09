"""工程 Supervisor 步骤轨迹（阶段 5B）。

只追加，不提供编辑/删除 API；workspace 永久删除时由数据库级联清除。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timeutils import utcnow
from app.db.base import Base

SUPERVISOR_NODE_NAMES = frozenset({
    "extraction", "verification", "quality_review", "reporting",
})


class ReviewSupervisorStep(Base):
    __tablename__ = "review_supervisor_steps"
    __table_args__ = (
        CheckConstraint(
            "node_name IN ('extraction', 'verification', 'quality_review', 'reporting')",
            name="ck_review_supervisor_steps_node",
        ),
        CheckConstraint(
            "status IN ('running', 'success', 'failed', 'skipped', 'needs_human')",
            name="ck_review_supervisor_steps_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    supervisor_run_id: Mapped[int] = mapped_column(
        ForeignKey("review_supervisor_runs.id", ondelete="CASCADE"),
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
    review_run_id: Mapped[int] = mapped_column(
        ForeignKey("review_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[str] = mapped_column(String(120), nullable=False)
    node_name: Mapped[str] = mapped_column(String(50), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retry_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("review_supervisor_steps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="running", index=True)
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    supervisor_run = relationship("ReviewSupervisorRun")
    workspace = relationship("Workspace")
    owner = relationship("User")
