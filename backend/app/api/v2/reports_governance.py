import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_password_changed, require_password_changed_csrf
from app.db.session import get_db
from app.models.report_asset import ReportAsset
from app.models.task import Task
from app.models.user import User
from app.models.user_feedback import UserFeedback
from app.schemas.report_delivery import (
    FeedbackCreate,
    FeedbackResponse,
    ReportRegenerateRequest,
    ReportVersionResponse,
)
from app.services.audit_service import add_audit_log
from app.services.report_template_service import list_report_templates
from app.services.quota_service import QuotaExceeded, check_report_export, increment_usage
from app.services.report_version_service import (
    ReportVersionError,
    create_report_version,
    delete_report_version,
    export_report,
    get_owned_report,
    list_owned_reports,
    report_response,
    resolve_asset_path,
    set_current_report,
)
from app.services.task_queue_service import TaskQueueError, requeue_task_for_reanalysis
from app.services.workspace_service import get_owned_workspace_task


router = APIRouter(prefix="/api/v2", tags=["v2-reports-governance"])


def _task_or_404(db: Session, workspace_id: int, task_id: int, user_id: int) -> Task:
    task = get_owned_workspace_task(
        db, workspace_id=workspace_id, task_id=task_id, owner_user_id=user_id
    )
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    return task


def _report_error(exc: ReportVersionError) -> HTTPException:
    code = 429 if exc.code == "REPORT_VERSION_LIMIT" else 409
    if exc.code in {"REPORT_NOT_FOUND", "ASSET_NOT_FOUND"}:
        code = 404
    return HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message})


@router.get("/report-templates")
def get_templates(
    user: User = Depends(require_password_changed),
) -> list[dict]:
    return list_report_templates()


@router.get(
    "/workspaces/{workspace_id}/tasks/{task_id}/reports",
    response_model=list[ReportVersionResponse],
)
def list_reports(
    workspace_id: int,
    task_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> list[dict]:
    task = _task_or_404(db, workspace_id, task_id, user.id)
    return [
        report_response(db, task=task, report=item)
        for item in list_owned_reports(
            db, workspace_id=workspace_id, task_id=task_id, owner_user_id=user.id
        )
    ]


@router.get(
    "/workspaces/{workspace_id}/tasks/{task_id}/reports/{report_id}",
    response_model=ReportVersionResponse,
)
def get_report(
    workspace_id: int,
    task_id: int,
    report_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict:
    task = _task_or_404(db, workspace_id, task_id, user.id)
    try:
        report = get_owned_report(
            db,
            workspace_id=workspace_id,
            task_id=task_id,
            report_id=report_id,
            owner_user_id=user.id,
        )
    except ReportVersionError as exc:
        raise _report_error(exc) from exc
    return report_response(db, task=task, report=report)


@router.post(
    "/workspaces/{workspace_id}/tasks/{task_id}/reports/{report_id}/current",
    response_model=ReportVersionResponse,
)
def select_current_report(
    workspace_id: int,
    task_id: int,
    report_id: int,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict:
    task = _task_or_404(db, workspace_id, task_id, user.id)
    try:
        report = get_owned_report(
            db,
            workspace_id=workspace_id,
            task_id=task_id,
            report_id=report_id,
            owner_user_id=user.id,
        )
        set_current_report(db, task=task, report=report)
        add_audit_log(
            db,
            action="report.set_current",
            status="success",
            user_id=user.id,
            resource_type="report",
            resource_id=report.id,
        )
        db.commit()
        db.refresh(report)
    except ReportVersionError as exc:
        db.rollback()
        raise _report_error(exc) from exc
    return report_response(db, task=task, report=report)


@router.post(
    "/workspaces/{workspace_id}/tasks/{task_id}/reports/{report_id}/exports",
    status_code=status.HTTP_201_CREATED,
)
def create_export(
    workspace_id: int,
    task_id: int,
    report_id: int,
    export_format: str = Query(alias="format", pattern="^(markdown|docx|pdf)$"),
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict:
    _task_or_404(db, workspace_id, task_id, user.id)
    try:
        check_report_export(db, user)
        report = get_owned_report(
            db,
            workspace_id=workspace_id,
            task_id=task_id,
            report_id=report_id,
            owner_user_id=user.id,
        )
        existing_asset = db.scalar(
            select(ReportAsset.id).where(
                ReportAsset.report_id == report.id,
                ReportAsset.asset_type == export_format,
                ReportAsset.checksum == report.content_hash,
                ReportAsset.status == "ready",
                ReportAsset.deleted_at.is_(None),
            )
        )
        asset = export_report(db, report=report, export_format=export_format)
        if existing_asset is None:
            increment_usage(db, user.id, report_storage_bytes=asset.size_bytes)
        add_audit_log(
            db,
            action="report.export",
            status="success",
            user_id=user.id,
            resource_type="report",
            resource_id=report.id,
            details={"format": export_format, "asset_id": asset.id},
        )
        db.commit()
    except ReportVersionError as exc:
        db.rollback()
        raise _report_error(exc) from exc
    except QuotaExceeded as exc:
        db.rollback()
        raise HTTPException(status_code=429, detail=exc.detail()) from exc
    return {
        "asset_id": asset.id,
        "status": asset.status,
        "format": asset.format,
        "reused": existing_asset is not None,
        "download_url": (
            f"/api/v2/workspaces/{workspace_id}/tasks/{task_id}/reports/"
            f"{report_id}/assets/{asset.id}/download"
        ),
    }


@router.get(
    "/workspaces/{workspace_id}/tasks/{task_id}/reports/{report_id}/assets/{asset_id}/download"
)
def download_asset(
    workspace_id: int,
    task_id: int,
    report_id: int,
    asset_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> FileResponse:
    _task_or_404(db, workspace_id, task_id, user.id)
    try:
        report = get_owned_report(
            db,
            workspace_id=workspace_id,
            task_id=task_id,
            report_id=report_id,
            owner_user_id=user.id,
        )
    except ReportVersionError as exc:
        raise _report_error(exc) from exc
    asset = db.scalar(
        select(ReportAsset).where(
            ReportAsset.id == asset_id,
            ReportAsset.report_id == report.id,
            ReportAsset.task_id == task_id,
            ReportAsset.workspace_id == workspace_id,
            ReportAsset.owner_user_id == user.id,
            ReportAsset.status == "ready",
            ReportAsset.deleted_at.is_(None),
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="报告资产不存在")
    try:
        path = resolve_asset_path(asset)
    except ReportVersionError as exc:
        raise _report_error(exc) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="报告资产文件不存在")
    return FileResponse(
        path,
        media_type=asset.mime_type,
        filename=asset.display_name,
        headers={"Cache-Control": "private, no-store"},
    )


@router.delete("/workspaces/{workspace_id}/tasks/{task_id}/reports/{report_id}")
def delete_report(
    workspace_id: int,
    task_id: int,
    report_id: int,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict:
    task = _task_or_404(db, workspace_id, task_id, user.id)
    try:
        report = get_owned_report(
            db,
            workspace_id=workspace_id,
            task_id=task_id,
            report_id=report_id,
            owner_user_id=user.id,
        )
        delete_report_version(db, task=task, report=report)
        add_audit_log(
            db,
            action="report.delete_version",
            status="success",
            user_id=user.id,
            resource_type="report",
            resource_id=report.id,
        )
        db.commit()
    except ReportVersionError as exc:
        db.rollback()
        raise _report_error(exc) from exc
    return {"status": "scheduled_for_cleanup", "report_id": report.id}


@router.post(
    "/workspaces/{workspace_id}/tasks/{task_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_feedback(
    workspace_id: int,
    task_id: int,
    payload: FeedbackCreate,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict:
    _task_or_404(db, workspace_id, task_id, user.id)
    if payload.report_id is not None:
        try:
            get_owned_report(
                db,
                workspace_id=workspace_id,
                task_id=task_id,
                report_id=payload.report_id,
                owner_user_id=user.id,
            )
        except ReportVersionError as exc:
            raise _report_error(exc) from exc
    record = UserFeedback(
        user_id=user.id,
        workspace_id=workspace_id,
        task_id=task_id,
        report_id=payload.report_id,
        feedback_type=payload.feedback_type,
        rating=payload.rating,
        comment=payload.comment,
        issue_category=payload.issue_category,
        correction_json=(
            json.dumps(payload.correction.model_dump(exclude_none=True), ensure_ascii=False)
            if payload.correction
            else None
        ),
    )
    db.add(record)
    db.flush()
    add_audit_log(
        db,
        action="feedback.create",
        status="success",
        user_id=user.id,
        resource_type="feedback",
        resource_id=record.id,
        details={"feedback_type": record.feedback_type, "report_id": record.report_id},
    )
    db.commit()
    db.refresh(record)
    return _feedback_response(record)


@router.get(
    "/workspaces/{workspace_id}/tasks/{task_id}/feedback",
    response_model=list[FeedbackResponse],
)
def list_feedback(
    workspace_id: int,
    task_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> list[dict]:
    _task_or_404(db, workspace_id, task_id, user.id)
    records = db.scalars(
        select(UserFeedback)
        .where(
            UserFeedback.workspace_id == workspace_id,
            UserFeedback.task_id == task_id,
            UserFeedback.user_id == user.id,
        )
        .order_by(UserFeedback.created_at.desc())
    ).all()
    return [_feedback_response(item) for item in records]


@router.post("/workspaces/{workspace_id}/tasks/{task_id}/reports/regenerate")
def regenerate_report(
    workspace_id: int,
    task_id: int,
    payload: ReportRegenerateRequest,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict:
    task = _task_or_404(db, workspace_id, task_id, user.id)
    if payload.report_id is not None:
        try:
            get_owned_report(
                db,
                workspace_id=workspace_id,
                task_id=task_id,
                report_id=payload.report_id,
                owner_user_id=user.id,
            )
        except ReportVersionError as exc:
            raise _report_error(exc) from exc
    if payload.feedback_id is not None:
        feedback = db.scalar(
            select(UserFeedback).where(
                UserFeedback.id == payload.feedback_id,
                UserFeedback.task_id == task_id,
                UserFeedback.user_id == user.id,
            )
        )
        if feedback is None:
            raise HTTPException(status_code=404, detail="反馈不存在")
    if payload.rerun_analysis:
        try:
            task.report_preferences_json = json.dumps(
                {"template_key": payload.template_key}, ensure_ascii=False
            )
            queued = requeue_task_for_reanalysis(db, task)
        except TaskQueueError as exc:
            raise HTTPException(
                status_code=409, detail={"code": exc.code, "message": exc.message}
            ) from exc
        add_audit_log(
            db,
            action="report.regenerate_with_analysis",
            status="queued",
            user_id=user.id,
            resource_type="task",
            resource_id=task.id,
            details={"template_key": payload.template_key},
        )
        db.commit()
        return {"status": "queued", "task_id": queued.id, "reuse_analysis": False}

    try:
        state = json.loads(task.agent_state_json or "{}")
    except json.JSONDecodeError:
        state = {}
    if not state:
        raise HTTPException(status_code=409, detail="任务没有可复用的已完成分析结果")
    source = "feedback_regenerate" if payload.feedback_id else "user_regenerate"
    try:
        report = create_report_version(
            db,
            task=task,
            state=state,
            template_key=payload.template_key,
            generation_source=source,
            correction_note=payload.correction_note,
        )
        add_audit_log(
            db,
            action="report.regenerate",
            status="success",
            user_id=user.id,
            resource_type="report",
            resource_id=report.id,
            details={"template_key": payload.template_key, "reuse_analysis": True},
        )
        db.commit()
        db.refresh(report)
    except ReportVersionError as exc:
        db.rollback()
        raise _report_error(exc) from exc
    return report_response(db, task=task, report=report)


def _feedback_response(record: UserFeedback) -> dict:
    correction = None
    if record.correction_json:
        try:
            correction = json.loads(record.correction_json)
        except json.JSONDecodeError:
            correction = None
    return {
        "id": record.id,
        "task_id": record.task_id,
        "report_id": record.report_id,
        "feedback_type": record.feedback_type,
        "rating": record.rating,
        "comment": record.comment,
        "issue_category": record.issue_category,
        "correction": correction,
        "status": record.status,
        "created_at": record.created_at,
    }
