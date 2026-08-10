import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.report import Report
from app.models.report_asset import ReportAsset
from app.models.review_report_asset import ReviewReportAsset
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.core.config import BACKEND_DIR, settings


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
        "workspace_type": workspace.workspace_type,
        "review_template_key": workspace.review_template_key,
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


def _resolve_and_validate_path(storage_path: str, root_dir: Path) -> Path | None:
    """将存储路径解析为绝对路径，校验在安全目录内。

    - 相对路径：解析到 root_dir 内部
    - 绝对路径：仅当解析后位于 root_dir 内部才接受
    - 拒绝 .. 穿越
    - 拒绝根目录外路径
    - 拒绝根目录本身
    - 拒绝符号链接逃逸（resolve 展开符号链接后用 relative_to 校验）
    """
    candidate = Path(storage_path)
    if ".." in candidate.parts:
        return None
    root = root_dir.resolve()
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    # 拒绝存储根目录本身，避免将根目录加入清理计划
    if resolved == root:
        return None
    return resolved


def _resolve_upload_path(storage_path: str) -> Path | None:
    from app.services.file_service import _resolve_upload_dir
    return _resolve_and_validate_path(storage_path, _resolve_upload_dir())


def _resolve_report_path(storage_path: str) -> Path | None:
    root = Path(settings.report_dir)
    if not root.is_absolute():
        root = BACKEND_DIR / root
    return _resolve_and_validate_path(storage_path, root)


def _remove_file_safe(path: Path) -> str | None:
    """安全删除单文件，返回 None 表示成功，否则返回固定安全错误信息（不含路径）。

    - 仅删除普通文件，拒绝目录/符号链接等非普通文件
    - 不执行递归删除
    """
    try:
        if not path.exists():
            return None  # 幂等：已不存在
        if not path.is_file():
            return "磁盘文件清理失败"  # 目录或非普通文件，拒绝操作
        os.remove(path)
    except OSError:
        return "磁盘文件清理失败"
    return None


def permanent_delete_workspace(
    db: Session,
    *,
    workspace: Workspace,
    user_id: int,
) -> dict[str, Any]:
    """永久删除工作区及其全部关联数据。

    两阶段设计：
    1. 在 DB 事务内完成所有数据库删除和配额更新，同时收集待清理的磁盘路径
    2. 调用方先 commit，再按清理计划逐个删除磁盘文件

    返回：
        deleted_counts: 各类型在删除前的记录数
        cleanup_plan:   [(Path, label), ...] 待删除的磁盘文件列表
    """
    from app.models.evidence import Evidence
    from app.models.file_chunk import FileChunk
    from app.models.file_profile import FileProfile
    from app.models.file_processing_run import FileProcessingRun
    from app.models.file_relation import FileRelation
    from app.models.report import Report as ReportModel
    from app.models.review_action import ReviewAction
    from app.models.review_brief import ReviewBrief
    from app.models.review_finding import ReviewFinding
    from app.models.review_report import ReviewReport
    from app.models.review_run import ReviewRun

    ws_id = workspace.id
    counts: dict[str, int] = {}
    cleanup_plan: list[tuple[Path, str]] = []
    skipped_cleanup: list[str] = []

    # ── 统计删除前数量 ──────────────────────────────────────────────
    def _count(model, **filters) -> int:
        stmt = select(func.count()).select_from(model)
        for col_name, val in filters.items():
            stmt = stmt.where(getattr(model, col_name) == val)
        return db.scalar(stmt) or 0

    counts["workspace_files"] = _count(WorkspaceFile, workspace_id=ws_id)
    counts["tasks"] = _count(Task, workspace_id=ws_id)
    counts["reports"] = _count(ReportModel, workspace_id=ws_id)
    counts["report_assets"] = _count(ReportAsset, workspace_id=ws_id)
    counts["review_briefs"] = _count(ReviewBrief, workspace_id=ws_id)
    counts["review_runs"] = _count(ReviewRun, workspace_id=ws_id)
    counts["review_findings"] = _count(ReviewFinding, workspace_id=ws_id)
    counts["review_reports"] = _count(ReviewReport, workspace_id=ws_id)
    counts["review_report_assets"] = _count(ReviewReportAsset, workspace_id=ws_id)
    counts["review_actions"] = _count(ReviewAction, workspace_id=ws_id)
    counts["evidences"] = _count(Evidence, workspace_id=ws_id)
    counts["file_profiles"] = _count(FileProfile, workspace_id=ws_id)
    counts["file_processing_runs"] = _count(FileProcessingRun, workspace_id=ws_id)
    counts["file_relations"] = _count(FileRelation, workspace_id=ws_id)

    # ── 收集 WorkspaceFile → File 映射（在级联删除前） ──────────────
    wf_rows = list(db.scalars(
        select(WorkspaceFile).where(WorkspaceFile.workspace_id == ws_id)
    ).all())
    ws_file_ids = [wf.file_id for wf in wf_rows]

    # ── 收集待清理的磁盘路径（仅验证，不执行删除；非法路径记录为警告） ──
    # Task 报告文件
    tasks = list(db.scalars(select(Task).where(Task.workspace_id == ws_id)).all())
    for task in tasks:
        if task.report_path:
            resolved = _resolve_report_path(task.report_path)
            if resolved is not None:
                cleanup_plan.append((resolved, f"task_report:{task.id}"))
            else:
                skipped_cleanup.append(f"task_report:{task.id}")

    # 通用报告资产
    report_assets = list(db.scalars(
        select(ReportAsset).where(ReportAsset.workspace_id == ws_id)
    ).all())
    for asset in report_assets:
        resolved = _resolve_report_path(asset.storage_key)
        if resolved is not None:
            cleanup_plan.append((resolved, f"report_asset:{asset.id}"))
        else:
            skipped_cleanup.append(f"report_asset:{asset.id}")

    # 工程审查报告资产
    review_assets = list(db.scalars(
        select(ReviewReportAsset).where(ReviewReportAsset.workspace_id == ws_id)
    ).all())
    for asset in review_assets:
        resolved = _resolve_report_path(asset.storage_path)
        if resolved is not None:
            cleanup_plan.append((resolved, f"review_report_asset:{asset.id}"))
        else:
            skipped_cleanup.append(f"review_report_asset:{asset.id}")

    # 5. 收集检索索引文件清理路径
    from app.services.engineering_retrieval_service import cleanup_retrieval_index
    for idx_path, idx_label in cleanup_retrieval_index(ws_id):
        cleanup_plan.append((idx_path, idx_label))

    # ── 数据库删除（仍在事务内） ────────────────────────────────────
    # 1. 删除 Task（级联：TaskStep, TaskPlan, TaskEvent, TaskClarification,
    #    ToolCall, AgentRun, ModelUsageRecord）
    for task in tasks:
        db.delete(task)

    # 2. 删除 Evidence（先于 workspace 级联，解除 file_id FK 阻止）
    db.query(Evidence).filter(Evidence.workspace_id == ws_id).delete(
        synchronize_session="fetch"
    )

    # 3. 删除 workspace（级联：WorkspaceFile, FileProfile, FileProcessingRun,
    #    FileRelation, Report, ReportAsset, ReviewBrief, ReviewRun → 级联
    #    ReviewFinding, ReviewAction, ReviewReport, ReviewReportAsset）
    db.delete(workspace)
    db.flush()

    # 4. 处理孤儿 File 及配额回收
    files_deleted = 0
    files_preserved_shared = 0
    for fid in ws_file_ids:
        remaining = db.scalar(
            select(func.count()).select_from(WorkspaceFile).where(
                WorkspaceFile.file_id == fid
            )
        ) or 0
        if remaining > 0:
            files_preserved_shared += 1
            continue

        # 清理 FileChunk
        db.query(FileChunk).filter(FileChunk.file_id == fid).delete(
            synchronize_session="fetch"
        )

        orphan_file = db.get(File, fid)
        if orphan_file is None:
            continue

        # 收集物理文件清理路径
        resolved = _resolve_upload_path(orphan_file.file_path)
        if resolved is not None:
            cleanup_plan.append((resolved, f"upload:{fid}"))
        else:
            skipped_cleanup.append(f"upload:{fid}")

        # 配额回收
        reclaim_bytes = orphan_file.size_bytes or 0
        if reclaim_bytes > 0:
            _reclaim_storage(db, orphan_file.owner_user_id, reclaim_bytes)

        # 删除 File 记录
        db.query(File).filter(File.id == fid).delete(synchronize_session="fetch")
        files_deleted += 1

    counts["files_deleted"] = files_deleted
    counts["files_preserved_shared"] = files_preserved_shared

    return {
        "deleted_counts": counts,
        "cleanup_plan": cleanup_plan,
        "skipped_cleanup": skipped_cleanup,
    }


def _reclaim_storage(db: Session, user_id: int | None, reclaim_bytes: int) -> None:
    """回收用户当日存储用量计数。"""
    if user_id is None or reclaim_bytes <= 0:
        return
    from datetime import date
    from app.models.usage import UsageCounter
    today = date.today()
    counter = db.scalar(
        select(UsageCounter).where(
            UsageCounter.user_id == user_id,
            UsageCounter.usage_date == today,
        )
    )
    if counter is not None:
        counter.file_storage_bytes = max(0, (counter.file_storage_bytes or 0) - reclaim_bytes)
