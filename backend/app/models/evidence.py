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
        CheckConstraint(
            "provenance_type IS NULL OR provenance_type IN ('field_locator', 'corpus_chunk')",
            name="ck_evidences_provenance_type",
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
    # content_hash：证据记录规范哈希（file_id/locator/quote 元数据 JSON SHA-256），
    # 与 CorpusChunk.content_hash（来源文本块哈希）语义不同，不得直接比较。
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # 来源完整性字段：由服务端根据安全解析后的当前文件/Corpus 计算。
    # provenance_type：field_locator（确定性管道定位）或 corpus_chunk（检索候选采纳）。
    # 历史记录允许为空 → Quality Gate 判定 EVIDENCE_PROVENANCE_MISSING。
    provenance_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    source_file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_chunk_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_chunk_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parser_name: Mapped[str] = mapped_column(String(120), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    review_run = relationship("ReviewRun")
    workspace = relationship("Workspace")
    owner = relationship("User")
    file = relationship("File")
