import argparse
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.file import File
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.services.audit_service import add_audit_log
from app.services.security_service import normalize_username


LEGACY_WORKSPACE_NAME = "旧版数据"


@dataclass
class ClaimResult:
    file_count: int
    task_count: int
    association_count: int
    applied: bool
    workspace_id: int | None


def claim_legacy_data(
    db: Session,
    *,
    username: str,
    apply: bool = False,
) -> ClaimResult:
    user = db.scalar(select(User).where(User.username == normalize_username(username)))
    if user is None:
        raise ValueError("目标用户不存在")
    legacy_files = db.scalars(select(File).where(File.owner_user_id.is_(None))).all()
    legacy_tasks = db.scalars(select(Task).where(Task.owner_user_id.is_(None))).all()
    existing_workspace = db.scalar(
        select(Workspace).where(
            Workspace.owner_user_id == user.id,
            Workspace.name == LEGACY_WORKSPACE_NAME,
        )
    )
    existing_file_ids: set[int] = set()
    if existing_workspace is not None:
        existing_file_ids = set(
            db.scalars(
                select(WorkspaceFile.file_id).where(
                    WorkspaceFile.workspace_id == existing_workspace.id
                )
            ).all()
        )
    association_count = sum(1 for item in legacy_files if item.id not in existing_file_ids)
    if not apply:
        return ClaimResult(
            file_count=len(legacy_files),
            task_count=len(legacy_tasks),
            association_count=association_count,
            applied=False,
            workspace_id=existing_workspace.id if existing_workspace else None,
        )

    workspace = existing_workspace
    if workspace is None:
        workspace = Workspace(
            owner_user_id=user.id,
            name=LEGACY_WORKSPACE_NAME,
            description="通过旧数据认领工具创建",
            status="active",
        )
        db.add(workspace)
        db.flush()

    for file_record in legacy_files:
        file_record.owner_user_id = user.id
        if file_record.id not in existing_file_ids:
            db.add(WorkspaceFile(workspace_id=workspace.id, file_id=file_record.id))
    for task in legacy_tasks:
        task.owner_user_id = user.id
        task.workspace_id = workspace.id

    add_audit_log(
        db,
        user_id=user.id,
        action="legacy_data.claim",
        resource_type="workspace",
        resource_id=workspace.id,
        status="success",
        details={
            "file_count": len(legacy_files),
            "task_count": len(legacy_tasks),
            "association_count": association_count,
            "source": "claim_legacy_data_cli",
        },
    )
    db.commit()
    return ClaimResult(
        file_count=len(legacy_files),
        task_count=len(legacy_tasks),
        association_count=association_count,
        applied=True,
        workspace_id=workspace.id,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="预览或认领 V1 无归属数据")
    parser.add_argument("--username", required=True, help="目标用户账号")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写入（默认）")
    parser.add_argument("--apply", action="store_true", help="显式执行认领")
    parser.add_argument("--yes", action="store_true", help="跳过交互确认")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.apply and args.dry_run:
        print("--dry-run 与 --apply 不能同时使用", file=sys.stderr)
        return 2
    db = SessionLocal()
    try:
        preview = claim_legacy_data(db, username=args.username, apply=False)
        print(
            f"待认领：文件 {preview.file_count}，任务 {preview.task_count}，"
            f"需新增关联 {preview.association_count}"
        )
        if not args.apply:
            print("当前为 dry-run，未修改数据库")
            return 0
        if not args.yes:
            confirmation = input("确认执行认领？输入 yes 继续: ").strip().lower()
            if confirmation != "yes":
                print("操作已取消")
                return 1
        result = claim_legacy_data(db, username=args.username, apply=True)
        print(
            f"认领完成：文件 {result.file_count}，任务 {result.task_count}，"
            f"新增关联 {result.association_count}"
        )
        return 0
    except ValueError as exc:
        db.rollback()
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
