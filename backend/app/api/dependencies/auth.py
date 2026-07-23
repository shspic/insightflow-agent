import hmac
from datetime import datetime, timedelta

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.auth_session import AuthSession
from app.models.user import User
from app.services.security_service import hash_token, verify_public_csrf_token


def _auth_error(detail: str = "身份认证已失效") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    raw_token = request.cookies.get(settings.auth_cookie_name)
    if not raw_token:
        raise _auth_error()
    now = datetime.utcnow()
    session_record = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_token(raw_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
    )
    if session_record is None:
        raise _auth_error()
    user = db.scalar(
        select(User).where(
            User.id == session_record.user_id,
            User.status == "active",
        )
    )
    if user is None:
        session_record.revoked_at = now
        db.commit()
        raise _auth_error()
    if (
        session_record.last_seen_at is None
        or now - session_record.last_seen_at
        >= timedelta(seconds=settings.session_last_seen_interval_seconds)
    ):
        session_record.last_seen_at = now
        db.commit()
    request.state.auth_session = session_record
    request.state.current_user = user
    return user


def require_active_user(user: User = Depends(get_current_user)) -> User:
    return user


def require_password_changed(user: User = Depends(require_active_user)) -> User:
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PASSWORD_CHANGE_REQUIRED", "message": "必须先修改密码"},
        )
    return user


def require_admin(user: User = Depends(require_password_changed)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def require_public_csrf(
    csrf_cookie: str | None = Cookie(default=None, alias=settings.csrf_cookie_name),
    csrf_header: str | None = Header(default=None, alias=settings.csrf_header_name),
) -> None:
    if (
        not csrf_cookie
        or not csrf_header
        or not hmac.compare_digest(csrf_cookie, csrf_header)
        or not verify_public_csrf_token(csrf_cookie)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF 校验失败")


def require_session_csrf(
    request: Request,
    user: User = Depends(get_current_user),
    csrf_cookie: str | None = Cookie(default=None, alias=settings.csrf_cookie_name),
    csrf_header: str | None = Header(default=None, alias=settings.csrf_header_name),
) -> User:
    session_record: AuthSession = request.state.auth_session
    if (
        not csrf_cookie
        or not csrf_header
        or not hmac.compare_digest(csrf_cookie, csrf_header)
        or not session_record.csrf_token_hash
        or not hmac.compare_digest(hash_token(csrf_cookie), session_record.csrf_token_hash)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF 校验失败")
    return user


def require_password_changed_csrf(user: User = Depends(require_session_csrf)) -> User:
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PASSWORD_CHANGE_REQUIRED", "message": "必须先修改密码"},
        )
    return user


def require_admin_csrf(user: User = Depends(require_password_changed_csrf)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user
