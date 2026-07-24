from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import (
    require_admin,
    require_admin_csrf,
    require_password_changed,
)
from app.db.session import get_db
from app.models.operations import WorkerStatus
from app.models.evaluation import EvaluationDataset, EvaluationRun
from app.models.prompt_version import PromptVersion
from app.models.task import Task
from app.models.usage import ModelUsageRecord, UsageCounter
from app.models.user import User
from app.models.user_feedback import UserFeedback
from app.services.audit_service import add_audit_log
from app.services.monitoring_service import operational_summary
from app.services.prompt_version_service import activate_prompt
from app.services.quota_service import set_quota_override, usage_snapshot
from app.services.workspace_service import safe_public_text
from app.evaluation.runner import run_evaluation, run_response
from app.maintenance.cleanup import cleanup_response, run_cleanup


router = APIRouter(prefix="/api/v2", tags=["v2-operations"])


class QuotaOverridePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quota_key: str = Field(max_length=80)
    limit_value: int = Field(ge=0)
    expires_at: datetime | None = None
    note: str = Field(min_length=1, max_length=500)


class EvaluationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str = "v2-core"
    mode: str = Field(default="deterministic", pattern="^deterministic$")
    category: str | None = Field(default=None, max_length=80)


class CleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True
    confirmation: str | None = None


@router.get("/usage/me")
def get_my_usage(
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict:
    return usage_snapshot(db, user)


@router.get("/admin/usage/summary")
def get_usage_summary(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    counters = list(db.scalars(select(UsageCounter)).all())
    return {
        "operational": operational_summary(db),
        "usage": {
            "tasks_created": sum(item.tasks_created for item in counters),
            "tasks_succeeded": sum(item.tasks_succeeded for item in counters),
            "tasks_failed": sum(item.tasks_failed for item in counters),
            "deepseek_calls": sum(item.deepseek_calls for item in counters),
            "input_tokens": sum(item.input_tokens for item in counters),
            "output_tokens": sum(item.output_tokens for item in counters),
            "tool_calls": sum(item.tool_calls for item in counters),
            "file_storage_bytes": sum(item.file_storage_bytes for item in counters),
            "report_storage_bytes": sum(item.report_storage_bytes for item in counters),
            "task_duration_ms": sum(item.task_duration_ms for item in counters),
        },
    }


@router.get("/admin/usage/users")
def get_user_usage(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    users = db.scalars(
        select(User)
        .order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            {
                "user_id": user.id,
                "username": user.username,
                "role": user.role,
                **usage_snapshot(db, user),
            }
            for user in users
        ],
        "total": db.scalar(select(func.count(User.id))) or 0,
    }


@router.patch("/admin/users/{user_id}/quota")
def patch_user_quota(
    user_id: int,
    payload: QuotaOverridePatch,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> dict:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        record = set_quota_override(
            db,
            target_user_id=target.id,
            quota_key=payload.quota_key,
            limit_value=payload.limit_value,
            expires_at=payload.expires_at,
            note=payload.note,
            admin_user_id=admin.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    add_audit_log(
        db,
        action="quota.override",
        status="success",
        user_id=admin.id,
        resource_type="user",
        resource_id=target.id,
        details={
            "quota_key": payload.quota_key,
            "limit_value": payload.limit_value,
            "expires_at": payload.expires_at,
            "note": payload.note,
        },
    )
    db.commit()
    return {
        "id": record.id,
        "user_id": record.user_id,
        "quota_key": record.quota_key,
        "limit_value": record.limit_value,
        "expires_at": record.expires_at,
        "note": record.note,
    }


@router.get("/admin/tasks")
def admin_tasks(
    task_status: str | None = Query(default=None, alias="status"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = select(Task).order_by(Task.created_at.desc()).limit(200)
    if task_status:
        statement = statement.where(Task.status == task_status)
    return [
        {
            "id": item.id,
            "owner_user_id": item.owner_user_id,
            "workspace_id": item.workspace_id,
            "status": item.status,
            "task_type": item.task_type,
            "progress_percent": item.progress_percent,
            "worker_id": item.worker_id,
            "retry_count": item.retry_count,
            "queued_at": item.queued_at,
            "started_at": item.started_at,
            "completed_at": item.completed_at,
            "error_code": item.error_code,
            "error_message": safe_public_text(item.error_message),
        }
        for item in db.scalars(statement).all()
    ]


@router.get("/admin/workers")
def admin_workers(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {
            "worker_id": item.worker_id,
            "status": item.status,
            "last_heartbeat_at": item.last_heartbeat_at,
            "current_task_id": item.current_task_id,
            "lease_expires_at": item.lease_expires_at,
            "started_at": item.started_at,
            "completed_tasks": item.completed_tasks,
            "failed_tasks": item.failed_tasks,
        }
        for item in db.scalars(
            select(WorkerStatus).order_by(WorkerStatus.last_heartbeat_at.desc())
        ).all()
    ]


@router.get("/admin/model-usage")
def admin_model_usage(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {
            "id": item.id,
            "user_id": item.user_id,
            "task_id": item.task_id,
            "provider": item.provider,
            "model_name": item.model_name,
            "prompt_name": item.prompt_name,
            "prompt_version": item.prompt_version,
            "status": item.status,
            "input_tokens": item.input_tokens,
            "output_tokens": item.output_tokens,
            "duration_ms": item.duration_ms,
            "estimated_cost_micros": item.estimated_cost_micros,
            "error_code": item.error_code,
            "created_at": item.created_at,
        }
        for item in db.scalars(
            select(ModelUsageRecord).order_by(ModelUsageRecord.created_at.desc()).limit(500)
        ).all()
    ]


@router.get("/admin/feedback")
def admin_feedback(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {
            "id": item.id,
            "user_id": item.user_id,
            "workspace_id": item.workspace_id,
            "task_id": item.task_id,
            "report_id": item.report_id,
            "feedback_type": item.feedback_type,
            "rating": item.rating,
            "issue_category": item.issue_category,
            "status": item.status,
            "created_at": item.created_at,
        }
        for item in db.scalars(
            select(UserFeedback).order_by(UserFeedback.created_at.desc()).limit(500)
        ).all()
    ]


@router.get("/admin/prompt-versions")
def admin_prompt_versions(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {
            "id": item.id,
            "prompt_name": item.prompt_name,
            "version": item.version,
            "status": item.status,
            "purpose": item.purpose,
            "template_text": item.template_text,
            "input_schema": item.input_schema_json,
            "output_schema": item.output_schema_json,
            "content_hash": item.content_hash,
            "created_at": item.created_at,
            "activated_at": item.activated_at,
            "retired_at": item.retired_at,
        }
        for item in db.scalars(
            select(PromptVersion).order_by(PromptVersion.prompt_name, PromptVersion.created_at.desc())
        ).all()
    ]


@router.post("/admin/prompt-versions/{prompt_id}/activate")
def admin_activate_prompt(
    prompt_id: int,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> dict:
    try:
        record = activate_prompt(db, prompt_id, admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    add_audit_log(
        db,
        action="prompt.activate",
        status="success",
        user_id=admin.id,
        resource_type="prompt_version",
        resource_id=record.id,
        details={"prompt_name": record.prompt_name, "version": record.version},
    )
    db.commit()
    return {"id": record.id, "status": record.status, "activated_at": record.activated_at}


@router.get("/admin/evaluations/datasets")
def admin_evaluation_datasets(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {
            "id": item.id,
            "name": item.name,
            "version": item.version,
            "description": item.description,
            "source": item.source,
            "created_at": item.created_at,
        }
        for item in db.scalars(
            select(EvaluationDataset).order_by(EvaluationDataset.created_at.desc())
        ).all()
    ]


@router.get("/admin/evaluations/runs")
def admin_evaluation_runs(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        run_response(item)
        for item in db.scalars(
            select(EvaluationRun).order_by(EvaluationRun.started_at.desc()).limit(100)
        ).all()
    ]


@router.post("/admin/evaluations/runs")
def admin_run_evaluation(
    payload: EvaluationRunRequest,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> dict:
    run = run_evaluation(
        db,
        dataset_name=payload.dataset,
        mode=payload.mode,
        category=payload.category,
    )
    add_audit_log(
        db,
        action="evaluation.run",
        status=run.status,
        user_id=admin.id,
        resource_type="evaluation_run",
        resource_id=run.id,
        details={"dataset": payload.dataset, "mode": payload.mode, "category": payload.category},
    )
    db.commit()
    return run_response(run)


@router.post("/admin/cleanup")
def admin_cleanup(
    payload: CleanupRequest,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> dict:
    if not payload.dry_run and payload.confirmation != "APPLY_CLEANUP":
        raise HTTPException(status_code=422, detail="执行清理必须确认 APPLY_CLEANUP")
    run = run_cleanup(
        db,
        dry_run=payload.dry_run,
        execution_source=f"admin:{admin.id}",
    )
    add_audit_log(
        db,
        action="cleanup.run",
        status="success" if run.error_count == 0 else "completed_with_errors",
        user_id=admin.id,
        resource_type="cleanup_run",
        resource_id=run.id,
        details={
            "dry_run": payload.dry_run,
            "deleted_count": run.deleted_count,
            "released_bytes": run.released_bytes,
            "error_count": run.error_count,
        },
    )
    db.commit()
    return cleanup_response(run)
