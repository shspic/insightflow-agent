from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_password_changed, require_password_changed_csrf
from app.db.session import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.auth import MessageResponse
from app.schemas.workspace import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate
from app.services.audit_service import add_audit_log
from app.services.quota_service import QuotaExceeded, check_workspace_creation
from app.services.workspace_service import get_owned_workspace, workspace_response


router = APIRouter(prefix="/api/v2/workspaces", tags=["v2-workspaces"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    request: Request,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict:
    try:
        check_workspace_creation(db, user)
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.detail()) from exc
    workspace = Workspace(
        owner_user_id=user.id,
        name=payload.name.strip(),
        description=payload.description,
        status="active",
    )
    db.add(workspace)
    db.flush()
    add_audit_log(
        db,
        user_id=user.id,
        action="workspace.create",
        resource_type="workspace",
        resource_id=workspace.id,
        status="success",
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(workspace)
    return workspace_response(db, workspace)


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(
    include_deleted: bool = Query(default=False),
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = select(Workspace).where(Workspace.owner_user_id == user.id)
    if not include_deleted:
        statement = statement.where(Workspace.deleted_at.is_(None))
    workspaces = db.scalars(statement.order_by(Workspace.updated_at.desc())).all()
    return [workspace_response(db, workspace) for workspace in workspaces]


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(
    workspace_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict:
    workspace = get_owned_workspace(
        db,
        workspace_id=workspace_id,
        owner_user_id=user.id,
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return workspace_response(db, workspace)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    request: Request,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict:
    workspace = get_owned_workspace(
        db,
        workspace_id=workspace_id,
        owner_user_id=user.id,
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    if payload.name is not None:
        workspace.name = payload.name.strip()
    if "description" in payload.model_fields_set:
        workspace.description = payload.description
    if payload.status is not None:
        if payload.status not in {"active", "archived"}:
            raise HTTPException(status_code=400, detail="状态只能是 active 或 archived")
        workspace.status = payload.status
    workspace.updated_at = datetime.utcnow()
    add_audit_log(
        db,
        user_id=user.id,
        action="workspace.update",
        resource_type="workspace",
        resource_id=workspace.id,
        status="success",
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(workspace)
    return workspace_response(db, workspace)


@router.delete("/{workspace_id}", response_model=MessageResponse)
def delete_workspace(
    workspace_id: int,
    request: Request,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> MessageResponse:
    workspace = get_owned_workspace(
        db,
        workspace_id=workspace_id,
        owner_user_id=user.id,
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    workspace.deleted_at = datetime.utcnow()
    workspace.updated_at = datetime.utcnow()
    add_audit_log(
        db,
        user_id=user.id,
        action="workspace.delete",
        resource_type="workspace",
        resource_id=workspace.id,
        status="success",
        ip_address=_client_ip(request),
    )
    db.commit()
    return MessageResponse(message="工作区已移入已删除列表")


@router.post("/{workspace_id}/restore", response_model=WorkspaceResponse)
def restore_workspace(
    workspace_id: int,
    request: Request,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict:
    workspace = get_owned_workspace(
        db,
        workspace_id=workspace_id,
        owner_user_id=user.id,
        include_deleted=True,
    )
    if workspace is None or workspace.deleted_at is None:
        raise HTTPException(status_code=404, detail="已删除工作区不存在")
    workspace.deleted_at = None
    workspace.updated_at = datetime.utcnow()
    add_audit_log(
        db,
        user_id=user.id,
        action="workspace.restore",
        resource_type="workspace",
        resource_id=workspace.id,
        status="success",
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(workspace)
    return workspace_response(db, workspace)
