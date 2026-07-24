from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.file import File
from app.models.report_asset import ReportAsset
from app.models.task import Task
from app.models.tool_call import ToolCall
from app.models.usage import ModelUsageRecord, QuotaOverride, UsageCounter
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile


RUNNING_STATUSES = {"queued", "running", "reviewing", "retrying"}


class QuotaExceeded(Exception):
    def __init__(self, quota_key: str, usage: int, limit: int) -> None:
        self.quota_key = quota_key
        self.usage = usage
        self.limit = limit
        self.reset_at = _next_reset()
        super().__init__(f"配额 {quota_key} 已达到上限 {limit}")

    def detail(self) -> dict[str, Any]:
        return {
            "code": "QUOTA_EXCEEDED",
            "quota_key": self.quota_key,
            "usage": self.usage,
            "limit": self.limit,
            "reset_at": self.reset_at.isoformat(),
        }


def check_task_creation(db: Session, user: User) -> None:
    if user.role != "admin":
        _enforce(db, user, "daily_tasks", _today_counter(db, user.id).tasks_created)
    running = db.scalar(
        select(func.count(Task.id)).where(
            Task.owner_user_id == user.id, Task.status.in_(RUNNING_STATUSES)
        )
    ) or 0
    _enforce(db, user, "concurrent_tasks", int(running))


def check_plan_confirmation(db: Session, user: User, task: Task) -> None:
    running = db.scalar(
        select(func.count(Task.id)).where(
            Task.owner_user_id == user.id,
            Task.id != task.id,
            Task.status.in_(RUNNING_STATUSES),
        )
    ) or 0
    _enforce(db, user, "concurrent_tasks", int(running))
    global_running = db.scalar(
        select(func.count(Task.id)).where(Task.status.in_(RUNNING_STATUSES))
    ) or 0
    global_limit = max(1, settings.system_max_running_tasks)
    if int(global_running) >= global_limit:
        raise QuotaExceeded("system_running_tasks", int(global_running), global_limit)


def check_model_call(db: Session, user: User, task: Task) -> None:
    task_calls = db.scalar(
        select(func.count(ModelUsageRecord.id)).where(ModelUsageRecord.task_id == task.id)
    ) or 0
    _enforce(db, user, "task_model_calls", int(task_calls))
    if user.role != "admin":
        _enforce(
            db,
            user,
            "daily_deepseek_calls",
            _today_counter(db, user.id).deepseek_calls,
        )


def check_tool_call(db: Session, user: User, task: Task) -> None:
    task_calls = db.scalar(
        select(func.count(ToolCall.id)).where(ToolCall.task_id == task.id)
    ) or 0
    _enforce(db, user, "task_tool_calls", int(task_calls))


def check_workspace_creation(db: Session, user: User) -> None:
    count = db.scalar(
        select(func.count(Workspace.id)).where(
            Workspace.owner_user_id == user.id,
            Workspace.deleted_at.is_(None),
        )
    ) or 0
    _enforce(db, user, "workspaces", int(count))


def check_file_upload(
    db: Session,
    user: User,
    *,
    workspace_id: int,
    incoming_size: int = 0,
    configured_storage_limit: int | None = None,
) -> None:
    file_count = db.scalar(
        select(func.count(WorkspaceFile.id)).where(WorkspaceFile.workspace_id == workspace_id)
    ) or 0
    _enforce(db, user, "workspace_files", int(file_count))
    if user.role != "admin":
        storage = db.scalar(
            select(func.coalesce(func.sum(File.size_bytes), 0)).where(
                File.owner_user_id == user.id
            )
        ) or 0
        limit = get_limit(
            db,
            user,
            "storage_bytes",
            configured_default=configured_storage_limit,
        )
        if int(storage) + max(0, incoming_size) > limit:
            raise QuotaExceeded("storage_bytes", int(storage) + max(0, incoming_size), limit)


def check_report_export(db: Session, user: User) -> None:
    today_start = datetime.combine(date.today(), time.min)
    count = db.scalar(
        select(func.count(ReportAsset.id)).where(
            ReportAsset.owner_user_id == user.id,
            ReportAsset.asset_type.in_(["markdown", "docx", "pdf"]),
            ReportAsset.created_at >= today_start,
        )
    ) or 0
    _enforce(db, user, "daily_report_exports", int(count))


def increment_usage(db: Session, user_id: int, **values: int) -> UsageCounter:
    counter = _today_counter(db, user_id)
    allowed = {
        "tasks_created",
        "tasks_succeeded",
        "tasks_failed",
        "deepseek_calls",
        "input_tokens",
        "output_tokens",
        "tool_calls",
        "file_storage_bytes",
        "report_storage_bytes",
        "task_duration_ms",
    }
    for key, value in values.items():
        if key in allowed:
            setattr(counter, key, int(getattr(counter, key) or 0) + max(0, int(value)))
    db.flush()
    return counter


def usage_snapshot(db: Session, user: User) -> dict[str, Any]:
    counter = _today_counter(db, user.id)
    file_bytes = db.scalar(
        select(func.coalesce(func.sum(File.size_bytes), 0)).where(File.owner_user_id == user.id)
    ) or 0
    report_bytes = db.scalar(
        select(func.coalesce(func.sum(ReportAsset.size_bytes), 0)).where(
            ReportAsset.owner_user_id == user.id,
            ReportAsset.status == "ready",
            ReportAsset.deleted_at.is_(None),
        )
    ) or 0
    workspaces = db.scalar(
        select(func.count(Workspace.id)).where(
            Workspace.owner_user_id == user.id, Workspace.deleted_at.is_(None)
        )
    ) or 0
    running = db.scalar(
        select(func.count(Task.id)).where(
            Task.owner_user_id == user.id, Task.status.in_(RUNNING_STATUSES)
        )
    ) or 0
    usage = {
        "daily_tasks": counter.tasks_created,
        "daily_deepseek_calls": counter.deepseek_calls,
        "storage_bytes": int(file_bytes) + int(report_bytes),
        "file_storage_bytes": int(file_bytes),
        "report_storage_bytes": int(report_bytes),
        "workspaces": int(workspaces),
        "concurrent_tasks": int(running),
        "task_model_calls": None,
        "task_tool_calls": None,
    }
    quota_keys = (
        "daily_tasks",
        "daily_deepseek_calls",
        "storage_bytes",
        "workspaces",
        "concurrent_tasks",
        "workspace_files",
        "task_model_calls",
        "task_tool_calls",
        "daily_report_exports",
    )
    return {
        "date": date.today().isoformat(),
        "usage": usage,
        "limits": {key: get_limit(db, user, key) for key in quota_keys},
        "reset_at": _next_reset().isoformat(),
        "admin_exemptions": (
            ["daily_tasks", "daily_deepseek_calls", "storage_bytes"]
            if user.role == "admin"
            else []
        ),
    }


def get_limit(
    db: Session,
    user: User,
    quota_key: str,
    *,
    configured_default: int | None = None,
) -> int:
    override = db.scalar(
        select(QuotaOverride).where(
            QuotaOverride.user_id == user.id,
            QuotaOverride.quota_key == quota_key,
            (QuotaOverride.expires_at.is_(None) | (QuotaOverride.expires_at > datetime.utcnow())),
        )
    )
    if override is not None:
        return max(0, override.limit_value)
    defaults = {
        "daily_tasks": settings.user_daily_tasks,
        "daily_deepseek_calls": settings.user_daily_deepseek_calls,
        "storage_bytes": settings.user_storage_quota_bytes,
        "workspaces": settings.user_max_workspaces,
        "concurrent_tasks": settings.user_concurrent_tasks,
        "workspace_files": settings.workspace_max_files,
        "task_model_calls": settings.task_model_call_budget,
        "task_tool_calls": settings.task_tool_call_budget,
        "daily_report_exports": settings.report_export_daily_limit,
    }
    if quota_key not in defaults:
        raise ValueError("未知配额键")
    default_value = (
        configured_default
        if configured_default is not None
        else defaults[quota_key]
    )
    return max(0, int(default_value))


def set_quota_override(
    db: Session,
    *,
    target_user_id: int,
    quota_key: str,
    limit_value: int,
    expires_at: datetime | None,
    note: str,
    admin_user_id: int,
) -> QuotaOverride:
    if quota_key not in {
        "daily_tasks",
        "daily_deepseek_calls",
        "storage_bytes",
        "workspaces",
        "concurrent_tasks",
        "workspace_files",
        "task_model_calls",
        "task_tool_calls",
        "daily_report_exports",
    }:
        raise ValueError("未知配额键")
    record = db.scalar(
        select(QuotaOverride).where(
            QuotaOverride.user_id == target_user_id,
            QuotaOverride.quota_key == quota_key,
        )
    )
    if record is None:
        record = QuotaOverride(
            user_id=target_user_id,
            quota_key=quota_key,
            limit_value=limit_value,
            expires_at=expires_at,
            note=note,
            created_by_user_id=admin_user_id,
        )
        db.add(record)
    else:
        record.limit_value = limit_value
        record.expires_at = expires_at
        record.note = note
        record.created_by_user_id = admin_user_id
    db.flush()
    return record


def _enforce(db: Session, user: User, quota_key: str, usage: int) -> None:
    limit = get_limit(db, user, quota_key)
    if usage >= limit:
        raise QuotaExceeded(quota_key, usage, limit)


def _today_counter(db: Session, user_id: int) -> UsageCounter:
    today = date.today()
    counter = db.scalar(
        select(UsageCounter)
        .where(UsageCounter.user_id == user_id, UsageCounter.usage_date == today)
        .with_for_update()
    )
    if counter is None:
        counter = UsageCounter(user_id=user_id, usage_date=today)
        db.add(counter)
        db.flush()
    return counter


def _next_reset() -> datetime:
    return datetime.combine(date.today() + timedelta(days=1), time.min)
