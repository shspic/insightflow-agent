import json
import time
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.file import File
from app.models.task import Task
from app.models.tool_call import ToolCall
from app.services.analysis_service import analyze_file
from app.services.chart_service import generate_charts

TaskTool = Callable[[], str]


class TaskServiceError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def create_task(db: Session, user_input: str, file_ids: list[int]) -> Task:
    if not file_ids:
        raise TaskServiceError("请至少选择一个文件")

    file_id = file_ids[0]
    file_record = db.get(File, file_id)
    if file_record is None:
        raise TaskServiceError("文件不存在")

    task = Task(
        user_input=user_input,
        status="running",
        file_ids_json=json.dumps([file_id], ensure_ascii=False),
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    task_type = classify_task(user_input)
    task.task_type = task_type
    _record_tool_call(
        db=db,
        task_id=task.id,
        node_name="task_classifier",
        tool_name="rule_classifier",
        input_payload={"user_input": user_input},
        output_payload={"task_type": task_type},
        status="success",
        latency_ms=0,
    )

    try:
        if task_type == "data_analysis":
            final_answer = _run_with_trace(
                db=db,
                task_id=task.id,
                node_name="data_analysis",
                tool_name="analyze_file",
                input_payload={"file_id": file_id},
                tool=lambda: _handle_data_analysis(db, file_record),
            )
        elif task_type == "chart_generation":
            final_answer = _run_with_trace(
                db=db,
                task_id=task.id,
                node_name="chart_generation",
                tool_name="generate_charts",
                input_payload={"file_id": file_id},
                tool=lambda: _handle_chart_generation(db, file_record),
            )
        elif task_type == "file_summary":
            final_answer = _run_with_trace(
                db=db,
                task_id=task.id,
                node_name="file_summary",
                tool_name="summarize_file",
                input_payload={"file_id": file_id},
                tool=lambda: _handle_file_summary(file_record),
            )
        else:
            final_answer = _run_with_trace(
                db=db,
                task_id=task.id,
                node_name="unsupported",
                tool_name="unsupported_task",
                input_payload={"file_id": file_id, "user_input": user_input},
                tool=lambda: "暂不支持该任务类型。当前支持：数据分析、图表生成、文件总结。",
            )

        task.final_answer = final_answer
        task.status = "success"
    except Exception as exc:
        task.final_answer = f"任务执行失败：{exc}"
        task.status = "failed"

    db.commit()
    db.refresh(task)
    return task


def classify_task(user_input: str) -> str:
    text = user_input.strip()

    if any(keyword in text for keyword in ["分析", "统计", "数据概况", "缺失值", "字段"]):
        return "data_analysis"

    if any(keyword in text for keyword in ["图表", "可视化", "柱状图", "趋势图", "折线图"]):
        return "chart_generation"

    if any(keyword in text for keyword in ["总结", "概括", "摘要", "这个文件有什么"]):
        return "file_summary"

    return "unsupported"


def list_tasks(db: Session) -> list[Task]:
    return db.query(Task).order_by(Task.created_at.desc()).all()


def get_task(db: Session, task_id: int) -> Task | None:
    return db.get(Task, task_id)


def get_task_trace(db: Session, task_id: int) -> list[ToolCall]:
    return db.query(ToolCall).filter(ToolCall.task_id == task_id).order_by(ToolCall.created_at.asc()).all()


def task_to_response(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "user_input": task.user_input,
        "task_type": task.task_type,
        "status": task.status,
        "file_ids": _load_file_ids(task.file_ids_json),
        "final_answer": task.final_answer,
        "report_path": task.report_path,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _handle_data_analysis(db: Session, file_record: File) -> str:
    analyzed = analyze_file(db, file_record)
    schema = _load_schema(analyzed.schema_json)
    analysis = schema.get("analysis_result", {})
    return (
        f"数据分析完成：共 {analysis.get('row_count', 0)} 行、"
        f"{analysis.get('column_count', 0)} 列。"
        f"数值列：{_join_or_empty(analysis.get('numeric_columns', []))}；"
        f"文本列：{_join_or_empty(analysis.get('text_columns', []))}；"
        f"日期列：{_join_or_empty(analysis.get('date_columns', []))}。"
    )


def _handle_chart_generation(db: Session, file_record: File) -> str:
    charted = generate_charts(db, file_record)
    schema = _load_schema(charted.schema_json)
    charts = schema.get("charts", [])
    generated = [chart for chart in charts if not chart.get("skipped")]
    skipped = [chart for chart in charts if chart.get("skipped")]
    return f"图表生成完成：生成 {len(generated)} 张图表，跳过 {len(skipped)} 张。"


def _handle_file_summary(file_record: File) -> str:
    summary = file_record.summary or "该文件还没有摘要，请先解析文件。"
    return (
        f"文件 ID：{file_record.id}\n"
        f"文件名：{file_record.filename}\n"
        f"文件类型：{file_record.file_type}\n"
        f"当前状态：{file_record.status}\n"
        f"摘要：{summary}"
    )


def _run_with_trace(
    db: Session,
    task_id: int,
    node_name: str,
    tool_name: str,
    input_payload: dict[str, Any],
    tool: TaskTool,
) -> str:
    started_at = time.perf_counter()
    try:
        output = tool()
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        _record_tool_call(
            db=db,
            task_id=task_id,
            node_name=node_name,
            tool_name=tool_name,
            input_payload=input_payload,
            output_payload=None,
            status="failed",
            latency_ms=latency_ms,
            error_message=str(exc),
        )
        raise

    latency_ms = int((time.perf_counter() - started_at) * 1000)
    _record_tool_call(
        db=db,
        task_id=task_id,
        node_name=node_name,
        tool_name=tool_name,
        input_payload=input_payload,
        output_payload={"final_answer": output},
        status="success",
        latency_ms=latency_ms,
    )
    return output


def _record_tool_call(
    db: Session,
    task_id: int,
    node_name: str,
    tool_name: str,
    input_payload: dict[str, Any] | None,
    output_payload: dict[str, Any] | None,
    status: str,
    latency_ms: int,
    error_message: str | None = None,
) -> None:
    tool_call = ToolCall(
        task_id=task_id,
        node_name=node_name,
        tool_name=tool_name,
        input_json=json.dumps(input_payload, ensure_ascii=False) if input_payload is not None else None,
        output_json=json.dumps(output_payload, ensure_ascii=False) if output_payload is not None else None,
        status=status,
        latency_ms=latency_ms,
        error_message=error_message,
    )
    db.add(tool_call)
    db.commit()


def _load_schema(schema_json: str | None) -> dict[str, Any]:
    if not schema_json:
        return {}

    try:
        data = json.loads(schema_json)
    except json.JSONDecodeError:
        return {}

    return data if isinstance(data, dict) else {}


def _load_file_ids(file_ids_json: str | None) -> list[int]:
    if not file_ids_json:
        return []

    try:
        data = json.loads(file_ids_json)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    return [int(item) for item in data]


def _join_or_empty(values: list[str]) -> str:
    return "、".join(values) if values else "无"
