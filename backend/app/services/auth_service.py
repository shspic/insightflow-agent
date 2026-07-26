from dataclasses import dataclass
from datetime import datetime, timedelta
from app.core.timeutils import utcnow

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.auth_session import AuthSession
from app.models.invite_code import InviteCode
from app.models.password_reset_request import PasswordResetRequest
from app.models.user import User
from app.services.audit_service import add_audit_log
from app.services.rate_limit_service import clear_attempts, ensure_not_blocked, record_attempt
from app.services.security_service import (
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_token,
    invite_code_hash,
    normalize_username,
    validate_password,
    validate_username,
    verify_password,
)


class AuthServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass
class CreatedSession:
    raw_token: str
    csrf_token: str
    record: AuthSession


def _utcnow() -> datetime:
    return utcnow()


def _effective_invite_status(invite: InviteCode, now: datetime) -> str:
    if invite.status == "disabled":
        return "disabled"
    if invite.expires_at is not None and invite.expires_at <= now:
        return "expired"
    if invite.max_uses is not None and invite.used_count >= invite.max_uses:
        return "exhausted"
    return "active"


def create_auth_session(
    db: Session,
    user: User,
    *,
    user_agent: str | None,
    ip_address: str | None,
) -> CreatedSession:
    raw_token = generate_session_token()
    csrf_token = generate_csrf_token()
    now = _utcnow()
    record = AuthSession(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        csrf_token_hash=hash_token(csrf_token),
        created_at=now,
        expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
        last_seen_at=now,
        user_agent=(user_agent or "")[:1000] or None,
        ip_address=(ip_address or "")[:64] or None,
    )
    db.add(record)
    db.flush()
    return CreatedSession(raw_token=raw_token, csrf_token=csrf_token, record=record)


def register_user(
    db: Session,
    *,
    username: str,
    password: str,
    password_confirm: str,
    invite_code: str,
    ip_address: str | None,
) -> User:
    if password != password_confirm:
        raise AuthServiceError("两次输入的密码不一致")
    try:
        normalized = validate_username(username)
        validate_password(password)
    except ValueError as exc:
        raise AuthServiceError(str(exc)) from exc

    now = _utcnow()
    digest = invite_code_hash(invite_code)
    invite = db.scalar(select(InviteCode).where(InviteCode.code_hash == digest))
    if invite is None or _effective_invite_status(invite, now) != "active":
        raise AuthServiceError("邀请码无效或不可用")
    if db.scalar(select(User.id).where(User.username == normalized)) is not None:
        raise AuthServiceError("该账号不可用", 409)

    user = User(
        username=normalized,
        password_hash=hash_password(password),
        role="user",
        status="active",
        must_change_password=False,
        password_changed_at=now,
    )
    db.add(user)
    db.flush()

    conditions = [
        InviteCode.id == invite.id,
        InviteCode.status == "active",
    ]
    if invite.expires_at is not None:
        conditions.append(InviteCode.expires_at > now)
    if invite.max_uses is not None:
        conditions.append(InviteCode.used_count < InviteCode.max_uses)
    result = db.execute(
        update(InviteCode)
        .where(*conditions)
        .values(
            used_count=InviteCode.used_count + 1,
            status=case(
                (
                    InviteCode.max_uses.is_not(None)
                    & (InviteCode.used_count + 1 >= InviteCode.max_uses),
                    "exhausted",
                ),
                else_="active",
            ),
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        raise AuthServiceError("邀请码无效或不可用")

    add_audit_log(
        db,
        user_id=user.id,
        action="auth.register",
        resource_type="user",
        resource_id=user.id,
        status="success",
        ip_address=ip_address,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AuthServiceError("该账号不可用", 409) from exc
    db.refresh(user)
    return user


def login_user(
    db: Session,
    *,
    username: str,
    password: str,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[User, CreatedSession]:
    normalized = normalize_username(username)
    ip_scope = ip_address or "unknown"
    ensure_not_blocked(db, "login_account", normalized)
    ensure_not_blocked(db, "login_ip", ip_scope)
    user = db.scalar(select(User).where(User.username == normalized))
    if user is None or user.status != "active" or not verify_password(user.password_hash, password):
        record_attempt(db, "login_account", normalized, settings.login_account_limit)
        record_attempt(db, "login_ip", ip_scope, settings.login_ip_limit)
        add_audit_log(
            db,
            action="auth.login",
            status="failed",
            user_id=user.id if user is not None else None,
            ip_address=ip_address,
        )
        db.commit()
        raise AuthServiceError("账号或密码错误", 401)

    clear_attempts(db, "login_account", normalized)
    clear_attempts(db, "login_ip", ip_scope)
    session = create_auth_session(
        db,
        user,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    user.last_login_at = _utcnow()
    add_audit_log(
        db,
        user_id=user.id,
        action="auth.login",
        resource_type="auth_session",
        resource_id=session.record.id,
        status="success",
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(user)
    return user, session


def revoke_session(
    db: Session,
    session_record: AuthSession,
    *,
    user_id: int,
    ip_address: str | None,
) -> None:
    if session_record.revoked_at is None:
        session_record.revoked_at = _utcnow()
    add_audit_log(
        db,
        user_id=user_id,
        action="auth.logout",
        resource_type="auth_session",
        resource_id=session_record.id,
        status="success",
        ip_address=ip_address,
    )
    db.commit()


def revoke_all_user_sessions(db: Session, user_id: int) -> int:
    now = _utcnow()
    result = db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    return result.rowcount


def change_user_password(
    db: Session,
    *,
    user: User,
    current_password: str,
    new_password: str,
    new_password_confirm: str,
    user_agent: str | None,
    ip_address: str | None,
) -> CreatedSession:
    if not verify_password(user.password_hash, current_password):
        raise AuthServiceError("当前密码错误", 400)
    if new_password != new_password_confirm:
        raise AuthServiceError("两次输入的新密码不一致")
    try:
        validate_password(new_password)
    except ValueError as exc:
        raise AuthServiceError(str(exc)) from exc
    if verify_password(user.password_hash, new_password):
        raise AuthServiceError("新密码不能与当前密码相同")

    now = _utcnow()
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.password_changed_at = now
    revoke_all_user_sessions(db, user.id)
    db.execute(
        update(PasswordResetRequest)
        .where(
            PasswordResetRequest.user_id == user.id,
            PasswordResetRequest.status == "approved",
        )
        .values(status="completed", handled_at=now)
    )
    created_session = create_auth_session(
        db,
        user,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    add_audit_log(
        db,
        user_id=user.id,
        action="auth.change_password",
        resource_type="user",
        resource_id=user.id,
        status="success",
        ip_address=ip_address,
    )
    db.commit()
    return created_session


def create_password_reset_request(
    db: Session,
    *,
    username: str,
    request_note: str | None,
    ip_address: str | None,
) -> None:
    normalized = normalize_username(username)
    ip_scope = ip_address or "unknown"
    ensure_not_blocked(db, "reset_account", normalized)
    ensure_not_blocked(db, "reset_ip", ip_scope)
    record_attempt(db, "reset_account", normalized, settings.reset_request_limit)
    record_attempt(db, "reset_ip", ip_scope, settings.reset_request_limit * 5)

    user = db.scalar(
        select(User).where(
            User.username == normalized,
            User.status == "active",
        )
    )
    if user is not None:
        recent_after = _utcnow() - timedelta(seconds=settings.auth_rate_window_seconds)
        existing = db.scalar(
            select(PasswordResetRequest.id).where(
                PasswordResetRequest.user_id == user.id,
                PasswordResetRequest.status == "pending",
                PasswordResetRequest.requested_at >= recent_after,
            )
        )
        if existing is None:
            db.add(
                PasswordResetRequest(
                    user_id=user.id,
                    status="pending",
                    request_note=request_note,
                )
            )
    add_audit_log(
        db,
        user_id=user.id if user is not None else None,
        action="auth.password_reset.request",
        resource_type="user" if user is not None else None,
        resource_id=user.id if user is not None else None,
        status="accepted",
        ip_address=ip_address,
    )
    db.commit()
