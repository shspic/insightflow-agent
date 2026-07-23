import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.task_event import TaskEvent
from app.services.security_service import sanitize_details
from app.services.workspace_service import safe_public_text


SENSITIVE_EVENT_KEYS = {
    "file_path",
    "report_path",
    "storage_path",
    "absolute_path",
    "prompt",
    "raw_prompt",
    "document_content",
    "chunk_text",
}


def append_task_event(
    db: Session,
    *,
    task_id: int,
    event_type: str,
    message: str,
    status: str | None = None,
    progress_percent: int | None = None,
    step_id: int | None = None,
    agent_type: str | None = None,
    payload: dict[str, Any] | None = None,
) -> TaskEvent:
    if progress_percent is not None and not 0 <= progress_percent <= 100:
        raise ValueError("事件进度必须在 0 到 100 之间")
    sanitized_payload = _sanitize_event_value(payload) if payload is not None else None
    event = TaskEvent(
        task_id=task_id,
        event_type=event_type,
        event_version="1",
        step_id=step_id,
        agent_type=agent_type,
        status=status,
        progress_percent=progress_percent,
        message=safe_public_text(message) or "任务事件",
        payload_json=(
            json.dumps(sanitized_payload, ensure_ascii=False, default=str)
            if sanitized_payload is not None
            else None
        ),
    )
    db.add(event)
    db.flush()
    return event


def list_task_events(
    db: Session,
    *,
    task_id: int,
    after_id: int = 0,
    limit: int = 200,
) -> list[TaskEvent]:
    return list(
        db.scalars(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id, TaskEvent.id > max(0, after_id))
            .order_by(TaskEvent.id.asc())
            .limit(max(1, min(limit, 500)))
        ).all()
    )


def task_event_response(event: TaskEvent) -> dict[str, Any]:
    try:
        payload = json.loads(event.payload_json) if event.payload_json else None
    except json.JSONDecodeError:
        payload = None
    return {
        "id": event.id,
        "task_id": event.task_id,
        "event_type": event.event_type,
        "event_version": event.event_version,
        "step_id": event.step_id,
        "agent_type": event.agent_type,
        "status": event.status,
        "progress_percent": event.progress_percent,
        "message": safe_public_text(event.message),
        "payload": _sanitize_event_value(payload),
        "created_at": event.created_at,
    }


def _sanitize_event_value(value: Any) -> Any:
    value = sanitize_details(value)
    if isinstance(value, dict):
        return {
            str(key): _sanitize_event_value(item)
            for key, item in value.items()
            if str(key).lower() not in SENSITIVE_EVENT_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_event_value(item) for item in value[:100]]
    if isinstance(value, str):
        return safe_public_text(value[:4000])
    return value
