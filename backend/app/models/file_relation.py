from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FileRelation(Base):
    __tablename__ = "file_relations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('suggested', 'confirmed', 'rejected', 'superseded')",
            name="ck_file_relations_status",
        ),
        CheckConstraint(
            "direction IN ('source_to_target', 'target_to_source', 'bidirectional')",
            name="ck_file_relations_direction",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_file_relations_confidence",
        ),
        CheckConstraint(
            "source_file_id != target_file_id",
            name="ck_file_relations_distinct_files",
        ),
        Index(
            "uq_file_relations_current_direction_type",
            "workspace_id",
            "source_file_id",
            "target_file_id",
            "relation_type",
            "direction",
            unique=True,
            sqlite_where=text("status != 'superseded'"),
            postgresql_where=text("status != 'superseded'"),
        ),
        Index(
            "ix_file_relations_workspace_status_confidence",
            "workspace_id",
            "status",
            "confidence",
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
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(40), nullable=False, default="bidirectional")
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_by: Mapped[str] = mapped_column(String(50), nullable=False, default="deterministic")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="suggested", index=True)
    user_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_relation_id: Mapped[int | None] = mapped_column(
        ForeignKey("file_relations.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    workspace = relationship("Workspace")
    owner = relationship("User")
    source_file = relationship("File", foreign_keys=[source_file_id])
    target_file = relationship("File", foreign_keys=[target_file_id])
    supersedes = relationship("FileRelation", remote_side=[id])
