from datetime import datetime, timedelta
from app.core.timeutils import utcnow

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.auth_rate_limit import AuthRateLimit
from app.services.security_service import scope_hash


class RateLimitExceededError(Exception):
    pass


def _utcnow() -> datetime:
    return utcnow()


def ensure_not_blocked(db: Session, scope_type: str, scope_value: str) -> None:
    digest = scope_hash(scope_type, scope_value)
    record = db.scalar(
        select(AuthRateLimit).where(
            AuthRateLimit.scope_type == scope_type,
            AuthRateLimit.scope_hash == digest,
        )
    )
    if record is not None and record.blocked_until is not None and record.blocked_until > _utcnow():
        raise RateLimitExceededError


def record_attempt(
    db: Session,
    scope_type: str,
    scope_value: str,
    limit: int,
) -> None:
    now = _utcnow()
    digest = scope_hash(scope_type, scope_value)
    record = db.scalar(
        select(AuthRateLimit).where(
            AuthRateLimit.scope_type == scope_type,
            AuthRateLimit.scope_hash == digest,
        )
    )
    window = timedelta(seconds=settings.auth_rate_window_seconds)
    if record is None:
        record = AuthRateLimit(
            scope_type=scope_type,
            scope_hash=digest,
            attempt_count=1,
            window_started_at=now,
            updated_at=now,
        )
        db.add(record)
    elif now - record.window_started_at >= window:
        record.attempt_count = 1
        record.window_started_at = now
        record.blocked_until = None
        record.updated_at = now
    else:
        record.attempt_count += 1
        record.updated_at = now

    if record.attempt_count >= limit:
        record.blocked_until = now + timedelta(seconds=settings.auth_block_seconds)


def clear_attempts(db: Session, scope_type: str, scope_value: str) -> None:
    digest = scope_hash(scope_type, scope_value)
    record = db.scalar(
        select(AuthRateLimit).where(
            AuthRateLimit.scope_type == scope_type,
            AuthRateLimit.scope_hash == digest,
        )
    )
    if record is not None:
        db.delete(record)
