from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"
    __table_args__ = (
        UniqueConstraint("scope_type", "scope_hash", name="uq_auth_rate_limits_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    scope_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
