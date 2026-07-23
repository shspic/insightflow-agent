from pathlib import Path

from fastapi import APIRouter, Depends, File as FormFile, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse as DownloadFileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_password_changed, require_password_changed_csrf
from app.core.config import BACKEND_DIR, settings
from app.db.session import get_db
from app.models.file import File
from app.models.file_relation import FileRelation
from app.models.user import User
from app.models.workspace_file import WorkspaceFile
from app.schemas.auth import MessageResponse
from app.schemas.rag import FileIndexResponse, FileSearchRequest, FileSearchResponse
from app.schemas.workspace import (
    WorkspaceFileBatchUploadResponse,
    WorkspaceFileResponse,
    WorkspaceFileUploadResult,
)
from app.services.analysis_service import FileAnalysisError, analyze_file
from app.services.audit_service import add_audit_log
from app.services.chart_service import FileChartError, generate_charts
from app.services.file_service import FileUploadError, save_uploaded_file
from app.services.ocr_service import FileOcrError, run_image_ocr
from app.services.parser_service import FileParseError, parse_file
from app.services.rag_service import RagServiceError, index_pdf_file, search_pdf_chunks
from app.services.workspace_service import (
    get_owned_workspace,
    get_owned_workspace_file,
    safe_schema,
    safe_public_text,
)


router = APIRouter(prefix="/api/v2/workspaces/{workspace_id}/files", tags=["v2-workspace-files"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _file_response(workspace_id: int, file_record: File) -> WorkspaceFileResponse:
    prefix = f"/api/v2/workspaces/{workspace_id}/files/{file_record.id}"
    size_bytes = file_record.size_bytes
    if size_bytes is None:
        path = Path(file_record.file_path)
        if path.exists():
            size_bytes = path.stat().st_size
    return WorkspaceFileResponse(
        file_id=file_record.id,
        display_name=file_record.filename,
        file_type=file_record.file_type,
        mime_type=file_record.mime_type,
        size_bytes=size_bytes,
        status=file_record.status,
        summary=safe_public_text(file_record.summary),
        structure=safe_schema(file_record.schema_json, prefix),
        download_url=f"{prefix}/download",
        created_at=file_record.created_at,
        updated_at=file_record.updated_at,
    )


def _owned_file_or_404(db: Session, workspace_id: int, file_id: int, user_id: int) -> File:
    file_record = get_owned_workspace_file(
        db,
        workspace_id=workspace_id,
        file_id=file_id,
        owner_user_id=user_id,
    )
    if file_record is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    return file_record


def _current_upload_usage(db: Session, workspace_id: int, user_id: int) -> tuple[int, int]:
    workspace_count = db.scalar(
        select(func.count()).select_from(WorkspaceFile).where(
            WorkspaceFile.workspace_id == workspace_id
        )
    ) or 0
    user_bytes = db.scalar(
        select(func.coalesce(func.sum(File.size_bytes), 0)).where(
            File.owner_user_id == user_id
        )
    ) or 0
    return int(workspace_count), int(user_bytes)


def _check_upload_quota(
    db: Session,
    *,
    workspace_id: int,
    user: User,
    incoming_size: int = 0,
) -> None:
    if user.role == "admin":
        return
    workspace_count, user_bytes = _current_upload_usage(db, workspace_id, user.id)
    if workspace_count >= max(1, settings.workspace_max_files):
        raise FileUploadError(
            f"工作区文件数量已达到上限 {settings.workspace_max_files}",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
    if user_bytes + incoming_size > max(1, settings.user_storage_quota_bytes):
        raise FileUploadError(
            f"用户存储配额不足，上限为 {settings.user_storage_quota_bytes} 字节",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )


@router.post("", response_model=WorkspaceFileResponse, status_code=status.HTTP_201_CREATED)
async def upload_workspace_file(
    workspace_id: int,
    request: Request,
    file: UploadFile = FormFile(...),
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> WorkspaceFileResponse:
    workspace = get_owned_workspace(db, workspace_id=workspace_id, owner_user_id=user.id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    file_record = None
    try:
        _check_upload_quota(db, workspace_id=workspace.id, user=user)
        _, usage_before = _current_upload_usage(db, workspace.id, user.id)
        file_record = await save_uploaded_file(
            db,
            file,
            owner_user_id=user.id,
            commit=False,
        )
        if (
            user.role != "admin"
            and usage_before + int(file_record.size_bytes or 0)
            > max(1, settings.user_storage_quota_bytes)
        ):
            raise FileUploadError(
                f"用户存储配额不足，上限为 {settings.user_storage_quota_bytes} 字节",
                status.HTTP_429_TOO_MANY_REQUESTS,
            )
        db.add(WorkspaceFile(workspace_id=workspace.id, file_id=file_record.id))
        db.flush()
        add_audit_log(
            db,
            user_id=user.id,
            action="file.upload",
            resource_type="file",
            resource_id=file_record.id,
            status="success",
            details={"workspace_id": workspace.id, "file_type": file_record.file_type},
            ip_address=_client_ip(request),
        )
        db.commit()
        db.refresh(file_record)
    except FileUploadError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception:
        db.rollback()
        if file_record is not None:
            saved_path = Path(file_record.file_path)
            if saved_path.exists():
                saved_path.unlink()
        raise
    return _file_response(workspace_id, file_record)


@router.post("/batch", response_model=WorkspaceFileBatchUploadResponse)
async def upload_workspace_files_batch(
    workspace_id: int,
    request: Request,
    files: list[UploadFile] = FormFile(...),
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> WorkspaceFileBatchUploadResponse:
    workspace = get_owned_workspace(db, workspace_id=workspace_id, owner_user_id=user.id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    if len(files) > max(1, settings.upload_max_batch_files):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"单次最多上传 {settings.upload_max_batch_files} 个文件",
        )
    results: list[WorkspaceFileUploadResult] = []
    for upload_file in files:
        original_name = Path(upload_file.filename or "unnamed").name
        file_record = None
        try:
            _check_upload_quota(db, workspace_id=workspace.id, user=user)
            _, usage_before = _current_upload_usage(db, workspace.id, user.id)
            file_record = await save_uploaded_file(
                db,
                upload_file,
                owner_user_id=user.id,
                commit=False,
            )
            if (
                user.role != "admin"
                and usage_before + int(file_record.size_bytes or 0)
                > max(1, settings.user_storage_quota_bytes)
            ):
                raise FileUploadError(
                    f"用户存储配额不足，上限为 {settings.user_storage_quota_bytes} 字节",
                    status.HTTP_429_TOO_MANY_REQUESTS,
                )
            db.add(WorkspaceFile(workspace_id=workspace.id, file_id=file_record.id))
            db.flush()
            add_audit_log(
                db,
                user_id=user.id,
                action="file.upload",
                resource_type="file",
                resource_id=file_record.id,
                status="success",
                details={"workspace_id": workspace.id, "file_type": file_record.file_type},
                ip_address=_client_ip(request),
            )
            db.commit()
            db.refresh(file_record)
            results.append(
                WorkspaceFileUploadResult(
                    filename=original_name,
                    status="uploaded",
                    file=_file_response(workspace_id, file_record),
                    message="上传成功",
                )
            )
        except FileUploadError as exc:
            db.rollback()
            if file_record is not None:
                saved_path = Path(file_record.file_path)
                if saved_path.exists():
                    saved_path.unlink()
            results.append(
                WorkspaceFileUploadResult(
                    filename=original_name,
                    status="failed",
                    error_status=exc.status_code,
                    error_code=_upload_error_code(exc.status_code),
                    message=exc.message,
                )
            )
        except Exception:
            db.rollback()
            if file_record is not None:
                saved_path = Path(file_record.file_path)
                if saved_path.exists():
                    saved_path.unlink()
            results.append(
                WorkspaceFileUploadResult(
                    filename=original_name,
                    status="failed",
                    error_status=500,
                    error_code="SERVER_ERROR",
                    message="服务器暂时无法保存文件",
                )
            )
    overall_status = "completed" if all(item.status == "uploaded" for item in results) else "partial"
    return WorkspaceFileBatchUploadResponse(status=overall_status, results=results)


def _upload_error_code(status_code: int) -> str:
    return {
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: "FILE_TOO_LARGE",
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "UNSUPPORTED_FILE_TYPE",
        status.HTTP_422_UNPROCESSABLE_ENTITY: "FILE_VALIDATION_FAILED",
        status.HTTP_429_TOO_MANY_REQUESTS: "UPLOAD_QUOTA_EXCEEDED",
    }.get(status_code, "UPLOAD_FAILED")


@router.get("", response_model=list[WorkspaceFileResponse])
def list_workspace_files(
    workspace_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> list[WorkspaceFileResponse]:
    workspace = get_owned_workspace(db, workspace_id=workspace_id, owner_user_id=user.id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    files = db.scalars(
        select(File)
        .join(WorkspaceFile, WorkspaceFile.file_id == File.id)
        .where(
            WorkspaceFile.workspace_id == workspace_id,
            File.owner_user_id == user.id,
        )
        .order_by(File.created_at.desc())
    ).all()
    return [_file_response(workspace_id, item) for item in files]


@router.get("/{file_id}", response_model=WorkspaceFileResponse)
def get_workspace_file(
    workspace_id: int,
    file_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> WorkspaceFileResponse:
    return _file_response(
        workspace_id,
        _owned_file_or_404(db, workspace_id, file_id, user.id),
    )


@router.delete("/{file_id}", response_model=MessageResponse)
def remove_workspace_file(
    workspace_id: int,
    file_id: int,
    request: Request,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> MessageResponse:
    _owned_file_or_404(db, workspace_id, file_id, user.id)
    association = db.scalar(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == workspace_id,
            WorkspaceFile.file_id == file_id,
        )
    )
    if association is None:
        raise HTTPException(status_code=404, detail="文件关联不存在")
    db.query(FileRelation).filter(
        FileRelation.workspace_id == workspace_id,
        or_(
            FileRelation.source_file_id == file_id,
            FileRelation.target_file_id == file_id,
        ),
    ).delete(synchronize_session=False)
    db.delete(association)
    add_audit_log(
        db,
        user_id=user.id,
        action="file.detach",
        resource_type="file",
        resource_id=file_id,
        status="success",
        details={"workspace_id": workspace_id},
        ip_address=_client_ip(request),
    )
    db.commit()
    return MessageResponse(message="文件已从工作区移除，原始文件等待后续清理")


@router.get("/{file_id}/download")
def download_workspace_file(
    workspace_id: int,
    file_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> DownloadFileResponse:
    file_record = _owned_file_or_404(db, workspace_id, file_id, user.id)
    path = Path(file_record.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件内容不存在")
    return DownloadFileResponse(
        path=path,
        media_type=file_record.mime_type,
        filename=file_record.filename,
    )


def _mutated_file_response(workspace_id: int, file_record: File) -> WorkspaceFileResponse:
    return _file_response(workspace_id, file_record)


@router.post("/{file_id}/parse", response_model=WorkspaceFileResponse)
def parse_workspace_file(
    workspace_id: int,
    file_id: int,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> WorkspaceFileResponse:
    record = _owned_file_or_404(db, workspace_id, file_id, user.id)
    try:
        return _mutated_file_response(workspace_id, parse_file(db, record))
    except FileParseError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.post("/{file_id}/analyze", response_model=WorkspaceFileResponse)
def analyze_workspace_file(
    workspace_id: int,
    file_id: int,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> WorkspaceFileResponse:
    record = _owned_file_or_404(db, workspace_id, file_id, user.id)
    try:
        return _mutated_file_response(workspace_id, analyze_file(db, record))
    except FileAnalysisError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.post("/{file_id}/charts", response_model=WorkspaceFileResponse)
def chart_workspace_file(
    workspace_id: int,
    file_id: int,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> WorkspaceFileResponse:
    record = _owned_file_or_404(db, workspace_id, file_id, user.id)
    try:
        return _mutated_file_response(workspace_id, generate_charts(db, record))
    except FileChartError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.post("/{file_id}/index", response_model=FileIndexResponse)
def index_workspace_pdf(
    workspace_id: int,
    file_id: int,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> FileIndexResponse:
    record = _owned_file_or_404(db, workspace_id, file_id, user.id)
    try:
        return index_pdf_file(db, record)
    except RagServiceError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.post("/{file_id}/search", response_model=FileSearchResponse)
def search_workspace_pdf(
    workspace_id: int,
    file_id: int,
    payload: FileSearchRequest,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> FileSearchResponse:
    record = _owned_file_or_404(db, workspace_id, file_id, user.id)
    try:
        return search_pdf_chunks(
            db,
            record,
            query=payload.query,
            top_k=payload.top_k,
            retrieval_mode=payload.retrieval_mode,
        )
    except RagServiceError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.post("/{file_id}/ocr", response_model=WorkspaceFileResponse)
def ocr_workspace_file(
    workspace_id: int,
    file_id: int,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
) -> WorkspaceFileResponse:
    record = _owned_file_or_404(db, workspace_id, file_id, user.id)
    try:
        return _mutated_file_response(workspace_id, run_image_ocr(db, record))
    except FileOcrError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.get("/{file_id}/assets/{asset_name}")
def download_workspace_asset(
    workspace_id: int,
    file_id: int,
    asset_name: str,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> DownloadFileResponse:
    record = _owned_file_or_404(db, workspace_id, file_id, user.id)
    schema = safe_schema(record.schema_json, "")
    if not schema or asset_name not in str(schema):
        raise HTTPException(status_code=404, detail="资源不存在")
    chart_dir = Path(settings.chart_dir)
    if not chart_dir.is_absolute():
        chart_dir = BACKEND_DIR / chart_dir
    asset_path = (chart_dir / Path(asset_name).name).resolve()
    if asset_path.parent != chart_dir.resolve() or not asset_path.exists():
        raise HTTPException(status_code=404, detail="资源不存在")
    return DownloadFileResponse(path=asset_path, filename=asset_path.name)
