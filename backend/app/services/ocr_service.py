import json
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.file import File

SUPPORTED_OCR_TYPES = {"png", "jpg", "jpeg", "webp"}
OCR_ENGINE_NOT_CONFIGURED_MESSAGE = "OCR 引擎未配置，请安装 Tesseract 或后续接入 VLM API。"
OCR_LANGUAGE_NOT_FOUND_MESSAGE = "OCR 语言包未配置或缺失，请确认 Tesseract 已安装对应语言包。"


class FileOcrError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def run_image_ocr(db: Session, file_record: File) -> File:
    result = extract_text_from_image(file_record)
    schema = _load_schema(file_record.schema_json)
    file_path = Path(file_record.file_path)
    schema["file_type"] = file_record.file_type
    schema["filename"] = file_record.filename
    schema["file_path"] = str(file_path)
    schema["file_size"] = file_path.stat().st_size
    schema["ocr_status"] = "done"
    schema["ocr_result"] = result

    ocr_text = result["text"]
    file_record.status = "parsed"
    file_record.summary = ocr_text if ocr_text else "未识别到明显文字。"
    file_record.schema_json = json.dumps(schema, ensure_ascii=False)
    db.commit()
    db.refresh(file_record)
    return file_record


def get_or_run_image_ocr(db: Session, file_record: File) -> dict[str, Any]:
    schema = _load_schema(file_record.schema_json)
    ocr_result = schema.get("ocr_result")
    if isinstance(ocr_result, dict):
        return ocr_result

    updated_file = run_image_ocr(db, file_record)
    updated_schema = _load_schema(updated_file.schema_json)
    return updated_schema.get("ocr_result", {})


def extract_text_from_image(file_record: File) -> dict[str, Any]:
    _ensure_image_file(file_record)

    try:
        from PIL import Image
        import pytesseract
        from pytesseract import TesseractNotFoundError
    except ImportError as exc:
        raise FileOcrError("OCR 依赖未安装，请先安装 pytesseract 和 pillow。") from exc

    _configure_tesseract(pytesseract)

    try:
        with Image.open(file_record.file_path) as image:
            text = pytesseract.image_to_string(image, lang=settings.ocr_lang).strip()
    except TesseractNotFoundError as exc:
        raise FileOcrError(OCR_ENGINE_NOT_CONFIGURED_MESSAGE) from exc
    except Exception as exc:
        message = str(exc)
        normalized_message = message.lower()
        if _is_language_error(normalized_message):
            raise FileOcrError(f"{OCR_LANGUAGE_NOT_FOUND_MESSAGE} 当前 OCR_LANG={settings.ocr_lang}") from exc
        if "tesseract" in normalized_message:
            raise FileOcrError(OCR_ENGINE_NOT_CONFIGURED_MESSAGE) from exc
        raise FileOcrError(f"OCR 识别失败：{message}") from exc

    return {
        "status": "success",
        "engine": "tesseract",
        "filename": file_record.filename,
        "file_type": file_record.file_type,
        "text": text,
        "text_length": len(text),
        "message": "OCR 识别完成。" if text else "未识别到明显文字。",
    }


def extract_scanned_pdf_pages(
    pdf_path: Path,
    page_numbers: list[int],
) -> list[dict[str, Any]]:
    """只处理调用方判定为缺少有效文本的页面。

    page_numbers 使用从 1 开始的页码；返回值不写日志，也不会调用模型。
    """
    try:
        import fitz
        from PIL import Image
        import pytesseract
        from pytesseract import Output, TesseractNotFoundError
    except ImportError as exc:
        raise FileOcrError("扫描 PDF OCR 依赖未安装，请安装 PyMuPDF、pillow 和 pytesseract。") from exc

    _configure_tesseract(pytesseract)
    requested = list(dict.fromkeys(page_numbers))[: max(1, settings.pdf_ocr_max_pages)]
    started = time.monotonic()
    results: list[dict[str, Any]] = []
    try:
        with fitz.open(pdf_path) as document:
            for page_number in requested:
                if time.monotonic() - started > max(1, settings.pdf_ocr_timeout_seconds):
                    results.append(
                        {
                            "page_number": page_number,
                            "status": "timeout",
                            "text": "",
                            "confidence": None,
                            "source_type": "scanned_pdf_ocr",
                        }
                    )
                    continue
                if page_number < 1 or page_number > len(document):
                    continue
                page = document[page_number - 1]
                scale = max(1.0, settings.pdf_ocr_dpi / 72)
                width = int(page.rect.width * scale)
                height = int(page.rect.height * scale)
                pixels = width * height
                if pixels > max(1, settings.pdf_ocr_max_pixels_per_page):
                    scale *= (
                        settings.pdf_ocr_max_pixels_per_page / max(1, pixels)
                    ) ** 0.5
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                try:
                    data = pytesseract.image_to_data(
                        image,
                        lang=settings.ocr_lang,
                        output_type=Output.DICT,
                        timeout=max(1, settings.pdf_ocr_timeout_seconds),
                    )
                    words = [
                        str(word).strip()
                        for word in data.get("text", [])
                        if str(word).strip()
                    ]
                    confidences = []
                    for value in data.get("conf", []):
                        try:
                            confidence = float(value)
                        except (TypeError, ValueError):
                            continue
                        if confidence >= 0:
                            confidences.append(confidence)
                    results.append(
                        {
                            "page_number": page_number,
                            "status": "success",
                            "text": " ".join(words).strip(),
                            "confidence": (
                                round(sum(confidences) / len(confidences) / 100, 4)
                                if confidences
                                else None
                            ),
                            "source_type": "scanned_pdf_ocr",
                        }
                    )
                except RuntimeError as exc:
                    results.append(
                        {
                            "page_number": page_number,
                            "status": "failed",
                            "text": "",
                            "confidence": None,
                            "source_type": "scanned_pdf_ocr",
                            "message": str(exc)[:300],
                        }
                    )
    except TesseractNotFoundError as exc:
        raise FileOcrError(OCR_ENGINE_NOT_CONFIGURED_MESSAGE) from exc
    except FileOcrError:
        raise
    except Exception as exc:
        normalized = str(exc).lower()
        if _is_language_error(normalized):
            raise FileOcrError(
                f"{OCR_LANGUAGE_NOT_FOUND_MESSAGE} 当前 OCR_LANG={settings.ocr_lang}"
            ) from exc
        if "tesseract" in normalized:
            raise FileOcrError(OCR_ENGINE_NOT_CONFIGURED_MESSAGE) from exc
        raise FileOcrError(f"扫描 PDF OCR 失败：{str(exc)[:300]}") from exc
    return results


def _configure_tesseract(pytesseract_module: Any) -> None:
    tesseract_cmd = settings.tesseract_cmd.strip()
    if not tesseract_cmd:
        return

    tesseract_path = Path(tesseract_cmd)
    if not tesseract_path.exists():
        raise FileOcrError(f"Tesseract 路径不存在，请检查 TESSERACT_CMD：{tesseract_cmd}")

    if tesseract_path.is_dir():
        raise FileOcrError(f"TESSERACT_CMD 应指向 tesseract.exe 文件，而不是目录：{tesseract_cmd}")

    pytesseract_module.pytesseract.tesseract_cmd = str(tesseract_path)


def _is_language_error(message: str) -> bool:
    language_error_keywords = [
        "failed loading language",
        "could not initialize tesseract",
        "error opening data file",
        "tessdata",
    ]
    return any(keyword in message for keyword in language_error_keywords)


def _ensure_image_file(file_record: File) -> None:
    file_type = (file_record.file_type or "").lower()
    if file_type not in SUPPORTED_OCR_TYPES:
        raise FileOcrError("当前文件类型不支持 OCR，仅支持 PNG、JPG、JPEG、WEBP 图片")

    file_path = Path(file_record.file_path)
    if not file_path.exists():
        raise FileOcrError("文件不存在，无法执行 OCR")


def _load_schema(schema_json: str | None) -> dict[str, Any]:
    if not schema_json:
        return {}

    try:
        data = json.loads(schema_json)
    except json.JSONDecodeError:
        return {}

    return data if isinstance(data, dict) else {}
