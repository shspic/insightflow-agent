from datetime import datetime
from app.core.timeutils import utcnow
from typing import Any

from sqlalchemy.orm import Session

from app.models.task import Task
from app.services.task_event_service import append_task_event
from app.services.workspace_service import safe_public_text


TERMINAL_TASK_STATUSES = {
    "completed",
    "completed_with_warnings",
    "failed",
    "cancelled",
}

ALLOWED_TASK_TRANSITIONS = {
    "draft": {"awaiting_clarification", "planning", "cancelled"},
    "awaiting_clarification": {"planning", "cancelled", "failed"},
    "planning": {"awaiting_clarification", "awaiting_confirmation", "failed", "cancelled"},
    "awaiting_confirmation": {"planning", "queued", "cancelled"},
    "queued": {"running", "cancelled", "failed"},
    "running": {"reviewing", "retrying", "completed", "failed", "cancelled"},
    "reviewing": {
        "retrying",
        "completed",
        "completed_with_warnings",
        "failed",
        "cancelled",
    },
    "retrying": {"queued", "running", "reviewing", "failed", "cancelled"},
    "completed": {"retrying"},
    "completed_with_warnings": {"retrying"},
    "failed": {"retrying"},
    "cancelled": set(),
}


class TaskStateError(Exception):
    def __init__(self, message: str, code: str = "INVALID_TASK_TRANSITION") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


def transition_task(
    db: Session,
    task: Task,
    target_status: str,
    *,
    message: str,
    progress_percent: int | None = None,
    event_type: str = "task_status_changed",
    step_id: int | None = None,
    agent_type: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Task:
    if target_status not in ALLOWED_TASK_TRANSITIONS:
        raise TaskStateError("未知任务状态", "UNKNOWN_TASK_STATUS")
    if task.status == target_status:
        return task
    allowed = ALLOWED_TASK_TRANSITIONS.get(task.status, set())
    if target_status not in allowed:
        raise TaskStateError(f"任务不能从 {task.status} 转换为 {target_status}")
    now = utcnow()
    old_status = task.status
    task.status = target_status
    if progress_percent is not None:
        task.progress_percent = _validate_progress(progress_percent)
    if target_status == "queued":
        task.queued_at = task.queued_at or now
    elif target_status == "running":
        task.started_at = task.started_at or now
    elif target_status in {"completed", "completed_with_warnings"}:
        task.completed_at = now
        task.progress_percent = 100
    elif target_status == "failed":
        task.failed_at = now
    elif target_status == "cancelled":
        task.completed_at = now
    task.updated_at = now
    append_task_event(
        db,
        task_id=task.id,
        event_type=event_type,
        message=message,
        status=target_status,
        progress_percent=task.progress_percent,
        step_id=step_id,
        agent_type=agent_type,
        payload={"from_status": old_status, "to_status": target_status, **(payload or {})},
    )
    db.flush()
    return task


def set_task_progress(
    db: Session,
    task: Task,
    progress_percent: int,
    *,
    message: str,
    step_id: int | None = None,
    agent_type: str | None = None,
) -> None:
    progress = _validate_progress(progress_percent)
    task.progress_percent = progress
    task.updated_at = utcnow()
    append_task_event(
        db,
        task_id=task.id,
        event_type="task_progress",
        message=message,
        status=task.status,
        progress_percent=progress,
        step_id=step_id,
        agent_type=agent_type,
    )
    db.flush()


def set_task_failure(task: Task, *, error_code: str, error_message: str) -> None:
    task.error_code = error_code[:80]
    task.error_message = safe_public_text(error_message)[:2000] if error_message else None


def _validate_progress(value: int) -> int:
    parsed = int(value)
    if not 0 <= parsed <= 100:
        raise TaskStateError("任务进度必须在 0 到 100 之间", "INVALID_PROGRESS")
    return parsed
