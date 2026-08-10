from datetime import datetime
from app.core.timeutils import utcnow

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_workspaces_status"),
        CheckConstraint(
            "workspace_type IN ('engineering', 'general')",
            name="ck_workspaces_workspace_type",
        ),
        CheckConstraint(
            "review_template_key IS NULL OR (workspace_type = 'engineering' AND review_template_key = 'engineering_bid_review_v1')",
            name="ck_workspaces_review_template_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="general", index=True
    )
    review_template_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    owner = relationship("User")
