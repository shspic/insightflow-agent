import json
import asyncio
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse as DownloadFileResponse, StreamingResponse
from fastapi import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies.auth import require_password_changed, require_password_changed_csrf
from app.db.session import get_db
from app.core.config import BACKEND_DIR, settings
from app.models.file import File
from app.models.task import Task
from app.models.task_plan import TaskPlan
from app.models.task_step import TaskStep
from app.models.tool_call import ToolCall
from app.models.user import User
from app.models.workspace_file import WorkspaceFile
from app.schemas.report import ReportResponse
from app.schemas.task import TaskCreate, ToolCallResponse
from app.schemas.task_execution import (
    ClarificationAnswerRequest,
    PlanPatchRequest,
    TaskDraftCreate,
    TaskEventResponse,
    TaskExecutionDetail,
    TaskPlanResponse,
)
from app.schemas.workspace import V2ReportResponse, WorkspaceTaskResponse
from app.services.report_service import (
    ReportServiceError,
    generate_task_report,
    get_task_report,
    resolve_report_file,
)
from app.services.task_service import task_to_v2_response
from app.services.task_event_service import list_task_events, task_event_response
from app.services.task_planning_service import (
    TaskPlanningError,
    answer_clarification,
    confirm_plan,
    create_task_draft,
    patch_plan,
    plan_response,
    regenerate_plan,
    task_execution_detail,
)
from app.services.task_queue_service import (
    TaskQueueError,
    request_task_cancellation,
    retry_task,
)
from app.services.task_state_machine import TERMINAL_TASK_STATUSES
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
        task = create_task_draft(
            db,
            workspace_id=workspace_id,
            owner_user_id=user.id,
            payload=TaskDraftCreate(
                user_request=payload.user_input,
                selected_file_ids=normalized_ids,
                use_deepseek=False,
            ),
        )
    except TaskPlanningError as exc:
        raise _planning_http_error(exc) from exc
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


@router.post("/drafts", response_model=TaskExecutionDetail, status_code=status.HTTP_201_CREATED)
def create_workspace_task_draft(
    workspace_id: int,
    payload: TaskDraftCreate,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    workspace = get_owned_workspace(db, workspace_id=workspace_id, owner_user_id=user.id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    if workspace.status != "active":
        raise HTTPException(status_code=409, detail="已归档工作区不能创建新任务")
    try:
        task = create_task_draft(
            db,
            workspace_id=workspace_id,
            owner_user_id=user.id,
            payload=payload,
        )
    except TaskPlanningError as exc:
        raise _planning_http_error(exc) from exc
    return task_execution_detail(db, task)


@router.get("/{task_id}", response_model=TaskExecutionDetail)
def get_workspace_task(
    workspace_id: int,
    task_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict:
    return task_execution_detail(
        db,
        _task_or_404(db, workspace_id, task_id, user.id),
    )


@router.post("/{task_id}/clarifications", response_model=TaskExecutionDetail)
def answer_workspace_task_clarification(
    workspace_id: int,
    task_id: int,
    payload: ClarificationAnswerRequest,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task = _task_or_404(db, workspace_id, task_id, user.id)
    try:
        task = answer_clarification(
            db,
            task=task,
            answers=payload.answers,
            continue_with_recommendation=payload.continue_with_recommendation,
        )
    except TaskPlanningError as exc:
        raise _planning_http_error(exc) from exc
    return task_execution_detail(db, task)


@router.post("/{task_id}/plans/regenerate", response_model=TaskPlanResponse)
def regenerate_workspace_task_plan(
    workspace_id: int,
    task_id: int,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task = _task_or_404(db, workspace_id, task_id, user.id)
    try:
        plan = regenerate_plan(db, task=task)
    except TaskPlanningError as exc:
        raise _planning_http_error(exc) from exc
    return plan_response(plan)


@router.patch("/{task_id}/plans/{plan_id}", response_model=TaskPlanResponse)
def patch_workspace_task_plan(
    workspace_id: int,
    task_id: int,
    plan_id: int,
    payload: PlanPatchRequest,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task = _task_or_404(db, workspace_id, task_id, user.id)
    plan = db.get(TaskPlan, plan_id)
    if plan is None or plan.task_id != task.id:
        raise HTTPException(status_code=404, detail="计划不存在")
    try:
        updated = patch_plan(db, task=task, plan=plan, payload=payload)
    except TaskPlanningError as exc:
        raise _planning_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return plan_response(updated)


@router.post("/{task_id}/plans/{plan_id}/confirm", response_model=TaskExecutionDetail)
def confirm_workspace_task_plan(
    workspace_id: int,
    task_id: int,
    plan_id: int,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task = _task_or_404(db, workspace_id, task_id, user.id)
    plan = db.get(TaskPlan, plan_id)
    if plan is None or plan.task_id != task.id:
        raise HTTPException(status_code=404, detail="计划不存在")
    try:
        task = confirm_plan(db, task=task, plan=plan)
    except TaskPlanningError as exc:
        raise _planning_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return task_execution_detail(db, task)


@router.post("/{task_id}/cancel", response_model=TaskExecutionDetail)
def cancel_workspace_task(
    workspace_id: int,
    task_id: int,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task = _task_or_404(db, workspace_id, task_id, user.id)
    return task_execution_detail(db, request_task_cancellation(db, task))


@router.post("/{task_id}/retry", response_model=TaskExecutionDetail)
def retry_workspace_task(
    workspace_id: int,
    task_id: int,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task = _task_or_404(db, workspace_id, task_id, user.id)
    try:
        task = retry_task(db, task)
    except TaskQueueError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from exc
    return task_execution_detail(db, task)


@router.post("/{task_id}/steps/{step_id}/retry", response_model=TaskExecutionDetail)
def retry_workspace_task_step(
    workspace_id: int,
    task_id: int,
    step_id: int,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task = _task_or_404(db, workspace_id, task_id, user.id)
    step = db.get(TaskStep, step_id)
    if step is None or step.task_id != task.id:
        raise HTTPException(status_code=404, detail="步骤不存在")
    try:
        task = retry_task(db, task, step_id=step.id)
    except TaskQueueError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from exc
    return task_execution_detail(db, task)


@router.get("/{task_id}/events", response_model=list[TaskEventResponse])
def get_workspace_task_events(
    workspace_id: int,
    task_id: int,
    after_id: int = Query(default=0, ge=0),
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _task_or_404(db, workspace_id, task_id, user.id)
    return [
        task_event_response(item)
        for item in list_task_events(db, task_id=task_id, after_id=after_id)
    ]


@router.get("/{task_id}/events/stream")
def stream_workspace_task_events(
    workspace_id: int,
    task_id: int,
    request: Request,
    after_id: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    _task_or_404(db, workspace_id, task_id, user.id)
    start_id = after_id
    if last_event_id and last_event_id.isdigit():
        start_id = max(start_id, int(last_event_id))
    event_session = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)

    async def event_stream():
        cursor = start_id
        last_heartbeat = asyncio.get_running_loop().time()
        try:
            while True:
                if await request.is_disconnected():
                    return
                with event_session() as event_db:
                    owned_task = get_owned_workspace_task(
                        event_db,
                        workspace_id=workspace_id,
                        task_id=task_id,
                        owner_user_id=user.id,
                    )
                    if owned_task is None:
                        return
                    events = list_task_events(
                        event_db,
                        task_id=task_id,
                        after_id=cursor,
                    )
                    terminal = owned_task.status in TERMINAL_TASK_STATUSES
                for event in events:
                    cursor = event.id
                    data = json.dumps(
                        task_event_response(event),
                        ensure_ascii=False,
                        default=str,
                    )
                    yield f"id: {event.id}\nevent: {event.event_type}\ndata: {data}\n\n"
                if terminal:
                    return
                now = asyncio.get_running_loop().time()
                if now - last_heartbeat >= max(1, settings.task_event_heartbeat_seconds):
                    yield ": heartbeat\n\n"
                    last_heartbeat = now
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    task = _task_or_404(db, workspace_id, task_id, user.id)
    if task.agent_state_json:
        if task.status not in TERMINAL_TASK_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="V2 任务必须在计划确认并执行完成后生成报告",
            )
        if task.report_path:
            try:
                return _v2_report(workspace_id, get_task_report(db, task_id))
            except ReportServiceError as exc:
                raise HTTPException(status_code=404, detail=exc.message) from exc
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


def _planning_http_error(exc: TaskPlanningError) -> HTTPException:
    if exc.code in {"WORKSPACE_NOT_FOUND", "TASK_NOT_FOUND", "PLAN_NOT_FOUND"}:
        status_code = 404
    elif exc.code in {"INVALID_TASK_STATUS", "INVALID_PLAN_STATUS", "REPLAN_LIMIT_REACHED"}:
        status_code = 409
    else:
        status_code = 422
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message},
    )
