from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import (
    get_current_user,
    require_password_changed_csrf,
    require_public_csrf,
    require_session_csrf,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.auth_session import AuthSession
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    CsrfResponse,
    LoginRequest,
    MessageResponse,
    PasswordResetRequestCreate,
    RegisterRequest,
    UserResponse,
)
from app.services.audit_service import add_audit_log
from app.services.auth_service import (
    AuthServiceError,
    change_user_password,
    create_password_reset_request,
    login_user,
    register_user,
    revoke_all_user_sessions,
    revoke_session,
)
from app.services.rate_limit_service import RateLimitExceededError
from app.services.rate_limit_service import ensure_not_blocked, record_attempt
from app.services.security_service import create_public_csrf_token, generate_csrf_token, hash_token
from sqlalchemy import select
from datetime import datetime
from app.core.timeutils import utcnow


router = APIRouter(prefix="/api/v2/auth", tags=["v2-auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_csrf_cookie(response: Response, csrf_token: str) -> None:
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=settings.session_ttl_seconds,
        secure=settings.auth_cookie_secure,
        httponly=False,
        samesite=settings.auth_cookie_samesite,
        domain=settings.auth_cookie_domain,
        path="/",
    )


def _set_session_cookies(response: Response, raw_token: str, csrf_token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=raw_token,
        max_age=settings.session_ttl_seconds,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
        domain=settings.auth_cookie_domain,
        path="/",
    )
    _set_csrf_cookie(response, csrf_token)


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        settings.auth_cookie_name,
        domain=settings.auth_cookie_domain,
        path="/",
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        domain=settings.auth_cookie_domain,
        path="/",
    )


@router.get("/csrf", response_model=CsrfResponse)
def csrf_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> CsrfResponse:
    origin = request.headers.get("origin")
    if origin and origin not in settings.cors_origins:
        raise HTTPException(status_code=403, detail="不允许的请求来源")
    token = create_public_csrf_token()
    raw_session = request.cookies.get(settings.auth_cookie_name)
    if raw_session:
        session_record = db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == hash_token(raw_session),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utcnow(),
            )
        )
        if session_record is not None:
            token = generate_csrf_token()
            session_record.csrf_token_hash = hash_token(token)
            db.commit()
    _set_csrf_cookie(response, token)
    return CsrfResponse(message="CSRF Token 已设置", csrf_token=token)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_public_csrf)],
)
def register(
    payload: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    try:
        ip_scope = _client_ip(request) or "unknown"
        ensure_not_blocked(db, "register_ip", ip_scope)
        record_attempt(db, "register_ip", ip_scope, settings.registration_ip_limit)
        db.commit()
        return register_user(
            db,
            username=payload.username,
            password=payload.password,
            password_confirm=payload.password_confirm,
            invite_code=payload.invite_code,
            ip_address=_client_ip(request),
        )
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="注册尝试过于频繁，请稍后重试",
        ) from exc
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post(
    "/login",
    response_model=AuthResponse,
    dependencies=[Depends(require_public_csrf)],
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthResponse:
    try:
        user, created_session = login_user(
            db,
            username=payload.username,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录尝试过于频繁，请稍后重试",
        ) from exc
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    _set_session_cookies(response, created_session.raw_token, created_session.csrf_token)
    return AuthResponse(
        user=UserResponse.model_validate(user),
        must_change_password=user.must_change_password,
        csrf_token=created_session.csrf_token,
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    response: Response,
    user: User = Depends(require_session_csrf),
    db: Session = Depends(get_db),
) -> MessageResponse:
    session_record: AuthSession = request.state.auth_session
    revoke_session(
        db,
        session_record,
        user_id=user.id,
        ip_address=_client_ip(request),
    )
    _clear_auth_cookies(response)
    return MessageResponse(message="已退出登录")


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/change-password", response_model=AuthResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    user: User = Depends(require_session_csrf),
    db: Session = Depends(get_db),
) -> AuthResponse:
    try:
        created_session = change_user_password(
            db,
            user=user,
            current_password=payload.current_password,
            new_password=payload.new_password,
            new_password_confirm=payload.new_password_confirm,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    _set_session_cookies(response, created_session.raw_token, created_session.csrf_token)
    return AuthResponse(
        user=UserResponse.model_validate(user),
        must_change_password=False,
        csrf_token=created_session.csrf_token,
    )


@router.post("/revoke-sessions", response_model=MessageResponse)
def revoke_sessions(
    request: Request,
    response: Response,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> MessageResponse:
    revoked_count = revoke_all_user_sessions(db, user.id)
    add_audit_log(
        db,
        user_id=user.id,
        action="auth.revoke_sessions",
        resource_type="user",
        resource_id=user.id,
        status="success",
        details={"revoked_count": revoked_count},
        ip_address=_client_ip(request),
    )
    db.commit()
    _clear_auth_cookies(response)
    return MessageResponse(message="所有会话已撤销")


@router.post(
    "/password-reset-requests",
    response_model=MessageResponse,
    dependencies=[Depends(require_public_csrf)],
)
def request_password_reset(
    payload: PasswordResetRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> MessageResponse:
    try:
        create_password_reset_request(
            db,
            username=payload.username,
            request_note=payload.request_note,
            ip_address=_client_ip(request),
        )
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="申请过于频繁，请稍后重试",
        ) from exc
    return MessageResponse(message="申请已提交。如账号存在，管理员将进行处理。")
