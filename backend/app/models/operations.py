from datetime import datetime
from app.core.timeutils import utcnow

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CleanupRun(Base):
    __tablename__ = "cleanup_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    cleanup_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scanned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    released_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dry_run: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    execution_source: Mapped[str] = mapped_column(String(50), nullable=False)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkerStatus(Base):
    __tablename__ = "worker_statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    worker_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    current_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
