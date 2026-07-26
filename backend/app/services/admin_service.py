import json
from datetime import datetime
from app.core.timeutils import utcnow

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auth_session import AuthSession
from app.models.invite_code import InviteCode
from app.models.password_reset_request import PasswordResetRequest
from app.models.user import User
from app.services.audit_service import add_audit_log
from app.services.auth_service import revoke_all_user_sessions
from app.services.security_service import (
    generate_invite_code,
    generate_temporary_password,
    hash_password,
    invite_code_hash,
    invite_code_hint,
    sanitize_details,
    validate_invite_code,
)


class AdminServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _utcnow() -> datetime:
    return utcnow()


def effective_invite_status(invite: InviteCode) -> str:
    now = _utcnow()
    if invite.status == "disabled":
        return "disabled"
    if invite.expires_at is not None and invite.expires_at <= now:
        return "expired"
    if invite.max_uses is not None and invite.used_count >= invite.max_uses:
        return "exhausted"
    return "active"


def create_invite(
    db: Session,
    *,
    admin: User,
    code: str | None,
    max_uses: int | None,
    expires_at: datetime | None,
    ip_address: str | None,
) -> tuple[InviteCode, str]:
    if expires_at is not None and expires_at <= _utcnow():
        raise AdminServiceError("过期时间必须晚于当前时间")
    try:
        raw_code = generate_invite_code() if code is None else validate_invite_code(code)
    except ValueError as exc:
        raise AdminServiceError(str(exc), 422) from exc
    code_digest = invite_code_hash(raw_code)
    if db.scalar(select(InviteCode.id).where(InviteCode.code_hash == code_digest)) is not None:
        raise AdminServiceError("邀请码已存在", 409)
    invite = InviteCode(
        code_hash=code_digest,
        code_hint=invite_code_hint(raw_code),
        status="active",
        max_uses=max_uses,
        used_count=0,
        expires_at=expires_at,
        created_by_user_id=admin.id,
    )
    db.add(invite)
    db.flush()
    add_audit_log(
        db,
        user_id=admin.id,
        action="admin.invite.create",
        resource_type="invite_code",
        resource_id=invite.id,
        status="success",
        details={"code_hint": invite.code_hint, "max_uses": max_uses},
        ip_address=ip_address,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AdminServiceError("邀请码已存在", 409) from exc
    db.refresh(invite)
    return invite, raw_code


def update_invite(
    db: Session,
    *,
    invite: InviteCode,
    admin: User,
    new_status: str | None,
    max_uses: int | None,
    expires_at: datetime | None,
    fields_set: set[str],
    ip_address: str | None,
) -> InviteCode:
    if "max_uses" in fields_set:
        if max_uses is not None and max_uses < invite.used_count:
            raise AdminServiceError("最大使用次数不能小于已使用次数")
        invite.max_uses = max_uses
    if "expires_at" in fields_set:
        invite.expires_at = expires_at
    if new_status is not None:
        if new_status not in {"active", "disabled"}:
            raise AdminServiceError("状态只能是 active 或 disabled")
        invite.status = new_status
    if invite.status == "active":
        invite.status = effective_invite_status(invite)
    invite.updated_at = _utcnow()
    add_audit_log(
        db,
        user_id=admin.id,
        action="admin.invite.update",
        resource_type="invite_code",
        resource_id=invite.id,
        status="success",
        details={"status": invite.status, "max_uses": invite.max_uses},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(invite)
    return invite


def rotate_invite(
    db: Session,
    *,
    invite: InviteCode,
    admin: User,
    ip_address: str | None,
) -> tuple[InviteCode, str]:
    raw_code = generate_invite_code()
    invite.code_hash = invite_code_hash(raw_code)
    invite.code_hint = invite_code_hint(raw_code)
    invite.used_count = 0
    invite.status = "active"
    invite.updated_at = _utcnow()
    add_audit_log(
        db,
        user_id=admin.id,
        action="admin.invite.rotate",
        resource_type="invite_code",
        resource_id=invite.id,
        status="success",
        details={"code_hint": invite.code_hint},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(invite)
    return invite, raw_code


def reject_reset_request(
    db: Session,
    *,
    reset_request: PasswordResetRequest,
    admin: User,
    admin_note: str | None,
    ip_address: str | None,
) -> PasswordResetRequest:
    if reset_request.status != "pending":
        raise AdminServiceError("只能拒绝 pending 状态的申请", 409)
    reset_request.status = "rejected"
    reset_request.admin_note = admin_note
    reset_request.handled_at = _utcnow()
    reset_request.handled_by_user_id = admin.id
    add_audit_log(
        db,
        user_id=admin.id,
        action="admin.password_reset.reject",
        resource_type="password_reset_request",
        resource_id=reset_request.id,
        status="success",
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(reset_request)
    return reset_request


def issue_temporary_password(
    db: Session,
    *,
    reset_request: PasswordResetRequest,
    admin: User,
    admin_note: str | None,
    ip_address: str | None,
) -> tuple[PasswordResetRequest, str]:
    if reset_request.status != "pending":
        raise AdminServiceError("只能处理 pending 状态的申请", 409)
    user = db.scalar(select(User).where(User.id == reset_request.user_id))
    if user is None or user.status != "active":
        raise AdminServiceError("目标用户当前不可处理", 409)

    temporary_password = generate_temporary_password()
    user.password_hash = hash_password(temporary_password)
    user.must_change_password = True
    user.password_changed_at = _utcnow()
    revoke_all_user_sessions(db, user.id)
    reset_request.status = "approved"
    reset_request.admin_note = admin_note
    reset_request.handled_at = _utcnow()
    reset_request.handled_by_user_id = admin.id
    add_audit_log(
        db,
        user_id=admin.id,
        action="admin.password_reset.issue_temporary_password",
        resource_type="password_reset_request",
        resource_id=reset_request.id,
        status="success",
        details={"target_user_id": user.id},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(reset_request)
    return reset_request, temporary_password


def set_user_status(
    db: Session,
    *,
    target: User,
    admin: User,
    new_status: str,
    ip_address: str | None,
) -> User:
    if target.id == admin.id:
        raise AdminServiceError("不能修改自己的状态", 409)
    if target.role == "admin":
        raise AdminServiceError("此接口只允许修改普通用户状态", 403)
    if new_status not in {"active", "disabled"}:
        raise AdminServiceError("状态只能是 active 或 disabled")
    target.status = new_status
    target.updated_at = _utcnow()
    if new_status == "disabled":
        revoke_all_user_sessions(db, target.id)
    add_audit_log(
        db,
        user_id=admin.id,
        action="admin.user.status",
        resource_type="user",
        resource_id=target.id,
        status="success",
        details={"new_status": new_status},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(target)
    return target


def safe_audit_details(details_json: str | None) -> dict | None:
    if not details_json:
        return None
    try:
        value = json.loads(details_json)
    except json.JSONDecodeError:
        return {"message": "详情格式不可解析"}
    sanitized = sanitize_details(value)
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}
