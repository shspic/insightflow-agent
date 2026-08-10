from datetime import datetime
from app.core.timeutils import utcnow

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from typing import Literal
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
from app.services.workspace_service import (
    _remove_file_safe,
    get_owned_workspace,
    permanent_delete_workspace,
    workspace_response,
)
from app.services.engineering_retrieval_service import (
    cleanup_retrieval_index,
    get_index_status,
    rebuild_index,
    search_workspace,
)
from app.retrieval.errors import EngineeringRetrievalError


class DeleteWorkspaceRequest(BaseModel):
    confirmation_name: str


class SearchRetrievalRequest(BaseModel):
    query: str = Field(..., min_length=1, description="检索查询文本")
    top_k: int = Field(default=5, ge=1, le=20, description="返回结果数 1-20")
    retrieval_mode: Literal["bm25", "dense", "hybrid_rrf"] = "hybrid_rrf"

    @field_validator("query")
    @classmethod
    def query_must_be_non_empty_after_strip(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("查询不能为空")
        return stripped


class BuildIndexRequest(BaseModel):
    rebuild: bool = Field(default=False, description="强制重建索引")


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
    ws_type = payload.workspace_type or "general"
    workspace = Workspace(
        owner_user_id=user.id,
        name=payload.name.strip(),
        description=payload.description,
        workspace_type=ws_type,
        review_template_key="engineering_bid_review_v1" if ws_type == "engineering" else None,
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
    workspace_type: str | None = Query(default=None, pattern="^(engineering|general)$"),
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = select(Workspace).where(Workspace.owner_user_id == user.id)
    if not include_deleted:
        statement = statement.where(Workspace.deleted_at.is_(None))
    if workspace_type:
        statement = statement.where(Workspace.workspace_type == workspace_type)
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
    workspace.updated_at = utcnow()
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


@router.delete("/{workspace_id}")
def delete_workspace(
    workspace_id: int,
    payload: DeleteWorkspaceRequest,
    request: Request,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
):
    workspace = get_owned_workspace(
        db,
        workspace_id=workspace_id,
        owner_user_id=user.id,
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作区不存在")

    # 名称确认：原始字符串精确比较（不 trim、不 strip）
    if payload.confirmation_name != workspace.name:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "WORKSPACE_DELETE_CONFIRMATION_MISMATCH",
                "message": "输入的项目名称不匹配，删除已取消",
            },
        )

    # 阶段 1：数据库删除 + 收集清理计划
    try:
        result = permanent_delete_workspace(db, workspace=workspace, user_id=user.id)
        add_audit_log(
            db,
            user_id=user.id,
            action="workspace.delete_permanent",
            resource_type="workspace",
            resource_id=workspace_id,
            status="success",
            ip_address=_client_ip(request),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    # 阶段 2：数据库已成功提交，逐个清理磁盘文件
    warnings: list[str] = []
    for label in result["skipped_cleanup"]:
        warnings.append(f"{label}: 磁盘清理已跳过（路径不安全）")
    for disk_path, label in result["cleanup_plan"]:
        err = _remove_file_safe(disk_path)
        if err:
            warnings.append(f"{label}: {err}")

    return {
        "message": "项目已永久删除",
        "workspace_id": workspace_id,
        "deleted_counts": result["deleted_counts"],
        "storage_cleanup_warnings": warnings,
    }


@router.post("/{workspace_id}/restore", include_in_schema=False)
def restore_workspace(
    workspace_id: int,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict:
    raise HTTPException(
        status_code=410,
        detail="软删除恢复接口已停用。历史软删除数据请通过独立迁移策略处理。",
    )


# ── 工程检索接口 ──────────────────────────────────────────────────


def _handle_retrieval_error(e: Exception) -> HTTPException:
    """将 EngineeringRetrievalError 映射为 HTTPException，安全化错误信息。"""
    if isinstance(e, EngineeringRetrievalError):
        return HTTPException(
            status_code=e.status_code,
            detail={
                "error_code": e.code,
                "message": e.message,
            },
        )
    # 未知异常：返回通用错误，不泄露内部信息
    return HTTPException(
        status_code=500,
        detail={
            "error_code": "ENGINEERING_RETRIEVAL_INDEX_ERROR",
            "message": "服务内部错误，请稍后重试",
        },
    )


def _check_engineering_workspace(db, workspace_id: int, user_id: int) -> Workspace:
    """校验工作区存在且为工程类型，否则抛出 HTTPException。"""
    workspace = get_owned_workspace(db, workspace_id=workspace_id, owner_user_id=user_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    if workspace.workspace_type != "engineering":
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "ENGINEERING_RETRIEVAL_WORKSPACE_INVALID",
                "message": "仅工程类工作区支持检索索引",
            },
        )
    return workspace


@router.get("/{workspace_id}/engineering-retrieval/index")
def get_retrieval_index(
    workspace_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict:
    """获取工程检索索引状态。"""
    _check_engineering_workspace(db, workspace_id, user.id)

    try:
        info = get_index_status(db, workspace_id, user.id)
    except EngineeringRetrievalError as e:
        raise _handle_retrieval_error(e)
    except Exception:
        raise _handle_retrieval_error(
            EngineeringRetrievalError(
                "ENGINEERING_RETRIEVAL_INDEX_ERROR",
                "获取索引状态失败",
                status_code=500,
            )
        )

    if info.status == "empty":
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "ENGINEERING_RETRIEVAL_MATERIAL_NOT_READY",
                "message": "工作区没有可用于检索的工程材料，请先上传文件并完成文件理解",
            },
        )

    return info.to_dict()


@router.post("/{workspace_id}/engineering-retrieval/index")
def build_retrieval_index(
    workspace_id: int,
    payload: BuildIndexRequest = BuildIndexRequest(),
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict:
    """构建/重建工程检索 Dense Index。"""
    _check_engineering_workspace(db, workspace_id, user.id)

    try:
        result = rebuild_index(
            db, workspace_id, user.id, rebuild=payload.rebuild
        )
    except EngineeringRetrievalError as e:
        raise _handle_retrieval_error(e)
    except Exception:
        raise _handle_retrieval_error(
            EngineeringRetrievalError(
                "ENGINEERING_RETRIEVAL_INDEX_ERROR",
                "索引构建失败",
                status_code=500,
            )
        )

    return result


@router.post("/{workspace_id}/engineering-retrieval/search")
def search_retrieval(
    workspace_id: int,
    payload: SearchRetrievalRequest,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> dict:
    """对工程工作区执行检索（需要 CSRF 保护）。"""
    _check_engineering_workspace(db, workspace_id, user.id)

    try:
        response = search_workspace(
            db,
            workspace_id,
            user.id,
            payload.query,
            top_k=payload.top_k,
            retrieval_mode=payload.retrieval_mode,
        )
    except EngineeringRetrievalError as e:
        raise _handle_retrieval_error(e)
    except Exception:
        raise _handle_retrieval_error(
            EngineeringRetrievalError(
                "ENGINEERING_RETRIEVAL_INDEX_ERROR",
                "检索失败",
                status_code=500,
            )
        )

    return response.to_dict()
