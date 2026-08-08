"""工程 Verification Agent 工具调用记录（阶段 4C-2）。

只追加，不提供修改或删除 API；error_message 必须安全化；
workspace 永久删除时由数据库级联清除。
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


class ReviewToolCall(Base):
    __tablename__ = "review_tool_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_review_tool_calls_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    verification_run_id: Mapped[int] = mapped_column(
        ForeignKey("review_verification_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    review_run_id: Mapped[int] = mapped_column(
        ForeignKey("review_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    review_finding_id: Mapped[int | None] = mapped_column(
        ForeignKey("review_findings.id", ondelete="SET NULL"),
        nullable=True,
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
    node_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retry_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("review_tool_calls.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="running", index=True)
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    index_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    corpus_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_revision: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    verification_run = relationship("ReviewVerificationRun")
    review_run = relationship("ReviewRun")
    workspace = relationship("Workspace")
    owner = relationship("User")
