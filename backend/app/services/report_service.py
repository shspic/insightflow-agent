import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, settings
from app.models.file import File
from app.models.task import Task
from app.models.tool_call import ToolCall


class ReportServiceError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def generate_task_report(
    db: Session,
    task_id: int,
    task_type: str | None = None,
    final_answer: str | None = None,
) -> dict[str, Any]:
    task = db.get(Task, task_id)
    if task is None:
        raise ReportServiceError("任务不存在，无法生成报告")

    files = _load_task_files(db, task)
    content = _build_report_content(
        db=db,
        task=task,
        files=files,
        task_type=task_type or task.task_type,
        final_answer=final_answer or task.final_answer,
    )
    report_path = _save_report_file(task_id=task.id, content=content)
    task.report_path = report_path
    db.commit()
    db.refresh(task)

    return _build_response(task_id=task.id, report_path=report_path, content=content)


def get_task_report(db: Session, task_id: int) -> dict[str, Any]:
    task = db.get(Task, task_id)
    if task is None:
        raise ReportServiceError("任务不存在")

    if not task.report_path:
        raise ReportServiceError("该任务还没有生成报告")

    report_file = resolve_report_file(task.report_path)
    if not report_file.exists():
        raise ReportServiceError("报告文件不存在，请重新生成报告")

    content = report_file.read_text(encoding="utf-8")
    return _build_response(task_id=task.id, report_path=task.report_path, content=content)


def resolve_report_file(report_path: str) -> Path:
    path = Path(report_path)
    if path.is_absolute():
        return path

    candidate = BACKEND_DIR / path
    if candidate.exists():
        return candidate

    return _resolve_report_dir() / path.name


def _build_report_content(
    db: Session,
    task: Task,
    files: list[File],
    task_type: str | None,
    final_answer: str | None,
) -> str:
    sections = [
        "# 分析报告",
        "",
        "## 1. 任务说明",
        f"- 用户输入：{_text(task.user_input)}",
        f"- 任务类型：{_text(task_type)}",
        f"- 关联文件：{_format_file_names(files)}",
        "",
        "## 2. 文件概况",
        _build_file_overview(files),
        "",
        "## 3. 数据概况",
        _build_data_section(files),
        "",
        "## 4. 图表展示",
        _build_chart_section(files),
        "",
        "## 5. 文档依据",
        _build_pdf_sources_section(db, task.id),
        "",
        "## 6. 图片识别结果",
        _build_ocr_section(files),
        "",
        "## 7. 风险与限制",
        "- 当前结果基于上传文件和系统已有工具自动生成。",
        "- OCR、PDF 文本提取、关键词检索和表格统计都可能存在误差。",
        "- 当前报告不是最终专业判断，重要结论仍需人工复核。",
        "",
        "## 8. 结论与建议",
        _text(final_answer) if final_answer else "本报告已整理当前任务和关联文件信息，建议结合原始文件继续核对关键结论。",
        "",
    ]
    return "\n".join(sections)


def _build_file_overview(files: list[File]) -> str:
    if not files:
        return "未找到关联文件。"

    lines = []
    for file_record in files:
        lines.extend(
            [
                f"### 文件 {file_record.id}",
                f"- 文件名：{_text(file_record.filename)}",
                f"- 文件类型：{_text(file_record.file_type)}",
                f"- 文件状态：{_text(file_record.status)}",
                f"- 文件摘要：{_text(file_record.summary)}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _build_data_section(files: list[File]) -> str:
    table_files = [file_record for file_record in files if (file_record.file_type or "").lower() in {"csv", "xlsx"}]
    if not table_files:
        return "本次任务未包含表格数据分析。"

    sections = []
    for file_record in table_files:
        schema = _load_schema(file_record.schema_json)
        analysis = schema.get("analysis_result") if isinstance(schema.get("analysis_result"), dict) else schema
        if not analysis:
            sections.append(f"### {_text(file_record.filename)}\n本次任务未包含表格数据分析。")
            continue

        sections.append(
            "\n".join(
                [
                    f"### {_text(file_record.filename)}",
                    f"- 行数：{_text(analysis.get('row_count'))}",
                    f"- 列数：{_text(analysis.get('column_count'))}",
                    f"- 字段：{_join_values(analysis.get('columns'))}",
                    f"- 缺失值：{_format_mapping(analysis.get('missing_values'))}",
                    f"- 数值列统计：{_format_nested_mapping(analysis.get('numeric_statistics'))}",
                    f"- 文本列高频值：{_format_text_top_values(analysis.get('text_top_values'))}",
                ]
            )
        )
    return "\n\n".join(sections)


def _build_chart_section(files: list[File]) -> str:
    charts = []
    for file_record in files:
        schema = _load_schema(file_record.schema_json)
        charts.extend(schema.get("charts") or [])

    if not charts:
        return "本次任务未生成图表。"

    lines = []
    for chart in charts:
        if chart.get("skipped"):
            lines.append(f"- {chart.get('title')}：{chart.get('description')}")
            continue
        chart_path = chart.get("url_path") or chart.get("file_path")
        lines.append(f"- {chart.get('title')}：{chart.get('description')}；图片路径：{chart_path}")
    return "\n".join(lines)


def _build_pdf_sources_section(db: Session, task_id: int) -> str:
    sources = _load_pdf_sources_from_trace(db, task_id)
    if not sources:
        return "本次任务未包含 PDF 引用来源。"

    lines = []
    for index, source in enumerate(sources, start=1):
        lines.append(
            f"{index}. 文件：{_text(source.get('filename'))}；"
            f"页码：第 {_text(source.get('page_number'))} 页；"
            f"引用片段：{_text(source.get('chunk_text'))}"
        )
    return "\n".join(lines)


def _build_ocr_section(files: list[File]) -> str:
    lines = []
    for file_record in files:
        schema = _load_schema(file_record.schema_json)
        ocr_result = schema.get("ocr_result")
        if isinstance(ocr_result, dict):
            text = ocr_result.get("text") or "未识别到明显文字。"
            lines.append(f"### {_text(file_record.filename)}\n{text}")

    if not lines:
        return "本次任务未包含图片识别结果。"

    return "\n\n".join(lines)


def _load_pdf_sources_from_trace(db: Session, task_id: int) -> list[dict[str, Any]]:
    tool_calls = (
        db.query(ToolCall)
        .filter(ToolCall.task_id == task_id, ToolCall.tool_name == "pdf_retrieval_tool")
        .order_by(ToolCall.created_at.asc())
        .all()
    )
    sources = []
    for tool_call in tool_calls:
        payload = _load_schema(tool_call.output_json)
        tool_result = payload.get("tool_results", {}).get("pdf_retrieval_tool", {})
        if isinstance(tool_result, dict):
            sources.extend(source for source in tool_result.get("sources", []) if isinstance(source, dict))
    return sources


def _load_task_files(db: Session, task: Task) -> list[File]:
    file_ids = _load_file_ids(task.file_ids_json)
    if not file_ids:
        return []
    return db.query(File).filter(File.id.in_(file_ids)).all()


def _load_file_ids(file_ids_json: str | None) -> list[int]:
    if not file_ids_json:
        return []
    try:
        data = json.loads(file_ids_json)
    except json.JSONDecodeError:
        return []
    return [int(item) for item in data] if isinstance(data, list) else []


def _save_report_file(task_id: int, content: str) -> str:
    report_dir = _resolve_report_dir()
    filename = f"task_{task_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}.md"
    report_file = report_dir / filename
    report_file.write_text(content, encoding="utf-8")
    return _to_stored_report_path(report_file)


def _resolve_report_dir() -> Path:
    report_dir = Path(settings.report_dir)
    if not report_dir.is_absolute():
        report_dir = BACKEND_DIR / report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def _to_stored_report_path(report_file: Path) -> str:
    try:
        return str(report_file.relative_to(BACKEND_DIR)).replace("\\", "/")
    except ValueError:
        return report_file.name


def _build_response(task_id: int, report_path: str, content: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "title": "分析报告",
        "report_path": report_path,
        "download_url": f"/api/reports/{task_id}/download",
        "content": content,
    }


def _format_file_names(files: list[File]) -> str:
    if not files:
        return "无"
    return "，".join(file_record.filename for file_record in files)


def _load_schema(schema_json: str | None) -> dict[str, Any]:
    if not schema_json:
        return {}
    try:
        data = json.loads(schema_json)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _format_mapping(values: Any) -> str:
    if not isinstance(values, dict) or not values:
        return "无"
    return "；".join(f"{_text(key)}：{_text(value)}" for key, value in values.items())


def _format_nested_mapping(values: Any) -> str:
    if not isinstance(values, dict) or not values:
        return "无"
    parts = []
    for key, value in values.items():
        if isinstance(value, dict):
            parts.append(f"{_text(key)}（{_format_mapping(value)}）")
        else:
            parts.append(f"{_text(key)}：{_text(value)}")
    return "；".join(parts)


def _format_text_top_values(values: Any) -> str:
    if not isinstance(values, dict) or not values:
        return "无"
    parts = []
    for column, items in values.items():
        if not isinstance(items, list) or not items:
            parts.append(f"{_text(column)}：无")
            continue
        formatted_items = []
        for item in items:
            if isinstance(item, dict):
                formatted_items.append(f"{_text(item.get('value'))}（{_text(item.get('count'))}）")
            else:
                formatted_items.append(_text(item))
        parts.append(f"{_text(column)}：{_join_values(formatted_items)}")
    return "；".join(parts)


def _join_values(values: Any) -> str:
    if values is None:
        return "无"
    if isinstance(values, dict):
        values = values.keys()
    if isinstance(values, (str, int, float, bool)):
        values = [values]
    try:
        items = list(values)
    except TypeError:
        items = [values]
    return "，".join(_text(item) for item in items) if items else "无"


def _text(value: Any) -> str:
    if value is None or value == "":
        return "无"
    return str(value)
