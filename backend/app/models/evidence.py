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


class Evidence(Base):
    __tablename__ = "evidences"
    __table_args__ = (
        CheckConstraint(
            "locator_type IN ('pdf_page', 'spreadsheet_cell', 'text_chunk')",
            name="ck_evidences_locator_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
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
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    locator_type: Mapped[str] = mapped_column(String(50), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sheet_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cell_range: Mapped[str | None] = mapped_column(String(200), nullable=True)
    chunk_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote: Mapped[str] = mapped_column(String(2000), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(120), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    review_run = relationship("ReviewRun")
    workspace = relationship("Workspace")
    owner = relationship("User")
    file = relationship("File")
