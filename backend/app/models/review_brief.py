from datetime import datetime
from app.core.timeutils import utcnow

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

from app.db.base import Base


class ReviewBrief(Base):
    __tablename__ = "review_briefs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "version",
            name="uq_review_briefs_workspace_version",
        ),
        CheckConstraint(
            "status IN ('draft', 'needs_clarification', 'confirmed', 'superseded')",
            name="ck_review_briefs_status",
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
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_requirements: Mapped[str] = mapped_column(Text, nullable=False)
    interpreted_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft", index=True
    )
    interpreter_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="deterministic_fixture"
    )
    model_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    clarification_questions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    workspace = relationship("Workspace")
    owner = relationship("User", foreign_keys=[owner_user_id])
    confirmer = relationship("User", foreign_keys=[confirmed_by])
