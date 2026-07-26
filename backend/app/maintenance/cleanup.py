import argparse
import json
from datetime import datetime, timedelta
from app.core.timeutils import utcnow
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, settings
from app.db.session import SessionLocal
from app.models.agent_run import AgentRun
from app.models.auth_session import AuthSession
from app.models.file import File
from app.models.operations import CleanupRun
from app.models.password_reset_request import PasswordResetRequest
from app.models.report import Report
from app.models.report_asset import ReportAsset
from app.models.task import Task
from app.models.task_event import TaskEvent
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.services.report_version_service import ReportVersionError, resolve_asset_path


def run_cleanup(
    db: Session,
    *,
    dry_run: bool = True,
    execution_source: str = "cli",
    now: datetime | None = None,
) -> CleanupRun:
    now = now or utcnow()
    run = CleanupRun(
        cleanup_type="retention_and_orphans",
        dry_run=int(dry_run),
        execution_source=execution_source,
    )
    db.add(run)
    db.flush()
    details: dict[str, dict[str, int]] = {}
    scanned = deleted = released = errors = 0

    def process_rows(name: str, rows: list, delete_row=True) -> None:
        nonlocal scanned, deleted, errors
        scanned += len(rows)
        count = 0
        for row in rows:
            try:
                if not dry_run and delete_row:
                    db.delete(row)
                count += 1
            except Exception:
                errors += 1
        deleted += count if not dry_run else 0
        details[name] = {"scanned": len(rows), "deleted": count if not dry_run else 0}

    expired_sessions = list(
        db.scalars(
            select(AuthSession).where(
                AuthSession.expires_at
                < now - timedelta(days=max(0, settings.session_retention_days))
            )
        ).all()
    )
    revoked_sessions = list(
        db.scalars(
            select(AuthSession).where(
                AuthSession.revoked_at.is_not(None),
                AuthSession.revoked_at
                < now - timedelta(days=max(0, settings.revoked_session_retention_days)),
            )
        ).all()
    )
    session_by_id = {item.id: item for item in [*expired_sessions, *revoked_sessions]}
    process_rows("sessions", list(session_by_id.values()))
    process_rows(
        "password_reset_requests",
        list(
            db.scalars(
                select(PasswordResetRequest).where(
                    PasswordResetRequest.requested_at
                    < now - timedelta(days=max(0, settings.password_reset_retention_days))
                )
            ).all()
        ),
    )
    process_rows(
        "task_events",
        list(
            db.scalars(
                select(TaskEvent).where(
                    TaskEvent.task_id.in_(
                        select(Task.id).where(
                            Task.status.in_(
                                ["completed", "completed_with_warnings", "failed", "cancelled"]
                            )
                        )
                    ),
                    TaskEvent.created_at
                    < now - timedelta(days=max(0, settings.task_event_retention_days))
                )
            ).all()
        ),
    )
    process_rows(
        "agent_runs",
        list(
            db.scalars(
                select(AgentRun).where(
                    AgentRun.task_id.in_(
                        select(Task.id).where(
                            Task.status.in_(
                                ["completed", "completed_with_warnings", "failed", "cancelled"]
                            )
                        )
                    ),
                    AgentRun.created_at
                    < now - timedelta(days=max(0, settings.agent_run_retention_days))
                )
            ).all()
        ),
    )

    superseded_assets = list(
        db.scalars(
            select(ReportAsset)
            .join(Report, Report.id == ReportAsset.report_id)
            .where(
                ReportAsset.status == "superseded",
                ReportAsset.deleted_at.is_(None),
                ReportAsset.created_at
                < now - timedelta(days=max(0, settings.superseded_asset_retention_days)),
            )
        ).all()
    )
    scanned += len(superseded_assets)
    asset_deleted = 0
    for asset in superseded_assets:
        try:
            report = db.get(Report, asset.report_id)
            if report is None or report.status not in {"superseded", "failed"}:
                continue
            path = resolve_asset_path(asset)
            size = path.stat().st_size if path.is_file() else 0
            if not dry_run:
                if path.is_file():
                    path.unlink()
                asset.status = "deleted"
                asset.deleted_at = now
                released += size
                asset_deleted += 1
        except Exception:
            errors += 1
    deleted += asset_deleted
    details["superseded_report_assets"] = {
        "scanned": len(superseded_assets),
        "deleted": asset_deleted,
    }

    failed_files = list(
        db.scalars(
            select(File).where(
                File.status.in_(["failed", "upload_failed"]),
                File.created_at < now - timedelta(days=1),
                ~select(WorkspaceFile.id)
                .where(WorkspaceFile.file_id == File.id)
                .exists(),
            )
        ).all()
    )
    scanned += len(failed_files)
    failed_deleted = 0
    for file_record in failed_files:
        try:
            path = Path(file_record.file_path).resolve()
            upload_root = _path(settings.upload_dir).resolve()
            if upload_root not in path.parents:
                continue
            size = path.stat().st_size if path.is_file() else 0
            if not dry_run:
                if path.is_file():
                    path.unlink()
                db.delete(file_record)
                released += size
                failed_deleted += 1
        except Exception:
            errors += 1
    deleted += failed_deleted
    details["failed_uploads"] = {"scanned": len(failed_files), "deleted": failed_deleted}

    workspaces = list(
        db.scalars(
            select(Workspace).where(
                Workspace.deleted_at.is_not(None),
                Workspace.deleted_at
                < now - timedelta(days=max(0, settings.workspace_delete_grace_days)),
            )
        ).all()
    )
    scanned += len(workspaces)
    workspace_deleted = 0
    for workspace in workspaces:
        try:
            associations = list(
                db.scalars(
                    select(WorkspaceFile).where(WorkspaceFile.workspace_id == workspace.id)
                ).all()
            )
            for association in associations:
                other_refs = db.scalar(
                    select(func.count(WorkspaceFile.id)).where(
                        WorkspaceFile.file_id == association.file_id,
                        WorkspaceFile.workspace_id != workspace.id,
                    )
                ) or 0
                file_record = db.get(File, association.file_id)
                if file_record and not other_refs:
                    file_path = Path(file_record.file_path).resolve()
                    upload_root = _path(settings.upload_dir).resolve()
                    if upload_root in file_path.parents and file_path.is_file() and not dry_run:
                        released += file_path.stat().st_size
                        file_path.unlink()
                    if not dry_run:
                        db.delete(file_record)
            report_assets = list(
                db.scalars(
                    select(ReportAsset).where(ReportAsset.workspace_id == workspace.id)
                ).all()
            )
            for asset in report_assets:
                path = resolve_asset_path(asset)
                if path.is_file() and not dry_run:
                    released += path.stat().st_size
                    path.unlink()
            if not dry_run:
                for task in db.scalars(
                    select(Task).where(Task.workspace_id == workspace.id)
                ).all():
                    db.delete(task)
                db.delete(workspace)
                workspace_deleted += 1
        except (Exception, ReportVersionError):
            errors += 1
    deleted += workspace_deleted
    details["soft_deleted_workspaces"] = {
        "scanned": len(workspaces),
        "deleted": workspace_deleted,
    }

    run.scanned_count = scanned
    run.deleted_count = deleted
    run.released_bytes = released
    run.error_count = errors
    run.details_json = json.dumps(details, ensure_ascii=False)
    run.completed_at = utcnow()
    db.commit()
    db.refresh(run)
    return run


def cleanup_response(run: CleanupRun) -> dict:
    return {
        "id": run.id,
        "dry_run": bool(run.dry_run),
        "scanned_count": run.scanned_count,
        "deleted_count": run.deleted_count,
        "released_bytes": run.released_bytes,
        "error_count": run.error_count,
        "details": json.loads(run.details_json or "{}"),
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else BACKEND_DIR / path


def main() -> int:
    parser = argparse.ArgumentParser(description="执行 InsightFlow 保留期与孤立资源清理")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args()
    dry_run = not args.apply
    if args.apply and args.confirm != "APPLY_CLEANUP":
        parser.error("--apply 必须同时提供 --confirm APPLY_CLEANUP")
    with SessionLocal() as db:
        print(cleanup_response(run_cleanup(db, dry_run=dry_run, execution_source="cli")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
