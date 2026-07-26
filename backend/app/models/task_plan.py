from datetime import datetime
from app.core.timeutils import utcnow

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TaskPlan(Base):
    __tablename__ = "task_plans"
    __table_args__ = (
        UniqueConstraint("task_id", "version", name="uq_task_plans_task_version"),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'rejected', 'superseded')",
            name="ck_task_plans_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    assumptions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    steps_json: Mapped[str] = mapped_column(Text, nullable=False)
    selected_file_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_model_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(50), nullable=False, default="supervisor")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    task = relationship("Task")
