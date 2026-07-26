from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_password_changed, require_password_changed_csrf
from app.core.config import settings
from app.db.session import get_db
from app.models.file_profile import FileProfile
from app.models.user import User
from app.schemas.file_relation import (
    FileRelationResponse,
    RelationDiscoverRequest,
    RelationDiscoverResponse,
    RelationMutationRequest,
)
from app.schemas.file_understanding import (
    BatchFileUnderstandRequest,
    BatchFileUnderstandResponse,
    FileProfileResponse,
    FileProfileUpdate,
    FileProfileVersionsResponse,
    FileUnderstandOptions,
    FileUnderstandResult,
)
from app.schemas.workspace_context import WorkspaceContextRequest, WorkspaceContextResponse
from app.services.file_relation_service import (
    FileRelationError,
    discover_file_relations,
    list_file_relations,
    mutate_file_relation,
    relation_response,
)
from app.services.file_understanding_service import (
    FileUnderstandingError,
    get_latest_profile,
    get_workspace_file_association,
    list_profile_versions,
    profile_response,
    understand_file,
    update_profile_confirmation,
)
from app.services.workspace_context_service import (
    WorkspaceContextError,
    build_workspace_context,
)
from app.services.workspace_service import get_owned_workspace_file


router = APIRouter(
    prefix="/api/v2/workspaces/{workspace_id}",
    tags=["v2-file-understanding"],
)


@router.post(
    "/files/{file_id}/understand",
    response_model=FileUnderstandResult,
)
def understand_workspace_file(
    workspace_id: int,
    file_id: int,
    options: FileUnderstandOptions = FileUnderstandOptions(),
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> FileUnderstandResult:
    try:
        profile = understand_file(
            db,
            file_id=file_id,
            workspace_id=workspace_id,
            owner_user_id=user.id,
            options=options,
        )
    except FileUnderstandingError as exc:
        raise _file_understanding_http_error(exc) from exc
    return _understand_result(profile)


@router.post(
    "/files/understand",
    response_model=BatchFileUnderstandResponse,
)
def understand_workspace_files(
    workspace_id: int,
    payload: BatchFileUnderstandRequest,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> BatchFileUnderstandResponse:
    if len(payload.file_ids) > max(1, settings.understanding_batch_max_files):
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"单次最多理解 {settings.understanding_batch_max_files} 个文件",
        )
    results: list[FileUnderstandResult] = []
    for file_id in payload.file_ids:
        try:
            profile = understand_file(
                db,
                file_id=file_id,
                workspace_id=workspace_id,
                owner_user_id=user.id,
                options=payload.options,
            )
            results.append(_understand_result(profile))
        except FileUnderstandingError as exc:
            results.append(
                FileUnderstandResult(
                    file_id=file_id,
                    profile_id=None,
                    profile_version=None,
                    status="failed",
                    error_code=exc.code,
                    message="文件不存在、无权访问或无法处理",
                )
            )
    overall_status = "completed" if all(item.status == "ready" for item in results) else "partial"
    return BatchFileUnderstandResponse(status=overall_status, results=results)


@router.get(
    "/files/{file_id}/profile",
    response_model=FileProfileResponse,
)
def get_workspace_file_profile(
    workspace_id: int,
    file_id: int,
    version: int | None = Query(default=None, ge=1),
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> FileProfileResponse:
    _owned_file_or_404(db, workspace_id, file_id, user.id)
    if version is None:
        profile = get_latest_profile(
            db,
            workspace_id=workspace_id,
            file_id=file_id,
            owner_user_id=user.id,
        )
    else:
        profile = db.scalar(
            select(FileProfile).where(
                FileProfile.workspace_id == workspace_id,
                FileProfile.file_id == file_id,
                FileProfile.owner_user_id == user.id,
                FileProfile.profile_version == version,
            )
        )
    if profile is None:
        raise HTTPException(status_code=404, detail="文件尚无对应理解结果")
    association = get_workspace_file_association(
        db,
        workspace_id=workspace_id,
        file_id=file_id,
    )
    return profile_response(profile, association)


@router.get(
    "/files/{file_id}/profile/versions",
    response_model=FileProfileVersionsResponse,
)
def get_workspace_file_profile_versions(
    workspace_id: int,
    file_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> FileProfileVersionsResponse:
    _owned_file_or_404(db, workspace_id, file_id, user.id)
    association = get_workspace_file_association(
        db,
        workspace_id=workspace_id,
        file_id=file_id,
    )
    profiles = list_profile_versions(
        db,
        workspace_id=workspace_id,
        file_id=file_id,
        owner_user_id=user.id,
    )
    return FileProfileVersionsResponse(
        file_id=file_id,
        profiles=[profile_response(item, association) for item in profiles],
    )


@router.patch(
    "/files/{file_id}/profile",
    response_model=FileProfileResponse,
)
def patch_workspace_file_profile(
    workspace_id: int,
    file_id: int,
    payload: FileProfileUpdate,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> FileProfileResponse:
    try:
        profile = update_profile_confirmation(
            db,
            workspace_id=workspace_id,
            file_id=file_id,
            owner_user_id=user.id,
            confirmed_role=payload.confirmed_role,
            custom_role=payload.custom_role,
            user_tags=payload.user_tags,
        )
    except FileUnderstandingError as exc:
        raise _file_understanding_http_error(exc) from exc
    association = get_workspace_file_association(
        db,
        workspace_id=workspace_id,
        file_id=file_id,
    )
    return profile_response(profile, association)


@router.post(
    "/file-relations/discover",
    response_model=RelationDiscoverResponse,
)
def discover_workspace_file_relations(
    workspace_id: int,
    payload: RelationDiscoverRequest,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> RelationDiscoverResponse:
    try:
        return discover_file_relations(
            db,
            workspace_id=workspace_id,
            owner_user_id=user.id,
            file_ids=payload.file_ids,
            use_deepseek=payload.use_deepseek,
        )
    except FileRelationError as exc:
        raise _relation_http_error(exc) from exc


@router.get(
    "/file-relations",
    response_model=list[FileRelationResponse],
)
def get_workspace_file_relations(
    workspace_id: int,
    relation_status: str | None = Query(default=None, alias="status"),
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> list[FileRelationResponse]:
    try:
        relations = list_file_relations(
            db,
            workspace_id=workspace_id,
            owner_user_id=user.id,
            status_filter=relation_status,
        )
    except FileRelationError as exc:
        raise _relation_http_error(exc) from exc
    return [relation_response(db, item) for item in relations]


@router.patch(
    "/file-relations/{relation_id}",
    response_model=FileRelationResponse,
)
def patch_workspace_file_relation(
    workspace_id: int,
    relation_id: int,
    payload: RelationMutationRequest,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> FileRelationResponse:
    try:
        relation = mutate_file_relation(
            db,
            workspace_id=workspace_id,
            relation_id=relation_id,
            owner_user_id=user.id,
            action=payload.action,
            relation_type=payload.relation_type,
            custom_relation_type=payload.custom_relation_type,
            user_note=payload.user_note,
        )
    except FileRelationError as exc:
        raise _relation_http_error(exc) from exc
    return relation_response(db, relation)


@router.post(
    "/context-preview",
    response_model=WorkspaceContextResponse,
)
def preview_workspace_context(
    workspace_id: int,
    payload: WorkspaceContextRequest,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> WorkspaceContextResponse:
    try:
        return build_workspace_context(
            db,
            workspace_id=workspace_id,
            owner_user_id=user.id,
            selected_file_ids=payload.file_ids,
        )
    except WorkspaceContextError as exc:
        code = status.HTTP_404_NOT_FOUND if exc.code == "WORKSPACE_NOT_FOUND" else 422
        raise HTTPException(status_code=code, detail=exc.message) from exc


def _owned_file_or_404(
    db: Session,
    workspace_id: int,
    file_id: int,
    owner_user_id: int,
) -> None:
    if get_owned_workspace_file(
        db,
        workspace_id=workspace_id,
        file_id=file_id,
        owner_user_id=owner_user_id,
    ) is None:
        raise HTTPException(status_code=404, detail="文件不存在")


def _understand_result(profile: FileProfile) -> FileUnderstandResult:
    messages = {
        "ready": "文件理解完成",
        "failed": "文件理解失败",
        "unsupported": "文件类型不受支持",
    }
    return FileUnderstandResult(
        file_id=profile.file_id,
        profile_id=profile.id,
        profile_version=profile.profile_version,
        status=profile.status,
        error_code=profile.error_code,
        message=messages.get(profile.status, "文件处理中"),
    )


def _file_understanding_http_error(exc: FileUnderstandingError) -> HTTPException:
    if exc.code in {"FILE_NOT_FOUND", "FILE_NOT_IN_WORKSPACE", "PROFILE_NOT_FOUND"}:
        return HTTPException(status_code=404, detail=exc.message)
    return HTTPException(status_code=422, detail=exc.message)


def _relation_http_error(exc: FileRelationError) -> HTTPException:
    if exc.code in {"WORKSPACE_NOT_FOUND", "RELATION_NOT_FOUND"}:
        return HTTPException(status_code=404, detail=exc.message)
    return HTTPException(status_code=422, detail=exc.message)
