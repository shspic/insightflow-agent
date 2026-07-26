from pathlib import Path
import zipfile
from uuid import uuid4

import fitz
from fastapi import UploadFile, status
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, settings
from app.models.file import File

ALLOWED_EXTENSIONS = {
    ".xlsx",
    ".csv",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".md",
    ".markdown",
}
CHUNK_SIZE = 1024 * 1024
MIME_TYPES = {
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
        "application/octet-stream",
    },
    ".csv": {
        "text/csv",
        "application/csv",
        "text/plain",
        "application/vnd.ms-excel",
        "application/octet-stream",
    },
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".png": {"image/png", "application/octet-stream"},
    ".jpg": {"image/jpeg", "image/jpg", "application/octet-stream"},
    ".jpeg": {"image/jpeg", "image/jpg", "application/octet-stream"},
    ".webp": {"image/webp", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".markdown": {"text/markdown", "text/plain", "application/octet-stream"},
}
DETECTED_MIME_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


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
        raise FileUploadError(
            f"不支持的文件类型，仅支持：{allowed}",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
    return extension


def _build_saved_filename(extension: str) -> str:
    return f"{uuid4().hex}{extension}"


async def save_uploaded_file(
    db: Session,
    upload_file: UploadFile,
    *,
    owner_user_id: int | None = None,
    commit: bool = True,
    max_size_bytes: int | None = None,
) -> File:
    original_filename = _safe_original_filename(upload_file.filename)
    extension = _get_allowed_extension(original_filename)
    upload_dir = _resolve_upload_dir()
    saved_filename = _build_saved_filename(extension)
    saved_path = upload_dir / saved_filename
    written_size = 0
    size_limit = max_size_bytes or settings.upload_max_file_size_bytes

    try:
        with saved_path.open("wb") as buffer:
            while True:
                chunk = await upload_file.read(CHUNK_SIZE)
                if not chunk:
                    break

                written_size += len(chunk)
                if written_size > size_limit:
                    raise FileUploadError(
                        f"单文件大小不能超过 {size_limit} 字节",
                        status.HTTP_413_CONTENT_TOO_LARGE,
                    )

                buffer.write(chunk)
        if written_size == 0:
            raise FileUploadError("不允许上传空文件", status.HTTP_422_UNPROCESSABLE_CONTENT)
        detected_mime_type = _validate_saved_file(
            saved_path,
            extension,
            upload_file.content_type,
        )
    except Exception:
        if saved_path.exists():
            saved_path.unlink()
        raise
    finally:
        await upload_file.close()

    file_record = File(
        owner_user_id=owner_user_id,
        filename=original_filename,
        file_type=extension.removeprefix("."),
        mime_type=detected_mime_type,
        size_bytes=written_size,
        file_path=str(saved_path),
        status="uploaded",
    )
    db.add(file_record)

    try:
        if commit:
            db.commit()
            db.refresh(file_record)
        else:
            db.flush()
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


def _validate_saved_file(
    path: Path,
    extension: str,
    declared_mime_type: str | None,
) -> str:
    declared = (declared_mime_type or "").split(";", 1)[0].strip().lower()
    if declared and declared not in MIME_TYPES[extension]:
        raise FileUploadError(
            f"文件 MIME 类型与扩展名不匹配：{declared}",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
    header = path.read_bytes()[:64]
    if extension == ".xlsx":
        _validate_xlsx(path, header)
    elif extension == ".pdf":
        if not header.startswith(b"%PDF-"):
            raise FileUploadError("PDF 文件头无效", status.HTTP_422_UNPROCESSABLE_CONTENT)
        _validate_pdf(path)
    elif extension == ".png":
        if not header.startswith(b"\x89PNG\r\n\x1a\n"):
            raise FileUploadError("PNG 文件头无效", status.HTTP_422_UNPROCESSABLE_CONTENT)
        _validate_image(path)
    elif extension in {".jpg", ".jpeg"}:
        if not header.startswith(b"\xff\xd8\xff"):
            raise FileUploadError("JPEG 文件头无效", status.HTTP_422_UNPROCESSABLE_CONTENT)
        _validate_image(path)
    elif extension == ".webp":
        if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WEBP":
            raise FileUploadError("WEBP 文件头无效", status.HTTP_422_UNPROCESSABLE_CONTENT)
        _validate_image(path)
    else:
        _validate_text_file(path, extension)
    return DETECTED_MIME_TYPES[extension]


def _validate_xlsx(path: Path, header: bytes) -> None:
    if not header.startswith(b"PK"):
        raise FileUploadError("XLSX 文件头无效", status.HTTP_422_UNPROCESSABLE_CONTENT)
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise FileUploadError(
                    "文件不是有效的 XLSX 工作簿",
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                )
            uncompressed_size = sum(item.file_size for item in archive.infolist())
            if uncompressed_size > 100 * 1024 * 1024:
                raise FileUploadError(
                    "XLSX 解压后内容超过安全上限",
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                )
            if path.stat().st_size and uncompressed_size / path.stat().st_size > 100:
                raise FileUploadError(
                    "XLSX 压缩比异常",
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                )
    except FileUploadError:
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        raise FileUploadError(
            "XLSX 压缩结构无效",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        ) from exc


def _validate_pdf(path: Path) -> None:
    try:
        with fitz.open(path) as document:
            if len(document) > max(1, settings.pdf_max_pages):
                raise FileUploadError(
                    f"PDF 页数不能超过 {settings.pdf_max_pages}",
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                )
    except FileUploadError:
        raise
    except Exception as exc:
        raise FileUploadError("PDF 文件损坏或无法读取", status.HTTP_422_UNPROCESSABLE_CONTENT) from exc


def _validate_image(path: Path) -> None:
    try:
        with Image.open(path) as image:
            width, height = image.size
            if width * height > max(1, settings.image_max_pixels):
                raise FileUploadError(
                    f"图片像素数不能超过 {settings.image_max_pixels}",
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                )
            image.verify()
    except FileUploadError:
        raise
    except Exception as exc:
        raise FileUploadError("图片损坏或格式无效", status.HTTP_422_UNPROCESSABLE_CONTENT) from exc


def _validate_text_file(path: Path, extension: str) -> None:
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise FileUploadError("文本文件包含二进制空字符", status.HTTP_422_UNPROCESSABLE_CONTENT)
    decoded = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise FileUploadError("文本文件编码不受支持", status.HTTP_422_UNPROCESSABLE_CONTENT)
    if extension == ".csv":
        sample = decoded[:8192]
        if not any(delimiter in sample for delimiter in (",", "\t", ";", "|")):
            raise FileUploadError(
                "CSV 未检测到常见分隔符",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
