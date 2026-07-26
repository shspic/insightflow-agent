import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import fitz
import pandas as pd
from sqlalchemy.orm import Session

from app.models.file import File

SUPPORTED_PARSE_TYPES = {"csv", "xlsx", "pdf", "png", "jpg", "jpeg"}
SUMMARY_LIMIT = 3000


class FileParseError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def parse_file(db: Session, file_record: File) -> File:
    try:
        result, summary = _parse_by_type(file_record)
    except Exception as exc:
        file_record.status = "failed"
        file_record.summary = f"解析失败：{exc}"
        db.commit()
        db.refresh(file_record)
        if isinstance(exc, FileParseError):
            raise
        raise FileParseError(str(exc)) from exc

    file_record.status = "parsed"
    file_record.summary = summary
    file_record.schema_json = json.dumps(result, ensure_ascii=False)
    db.commit()
    db.refresh(file_record)
    return file_record


def _parse_by_type(file_record: File) -> tuple[dict[str, Any], str]:
    file_type = (file_record.file_type or "").lower()
    file_path = Path(file_record.file_path)

    if file_type not in SUPPORTED_PARSE_TYPES:
        raise FileParseError("当前文件类型暂不支持解析")

    if not file_path.exists():
        raise FileParseError("文件不存在，无法解析")

    if file_type == "csv":
        return _parse_csv(file_path)

    if file_type == "xlsx":
        return _parse_excel(file_path)

    if file_type == "pdf":
        return _parse_pdf(file_path)

    return _parse_image(file_record, file_path)


def _parse_csv(file_path: Path) -> tuple[dict[str, Any], str]:
    dataframe = pd.read_csv(file_path)
    result = _build_table_result(dataframe)
    result["file_type"] = "csv"
    summary = f"CSV 文件解析完成：{result['row_count']} 行，{result['column_count']} 列。"
    return result, summary


def _parse_excel(file_path: Path) -> tuple[dict[str, Any], str]:
    with pd.ExcelFile(file_path) as workbook:
        sheet_name = workbook.sheet_names[0]
        dataframe = pd.read_excel(workbook, sheet_name=sheet_name)
    result = _build_table_result(dataframe)
    result["file_type"] = "xlsx"
    result["sheet_name"] = sheet_name
    summary = f"Excel 文件解析完成：第一个 sheet「{sheet_name}」，{result['row_count']} 行，{result['column_count']} 列。"
    return result, summary


def _parse_pdf(file_path: Path) -> tuple[dict[str, Any], str]:
    pages = []
    with fitz.open(file_path) as document:
        for index, page in enumerate(document, start=1):
            pages.append(
                {
                    "page_number": index,
                    "text": page.get_text("text"),
                }
            )

    full_text = "\n".join(page["text"] for page in pages).strip()
    summary = full_text[:SUMMARY_LIMIT] if full_text else "PDF 未提取到文本。"
    result = {
        "file_type": "pdf",
        "page_count": len(pages),
        "pages": pages,
        "summary_limit": SUMMARY_LIMIT,
    }
    return result, summary


def _parse_image(file_record: File, file_path: Path) -> tuple[dict[str, Any], str]:
    result = {
        "file_type": file_record.file_type,
        "filename": file_record.filename,
        "file_path": str(file_path),
        "file_size": file_path.stat().st_size,
        "ocr_status": "not_implemented",
    }
    return result, "图片文件已保存，OCR 暂未实现。"


def _build_table_result(dataframe: pd.DataFrame) -> dict[str, Any]:
    date_columns = _detect_date_columns(dataframe)
    numeric_columns = dataframe.select_dtypes(include=["number"]).columns.tolist()
    text_columns = [
        column
        for column in dataframe.columns.tolist()
        if column not in numeric_columns and column not in date_columns
    ]

    return {
        "columns": dataframe.columns.tolist(),
        "row_count": int(dataframe.shape[0]),
        "column_count": int(dataframe.shape[1]),
        "numeric_columns": numeric_columns,
        "text_columns": text_columns,
        "date_columns": date_columns,
        "missing_values": {column: int(dataframe[column].isna().sum()) for column in dataframe.columns},
        "preview_rows": _to_preview_rows(dataframe),
    }


def _detect_date_columns(dataframe: pd.DataFrame) -> list[str]:
    date_columns: list[str] = []

    for column in dataframe.columns:
        series = dataframe[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            date_columns.append(column)
            continue

        if not pd.api.types.is_object_dtype(series) and not pd.api.types.is_string_dtype(series):
            continue

        non_empty = series.dropna()
        if non_empty.empty:
            continue

        parsed = pd.to_datetime(non_empty, errors="coerce", format="mixed")
        if parsed.notna().sum() / len(non_empty) >= 0.8:
            date_columns.append(column)

    return date_columns


def _to_preview_rows(dataframe: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for record in dataframe.head(5).to_dict(orient="records"):
        rows.append({key: _to_json_value(value) for key, value in record.items()})
    return rows


def _to_json_value(value: Any) -> Any:
    if pd.isna(value):
        return None

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if hasattr(value, "item"):
        return value.item()

    return value
