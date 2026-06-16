from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, settings
from app.models.file import File

ALLOWED_EXTENSIONS = {".xlsx", ".csv", ".pdf", ".png", ".jpg", ".jpeg"}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


class FileUploadError(Exception):
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _resolve_upload_dir() -> Path:
    upload_dir = Path(settings.upload_dir)
    if not upload_dir.is_absolute():
        upload_dir = BACKEND_DIR / upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def _safe_original_filename(filename: str | None) -> str:
    name = Path(filename or "").name.strip()
    return name or "unnamed"


def _get_allowed_extension(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise FileUploadError(f"不支持的文件类型，仅支持：{allowed}")
    return extension


def _build_saved_filename(extension: str) -> str:
    return f"{uuid4().hex}{extension}"


async def save_uploaded_file(db: Session, upload_file: UploadFile) -> File:
    original_filename = _safe_original_filename(upload_file.filename)
    extension = _get_allowed_extension(original_filename)
    upload_dir = _resolve_upload_dir()
    saved_filename = _build_saved_filename(extension)
    saved_path = upload_dir / saved_filename
    written_size = 0

    try:
        with saved_path.open("wb") as buffer:
            while True:
                chunk = await upload_file.read(CHUNK_SIZE)
                if not chunk:
                    break

                written_size += len(chunk)
                if written_size > MAX_UPLOAD_SIZE:
                    raise FileUploadError("单文件最大支持 10MB", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

                buffer.write(chunk)
    except Exception:
        if saved_path.exists():
            saved_path.unlink()
        raise
    finally:
        await upload_file.close()

    file_record = File(
        filename=original_filename,
        file_type=extension.removeprefix("."),
        file_path=str(saved_path),
        status="pending",
    )
    db.add(file_record)

    try:
        db.commit()
        db.refresh(file_record)
    except Exception:
        db.rollback()
        if saved_path.exists():
            saved_path.unlink()
        raise

    return file_record


def list_files(db: Session) -> list[File]:
    return db.query(File).order_by(File.created_at.desc()).all()


def get_file_by_id(db: Session, file_id: int) -> File | None:
    return db.get(File, file_id)
