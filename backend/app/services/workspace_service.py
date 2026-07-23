import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.core.config import BACKEND_DIR


def get_owned_workspace(
    db: Session,
    *,
    workspace_id: int,
    owner_user_id: int,
    include_deleted: bool = False,
) -> Workspace | None:
    filters = [
        Workspace.id == workspace_id,
        Workspace.owner_user_id == owner_user_id,
    ]
    if not include_deleted:
        filters.append(Workspace.deleted_at.is_(None))
    return db.scalar(select(Workspace).where(*filters))


def get_owned_workspace_file(
    db: Session,
    *,
    workspace_id: int,
    file_id: int,
    owner_user_id: int,
) -> File | None:
    return db.scalar(
        select(File)
        .join(WorkspaceFile, WorkspaceFile.file_id == File.id)
        .join(Workspace, Workspace.id == WorkspaceFile.workspace_id)
        .where(
            Workspace.id == workspace_id,
            Workspace.owner_user_id == owner_user_id,
            Workspace.deleted_at.is_(None),
            WorkspaceFile.workspace_id == workspace_id,
            WorkspaceFile.file_id == file_id,
            File.id == file_id,
            File.owner_user_id == owner_user_id,
        )
    )


def get_owned_workspace_task(
    db: Session,
    *,
    workspace_id: int,
    task_id: int,
    owner_user_id: int,
) -> Task | None:
    return db.scalar(
        select(Task)
        .join(Workspace, Workspace.id == Task.workspace_id)
        .where(
            Workspace.id == workspace_id,
            Workspace.owner_user_id == owner_user_id,
            Workspace.deleted_at.is_(None),
            Task.id == task_id,
            Task.workspace_id == workspace_id,
            Task.owner_user_id == owner_user_id,
        )
    )


def workspace_counts(db: Session, workspace_id: int) -> tuple[int, int]:
    file_count = db.scalar(
        select(func.count()).select_from(WorkspaceFile).where(
            WorkspaceFile.workspace_id == workspace_id
        )
    ) or 0
    task_count = db.scalar(
        select(func.count()).select_from(Task).where(Task.workspace_id == workspace_id)
    ) or 0
    return file_count, task_count


def safe_schema(schema_json: str | None, download_prefix: str) -> dict[str, Any] | None:
    if not schema_json:
        return None
    try:
        data = json.loads(schema_json)
    except json.JSONDecodeError:
        return None
    return _remove_paths(data, download_prefix)


def _remove_paths(value: Any, download_prefix: str) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in {"file_path", "report_path", "storage_path", "absolute_path"}:
                continue
            if normalized == "url_path" and isinstance(item, str):
                cleaned[key] = f"{download_prefix}/assets/{Path(item).name}"
                continue
            cleaned[key] = _remove_paths(item, download_prefix)
        return cleaned
    if isinstance(value, list):
        return [_remove_paths(item, download_prefix) for item in value]
    return value


def workspace_response(db: Session, workspace: Workspace) -> dict[str, Any]:
    file_count, task_count = workspace_counts(db, workspace.id)
    return {
        "id": workspace.id,
        "name": workspace.name,
        "description": workspace.description,
        "status": workspace.status,
        "is_deleted": workspace.deleted_at is not None,
        "file_count": file_count,
        "task_count": task_count,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
        "deleted_at": workspace.deleted_at,
    }


def safe_public_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.replace(str(BACKEND_DIR), "[服务器路径已隐藏]")
    return re.sub(
        r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s<>\"]+",
        "[服务器路径已隐藏]",
        cleaned,
    )
