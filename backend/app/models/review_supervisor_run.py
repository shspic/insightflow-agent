"""工程 Supervisor 运行记录（阶段 5B）。

确定性状态机：Extraction → Verification → Quality Review → Reporting。
与 general 工作流完全解耦；同一 ReviewRun 同一 input_state_hash 的成功运行
幂等复用，不允许跨 workspace/owner 复用。
"""

from datetime import datetime

from sqlalchemy import (
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


class ReviewSupervisorRun(Base):
    __tablename__ = "review_supervisor_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planning', 'running', 'ready_to_report', 'completed', "
            "'completed_with_warnings', 'needs_human', 'failed')",
            name="ck_review_supervisor_runs_status",
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
    graph_version: Mapped[str] = mapped_column(String(50), nullable=False)
    quality_gate_version: Mapped[str] = mapped_column(String(50), nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(50), nullable=True)
    max_step_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verification_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("review_verification_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("review_reports.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    quality_gate_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    clarification_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    workspace = relationship("Workspace")
    owner = relationship("User")
    review_run = relationship("ReviewRun")
