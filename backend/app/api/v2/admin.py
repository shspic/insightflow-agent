from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_admin, require_admin_csrf
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.invite_code import InviteCode
from app.models.password_reset_request import PasswordResetRequest
from app.models.task import Task
from app.models.user import User
from app.schemas.admin import (
    AdminNoteRequest,
    AuditLogResponse,
    InviteCodeCreate,
    InviteCodeResponse,
    InviteCodeSecretResponse,
    InviteCodeUpdate,
    PasswordResetAdminResponse,
    TemporaryPasswordResponse,
    UserListItem,
    UserStatusUpdate,
)
from app.services.admin_service import (
    AdminServiceError,
    create_invite,
    effective_invite_status,
    issue_temporary_password,
    reject_reset_request,
    rotate_invite,
    safe_audit_details,
    set_user_status,
    update_invite,
)


router = APIRouter(prefix="/api/v2/admin", tags=["v2-admin"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _invite_response(invite: InviteCode, raw_code: str | None = None):
    payload = InviteCodeResponse.model_validate(invite).model_dump()
    payload["status"] = effective_invite_status(invite)
    if raw_code is not None:
        payload["invite_code"] = raw_code
        return InviteCodeSecretResponse(**payload)
    return InviteCodeResponse(**payload)


def _reset_response(reset_request: PasswordResetRequest) -> PasswordResetAdminResponse:
    return PasswordResetAdminResponse(
        id=reset_request.id,
        user_id=reset_request.user_id,
        username=reset_request.user.username,
        status=reset_request.status,
        request_note=reset_request.request_note,
        admin_note=reset_request.admin_note,
        requested_at=reset_request.requested_at,
        handled_at=reset_request.handled_at,
        handled_by_user_id=reset_request.handled_by_user_id,
    )


@router.post(
    "/invite-codes",
    response_model=InviteCodeSecretResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_invite_code(
    payload: InviteCodeCreate,
    request: Request,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> InviteCodeSecretResponse:
    try:
        invite, raw_code = create_invite(
            db,
            admin=admin,
            max_uses=payload.max_uses,
            expires_at=payload.expires_at,
            ip_address=_client_ip(request),
        )
    except AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _invite_response(invite, raw_code)


@router.get("/invite-codes", response_model=list[InviteCodeResponse])
def list_invite_codes(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[InviteCodeResponse]:
    invites = db.scalars(select(InviteCode).order_by(InviteCode.created_at.desc())).all()
    return [_invite_response(invite) for invite in invites]


@router.patch("/invite-codes/{invite_id}", response_model=InviteCodeResponse)
def patch_invite_code(
    invite_id: int,
    payload: InviteCodeUpdate,
    request: Request,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> InviteCodeResponse:
    invite = db.scalar(select(InviteCode).where(InviteCode.id == invite_id))
    if invite is None:
        raise HTTPException(status_code=404, detail="邀请码记录不存在")
    try:
        invite = update_invite(
            db,
            invite=invite,
            admin=admin,
            new_status=payload.status,
            max_uses=payload.max_uses,
            expires_at=payload.expires_at,
            fields_set=payload.model_fields_set,
            ip_address=_client_ip(request),
        )
    except AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _invite_response(invite)


@router.post("/invite-codes/{invite_id}/rotate", response_model=InviteCodeSecretResponse)
def rotate_invite_code(
    invite_id: int,
    request: Request,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> InviteCodeSecretResponse:
    invite = db.scalar(select(InviteCode).where(InviteCode.id == invite_id))
    if invite is None:
        raise HTTPException(status_code=404, detail="邀请码记录不存在")
    invite, raw_code = rotate_invite(
        db,
        invite=invite,
        admin=admin,
        ip_address=_client_ip(request),
    )
    return _invite_response(invite, raw_code)


@router.get("/password-reset-requests", response_model=list[PasswordResetAdminResponse])
def list_password_reset_requests(
    request_status: str | None = Query(default=None, alias="status"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[PasswordResetAdminResponse]:
    statement = select(PasswordResetRequest).order_by(PasswordResetRequest.requested_at.desc())
    if request_status is not None:
        statement = statement.where(PasswordResetRequest.status == request_status)
    records = db.scalars(statement).all()
    return [_reset_response(record) for record in records]


@router.post(
    "/password-reset-requests/{request_id}/reject",
    response_model=PasswordResetAdminResponse,
)
def reject_password_reset(
    request_id: int,
    payload: AdminNoteRequest,
    request: Request,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> PasswordResetAdminResponse:
    reset_request = db.scalar(
        select(PasswordResetRequest).where(PasswordResetRequest.id == request_id)
    )
    if reset_request is None:
        raise HTTPException(status_code=404, detail="密码重置申请不存在")
    try:
        record = reject_reset_request(
            db,
            reset_request=reset_request,
            admin=admin,
            admin_note=payload.admin_note,
            ip_address=_client_ip(request),
        )
    except AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _reset_response(record)


@router.post(
    "/password-reset-requests/{request_id}/issue-temporary-password",
    response_model=TemporaryPasswordResponse,
)
def issue_reset_temporary_password(
    request_id: int,
    payload: AdminNoteRequest,
    request: Request,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> TemporaryPasswordResponse:
    reset_request = db.scalar(
        select(PasswordResetRequest).where(PasswordResetRequest.id == request_id)
    )
    if reset_request is None:
        raise HTTPException(status_code=404, detail="密码重置申请不存在")
    try:
        record, temporary_password = issue_temporary_password(
            db,
            reset_request=reset_request,
            admin=admin,
            admin_note=payload.admin_note,
            ip_address=_client_ip(request),
        )
    except AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return TemporaryPasswordResponse(
        request=_reset_response(record),
        temporary_password=temporary_password,
    )


@router.get("/users")
def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    total = db.scalar(select(func.count()).select_from(User)) or 0
    records = db.scalars(
        select(User)
        .order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [UserListItem.model_validate(record) for record in records],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.patch("/users/{user_id}/status", response_model=UserListItem)
def patch_user_status(
    user_id: int,
    payload: UserStatusUpdate,
    request: Request,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> User:
    target = db.scalar(select(User).where(User.id == user_id))
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        return set_user_status(
            db,
            target=target,
            admin=admin,
            new_status=payload.status,
            ip_address=_client_ip(request),
        )
    except AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/audit-logs")
def list_audit_logs(
    action: str | None = None,
    audit_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    filters = []
    if action:
        filters.append(AuditLog.action == action)
    if audit_status:
        filters.append(AuditLog.status == audit_status)
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    records = db.scalars(
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [
        AuditLogResponse(
            id=record.id,
            user_id=record.user_id,
            action=record.action,
            resource_type=record.resource_type,
            resource_id=record.resource_id,
            status=record.status,
            details=safe_audit_details(record.details_json),
            created_at=record.created_at,
        )
        for record in records
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/tasks")
def list_task_metadata(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    total = db.scalar(select(func.count()).select_from(Task)) or 0
    records = db.scalars(
        select(Task)
        .order_by(Task.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [
        {
            "id": record.id,
            "owner_user_id": record.owner_user_id,
            "workspace_id": record.workspace_id,
            "task_type": record.task_type,
            "status": record.status,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
        for record in records
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}
