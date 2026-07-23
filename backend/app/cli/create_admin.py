import argparse
import getpass
import os
import sys
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.user import User
from app.services.audit_service import add_audit_log
from app.services.auth_service import revoke_all_user_sessions
from app.services.security_service import hash_password, validate_username


def create_or_update_admin(
    db: Session,
    *,
    username: str,
    password: str,
    update_password: bool = False,
) -> User:
    normalized = validate_username(username)
    existing = db.scalar(select(User).where(User.username == normalized))
    if existing is not None and not update_password:
        raise ValueError("账号已存在；如需更新密码，请显式使用 --update-password")
    if existing is not None and existing.role != "admin":
        raise ValueError("已存在同名普通用户，不能通过此命令提升权限")

    now = datetime.utcnow()
    if existing is None:
        admin = User(
            username=normalized,
            password_hash=hash_password(password),
            role="admin",
            status="active",
            must_change_password=False,
            password_changed_at=now,
        )
        db.add(admin)
        db.flush()
        action = "admin.initialize"
    else:
        admin = existing
        admin.password_hash = hash_password(password)
        admin.password_changed_at = now
        admin.must_change_password = False
        revoke_all_user_sessions(db, admin.id)
        action = "admin.update_password"

    add_audit_log(
        db,
        user_id=admin.id,
        action=action,
        resource_type="user",
        resource_id=admin.id,
        status="success",
        details={"source": "create_admin_cli"},
    )
    db.commit()
    db.refresh(admin)
    return admin


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安全创建 InsightFlow 管理员")
    parser.add_argument("--username", help="管理员账号；未提供时交互输入")
    parser.add_argument(
        "--update-password",
        action="store_true",
        help="显式更新已存在管理员的密码",
    )
    parser.add_argument("--yes", action="store_true", help="确认执行密码更新")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    username = args.username or os.getenv("ADMIN_USERNAME") or input("管理员账号: ").strip()
    password = os.getenv("ADMIN_PASSWORD")
    if password is None:
        password = getpass.getpass("管理员密码: ")
        password_confirm = getpass.getpass("确认管理员密码: ")
        if password != password_confirm:
            print("两次输入的密码不一致", file=sys.stderr)
            return 2
    if args.update_password and not args.yes:
        confirmation = input("确认更新该管理员密码？输入 yes 继续: ").strip().lower()
        if confirmation != "yes":
            print("操作已取消")
            return 1

    db = SessionLocal()
    try:
        admin = create_or_update_admin(
            db,
            username=username,
            password=password,
            update_password=args.update_password,
        )
    except ValueError as exc:
        db.rollback()
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        db.close()
    print(f"管理员账号已安全写入：{admin.username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
