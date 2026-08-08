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


class ReviewAction(Base):
    __tablename__ = "review_actions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('confirm', 'reject', 'modify', 'resolve')",
            name="ck_review_actions_action_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
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
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    review_finding = relationship("ReviewFinding")
    review_run = relationship("ReviewRun")
    workspace = relationship("Workspace")
    owner = relationship("User")
