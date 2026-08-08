from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timeutils import utcnow
from app.db.base import Base


class ReviewReport(Base):
    __tablename__ = "review_reports"
    __table_args__ = (
        UniqueConstraint(
            "review_run_id", "version", name="uq_review_reports_run_version"
        ),
        UniqueConstraint(
            "review_run_id",
            "review_state_hash",
            name="uq_review_reports_run_state_hash",
        ),
        CheckConstraint(
            "status IN ('ready', 'ready_with_warnings')",
            name="ck_review_reports_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    review_run_id: Mapped[int] = mapped_column(
        ForeignKey("review_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    review_state_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    review_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    quality_gate_json: Mapped[str] = mapped_column(Text, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    finding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    high_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    medium_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    modified_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generator_name: Mapped[str] = mapped_column(String(120), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    review_run = relationship("ReviewRun")
    workspace = relationship("Workspace")
    owner = relationship("User")

