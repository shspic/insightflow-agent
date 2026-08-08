"""工程 Verification Agent 运行记录（阶段 4C-2）。

与旧 general ToolCall/Task 完全解耦；同一 ReviewRun 同一 input_state_hash
的成功运行幂等复用，不允许跨 workspace/owner 复用。
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


class ReviewVerificationRun(Base):
    __tablename__ = "review_verification_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planning', 'running', 'completed', "
            "'completed_with_warnings', 'failed')",
            name="ck_review_verification_runs_status",
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
    review_run_id: Mapped[int] = mapped_column(
        ForeignKey("review_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="planning", index=True)
    input_state_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    planner_type: Mapped[str] = mapped_column(String(50), nullable=False, default="deterministic")
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    token_usage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    tool_calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    workspace = relationship("Workspace")
    owner = relationship("User")
    review_run = relationship("ReviewRun")
