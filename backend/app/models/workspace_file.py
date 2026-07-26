from datetime import datetime
from app.core.timeutils import utcnow

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WorkspaceFile(Base):
    __tablename__ = "workspace_files"
    __table_args__ = (
        UniqueConstraint("workspace_id", "file_id", name="uq_workspace_files_workspace_file"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    user_confirmed_role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    workspace = relationship("Workspace")
    file = relationship("File")
