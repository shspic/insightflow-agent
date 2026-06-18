import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.file import File
from app.services.analysis_service import analyze_file
from app.services.chart_service import generate_charts
from app.services.ocr_service import get_or_run_image_ocr
from app.services.rag_service import answer_pdf_question

TABLE_TYPES = {"csv", "xlsx"}
IMAGE_TYPES = {"png", "jpg", "jpeg"}


class MultiFileServiceError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def analyze_multiple_files(db: Session, file_ids: list[int], user_input: str) -> dict[str, Any]:
    files = _load_files(db, file_ids)
    grouped_files = _group_files(files)
    table_results = [_analyze_table_file(db, file_record) for file_record in grouped_files["tables"]]
    pdf_results = [_analyze_pdf_file(db, file_record, user_input) for file_record in grouped_files["pdfs"]]
    image_results = [_analyze_image_file(db, file_record) for file_record in grouped_files["images"]]
    other_results = [_build_file_summary(file_record, message="当前文件类型暂未纳入综合分析工具。") for file_record in grouped_files["others"]]
    errors = _collect_errors(table_results, pdf_results, image_results, other_results)

    return {
        "file_count": len(files),
        "table_file_count": len(grouped_files["tables"]),
        "pdf_file_count": len(grouped_files["pdfs"]),
        "image_file_count": len(grouped_files["images"]),
        "other_file_count": len(grouped_files["others"]),
        "analysis_count": sum(1 for item in table_results if item.get("analysis_result")),
        "chart_count": sum(len(item.get("charts") or []) for item in table_results),
        "pdf_result_count": sum(len(item.get("sources") or []) for item in pdf_results),
        "ocr_count": sum(1 for item in image_results if item.get("ocr_result")),
        "files": [_build_file_summary(file_record) for file_record in files],
        "table_results": table_results,
        "pdf_results": pdf_results,
        "image_results": image_results,
        "other_results": other_results,
        "errors": errors,
    }


def summarize_multi_file_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "file_count": result.get("file_count", 0),
        "table_file_count": result.get("table_file_count", 0),
        "pdf_file_count": result.get("pdf_file_count", 0),
        "image_file_count": result.get("image_file_count", 0),
        "analysis_count": result.get("analysis_count", 0),
        "chart_count": result.get("chart_count", 0),
        "pdf_result_count": result.get("pdf_result_count", 0),
        "ocr_count": result.get("ocr_count", 0),
        "errors": result.get("errors", []),
        "files": [
            {
                "file_id": file_item.get("file_id"),
                "filename": file_item.get("filename"),
                "file_type": file_item.get("file_type"),
                "status": file_item.get("status"),
            }
            for file_item in result.get("files", [])
        ],
    }


def _load_files(db: Session, file_ids: list[int]) -> list[File]:
    if not file_ids:
        raise MultiFileServiceError("请至少选择一个文件")

    files = db.query(File).filter(File.id.in_(file_ids)).all()
    file_map = {file_record.id: file_record for file_record in files}
    missing_ids = [file_id for file_id in file_ids if file_id not in file_map]
    if missing_ids:
        raise MultiFileServiceError(f"文件不存在：{missing_ids}")

    return [file_map[file_id] for file_id in file_ids]


def _group_files(files: list[File]) -> dict[str, list[File]]:
    grouped = {"tables": [], "pdfs": [], "images": [], "others": []}
    for file_record in files:
        file_type = (file_record.file_type or "").lower()
        if file_type in TABLE_TYPES:
            grouped["tables"].append(file_record)
        elif file_type == "pdf":
            grouped["pdfs"].append(file_record)
        elif file_type in IMAGE_TYPES:
            grouped["images"].append(file_record)
        else:
            grouped["others"].append(file_record)
    return grouped


def _analyze_table_file(db: Session, file_record: File) -> dict[str, Any]:
    try:
        schema = _load_schema(file_record.schema_json)
        if not isinstance(schema.get("analysis_result"), dict):
            file_record = analyze_file(db, file_record)
            schema = _load_schema(file_record.schema_json)

        if not schema.get("charts"):
            file_record = generate_charts(db, file_record)
            schema = _load_schema(file_record.schema_json)

        return {
            **_build_file_summary(file_record),
            "analysis_result": schema.get("analysis_result", {}),
            "charts": schema.get("charts", []),
        }
    except Exception as exc:
        return {
            **_build_file_summary(file_record),
            "error": f"表格分析失败：{exc}",
        }


def _analyze_pdf_file(db: Session, file_record: File, user_input: str) -> dict[str, Any]:
    try:
        result = answer_pdf_question(db=db, file_record=file_record, question=user_input)
        return {
            **_build_file_summary(file_record),
            "answer": result.get("answer"),
            "sources": result.get("sources", []),
            "retrieval_mode": result.get("retrieval_mode"),
            "fallback_used": result.get("fallback_used", False),
            "result_count": result.get("result_count", len(result.get("results", []))),
            "message": result.get("message"),
        }
    except Exception as exc:
        return {
            **_build_file_summary(file_record),
            "error": f"PDF 检索失败：{exc}",
        }


def _analyze_image_file(db: Session, file_record: File) -> dict[str, Any]:
    try:
        result = get_or_run_image_ocr(db=db, file_record=file_record)
        return {
            **_build_file_summary(file_record),
            "ocr_result": result,
        }
    except Exception as exc:
        return {
            **_build_file_summary(file_record),
            "error": f"图片 OCR 失败：{exc}",
        }


def _build_file_summary(file_record: File, message: str | None = None) -> dict[str, Any]:
    payload = {
        "file_id": file_record.id,
        "filename": file_record.filename,
        "file_type": file_record.file_type,
        "status": file_record.status,
        "summary": file_record.summary,
    }
    if message:
        payload["message"] = message
    return payload


def _collect_errors(*groups: list[dict[str, Any]]) -> list[str]:
    errors = []
    for group in groups:
        for item in group:
            error = item.get("error")
            if error:
                errors.append(f"{item.get('filename')}：{error}")
    return errors


def _load_schema(schema_json: str | None) -> dict[str, Any]:
    if not schema_json:
        return {}

    try:
        data = json.loads(schema_json)
    except json.JSONDecodeError:
        return {}

    return data if isinstance(data, dict) else {}
