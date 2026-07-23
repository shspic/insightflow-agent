from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.services.security_service import sanitized_json


def add_audit_log(
    db: Session,
    *,
    action: str,
    status: str,
    user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | int | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    record = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        status=status,
        details_json=sanitized_json(details),
        ip_address=ip_address,
    )
    db.add(record)
    return record
