import json
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse as DownloadFileResponse
from fastapi import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_password_changed, require_password_changed_csrf
from app.db.session import get_db
from app.core.config import BACKEND_DIR, settings
from app.models.file import File
from app.models.task import Task
from app.models.tool_call import ToolCall
from app.models.user import User
from app.models.workspace_file import WorkspaceFile
from app.schemas.report import ReportResponse
from app.schemas.task import TaskCreate, ToolCallResponse
from app.schemas.workspace import V2ReportResponse, WorkspaceTaskResponse
from app.services.report_service import (
    ReportServiceError,
    generate_task_report,
    get_task_report,
    resolve_report_file,
)
from app.services.task_service import TaskServiceError, create_task, task_to_v2_response
from app.services.workspace_service import (
    get_owned_workspace,
    get_owned_workspace_task,
    safe_public_text,
)


router = APIRouter(prefix="/api/v2/workspaces/{workspace_id}/tasks", tags=["v2-workspace-tasks"])


def _task_or_404(db: Session, workspace_id: int, task_id: int, user_id: int) -> Task:
    task = get_owned_workspace_task(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        owner_user_id=user_id,
    )
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _safe_json_text(value: str | None) -> str | None:
    if not value:
        return value
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return value

    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                key: clean(child)
                for key, child in item.items()
                if str(key).lower()
                not in {"file_path", "report_path", "storage_path", "absolute_path"}
            }
        if isinstance(item, list):
            return [clean(child) for child in item]
        return item

    return json.dumps(clean(data), ensure_ascii=False)


@router.post("", response_model=WorkspaceTaskResponse, status_code=status.HTTP_201_CREATED)
def create_workspace_task(
    workspace_id: int,
    payload: TaskCreate,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict:
    workspace = get_owned_workspace(db, workspace_id=workspace_id, owner_user_id=user.id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    if workspace.status != "active":
        raise HTTPException(status_code=409, detail="已归档工作区不能创建新任务")
    normalized_ids = list(dict.fromkeys(int(file_id) for file_id in payload.file_ids))
    owned_ids = set(
        db.scalars(
            select(File.id)
            .join(WorkspaceFile, WorkspaceFile.file_id == File.id)
            .where(
                WorkspaceFile.workspace_id == workspace_id,
                File.owner_user_id == user.id,
                File.id.in_(normalized_ids),
            )
        ).all()
    )
    if len(owned_ids) != len(normalized_ids):
        raise HTTPException(status_code=400, detail="包含无权访问或不存在的文件")
    try:
        task = create_task(
            db,
            user_input=payload.user_input,
            file_ids=normalized_ids,
            owner_user_id=user.id,
            workspace_id=workspace_id,
        )
    except TaskServiceError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return task_to_v2_response(task)


@router.get("", response_model=list[WorkspaceTaskResponse])
def list_workspace_tasks(
    workspace_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> list[dict]:
    workspace = get_owned_workspace(db, workspace_id=workspace_id, owner_user_id=user.id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    tasks = db.scalars(
        select(Task)
        .where(
            Task.workspace_id == workspace_id,
            Task.owner_user_id == user.id,
        )
        .order_by(Task.created_at.desc())
    ).all()
    return [task_to_v2_response(task) for task in tasks]


@router.get("/{task_id}", response_model=WorkspaceTaskResponse)
def get_workspace_task(
    workspace_id: int,
    task_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict:
    return task_to_v2_response(_task_or_404(db, workspace_id, task_id, user.id))


@router.get("/{task_id}/trace", response_model=list[ToolCallResponse])
def get_workspace_task_trace(
    workspace_id: int,
    task_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> list[dict]:
    _task_or_404(db, workspace_id, task_id, user.id)
    records = db.scalars(
        select(ToolCall)
        .where(ToolCall.task_id == task_id)
        .order_by(ToolCall.created_at.asc())
    ).all()
    return [
        {
            "id": record.id,
            "task_id": record.task_id,
            "node_name": record.node_name,
            "tool_name": record.tool_name,
            "input_json": _safe_json_text(record.input_json),
            "output_json": _safe_json_text(record.output_json),
            "status": record.status,
            "latency_ms": record.latency_ms,
            "error_message": safe_public_text(record.error_message),
            "created_at": record.created_at,
        }
        for record in records
    ]


def _v2_report(workspace_id: int, report: dict) -> V2ReportResponse:
    content = _rewrite_report_assets(
        safe_public_text(report["content"]) or "",
        workspace_id,
        report["task_id"],
    )
    return V2ReportResponse(
        task_id=report["task_id"],
        title=report["title"],
        download_url=(
            f"/api/v2/workspaces/{workspace_id}/tasks/{report['task_id']}/report/download"
        ),
        content=content,
    )


def _rewrite_report_assets(content: str, workspace_id: int, task_id: int) -> str:
    prefix = f"/api/v2/workspaces/{workspace_id}/tasks/{task_id}/assets/"
    return re.sub(
        r"(?:/static/charts/|storage[\\/]charts[\\/])([^)\s]+)",
        lambda match: f"{prefix}{Path(match.group(1)).name}",
        content,
    )


@router.post("/{task_id}/report", response_model=V2ReportResponse)
def create_workspace_task_report(
    workspace_id: int,
    task_id: int,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> V2ReportResponse:
    _task_or_404(db, workspace_id, task_id, user.id)
    try:
        return _v2_report(workspace_id, generate_task_report(db, task_id))
    except ReportServiceError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.get("/{task_id}/report", response_model=V2ReportResponse)
def get_workspace_task_report(
    workspace_id: int,
    task_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> V2ReportResponse:
    _task_or_404(db, workspace_id, task_id, user.id)
    try:
        return _v2_report(workspace_id, get_task_report(db, task_id))
    except ReportServiceError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.get("/{task_id}/report/download")
def download_workspace_task_report(
    workspace_id: int,
    task_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> Response:
    _task_or_404(db, workspace_id, task_id, user.id)
    try:
        report = get_task_report(db, task_id)
        path = resolve_report_file(report["report_path"])
        content = _rewrite_report_assets(
            safe_public_text(report["content"]) or "",
            workspace_id,
            task_id,
        )
    except ReportServiceError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.get("/{task_id}/assets/{asset_name}")
def download_workspace_task_asset(
    workspace_id: int,
    task_id: int,
    asset_name: str,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> DownloadFileResponse:
    task = _task_or_404(db, workspace_id, task_id, user.id)
    try:
        file_ids = [int(value) for value in json.loads(task.file_ids_json or "[]")]
    except (TypeError, ValueError, json.JSONDecodeError):
        file_ids = []
    files = db.scalars(
        select(File).where(
            File.id.in_(file_ids),
            File.owner_user_id == user.id,
        )
    ).all()
    safe_name = Path(asset_name).name
    if safe_name != asset_name or not any(
        safe_name in (record.schema_json or "") for record in files
    ):
        raise HTTPException(status_code=404, detail="资源不存在")
    chart_dir = Path(settings.chart_dir)
    if not chart_dir.is_absolute():
        chart_dir = BACKEND_DIR / chart_dir
    asset_path = (chart_dir / safe_name).resolve()
    if asset_path.parent != chart_dir.resolve() or not asset_path.exists():
        raise HTTPException(status_code=404, detail="资源不存在")
    return DownloadFileResponse(path=asset_path, filename=safe_name)
