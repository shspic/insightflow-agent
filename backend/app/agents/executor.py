import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.state import AgentState
from app.models.file import File
from app.services.analysis_service import analyze_file
from app.services.chart_service import generate_charts
from app.services.ocr_service import get_or_run_image_ocr
from app.services.rag_service import answer_pdf_question
from app.services.report_service import generate_task_report


def execute_selected_tools(state: AgentState, db: Session) -> AgentState:
    if not state.selected_tools and state.task_type == "unsupported":
        state.tool_results["unsupported_handler"] = {
            "message": "当前任务类型暂不支持，未调用业务工具。",
        }
        return state

    for tool_name in state.selected_tools:
        state.tool_results[tool_name] = execute_tool(tool_name, state, db)
    return state


def execute_tool(tool_name: str, state: AgentState, db: Session) -> dict[str, Any]:
    if tool_name == "data_analysis_tool":
        return _run_data_analysis_tool(state, db)

    if tool_name == "chart_generation_tool":
        return _run_chart_generation_tool(state, db)

    if tool_name == "file_summary_tool":
        return _run_file_summary_tool(state, db)

    if tool_name == "pdf_retrieval_tool":
        return _run_pdf_retrieval_tool(state, db)

    if tool_name == "image_ocr_tool":
        return _run_image_ocr_tool(state, db)

    if tool_name == "report_writer_tool":
        return _run_report_writer_tool(state, db)

    raise ValueError(f"未知工具：{tool_name}")


def _run_data_analysis_tool(state: AgentState, db: Session) -> dict[str, Any]:
    file_record = _get_primary_file(state, db)
    analyzed = analyze_file(db, file_record)
    schema = _load_schema(analyzed.schema_json)
    return {
        "file_id": analyzed.id,
        "filename": analyzed.filename,
        "analysis_result": schema.get("analysis_result", {}),
    }


def _run_chart_generation_tool(state: AgentState, db: Session) -> dict[str, Any]:
    file_record = _get_primary_file(state, db)
    charted = generate_charts(db, file_record)
    schema = _load_schema(charted.schema_json)
    return {
        "file_id": charted.id,
        "filename": charted.filename,
        "charts": schema.get("charts", []),
    }


def _run_file_summary_tool(state: AgentState, db: Session) -> dict[str, Any]:
    file_record = _get_primary_file(state, db)
    return {
        "file_id": file_record.id,
        "filename": file_record.filename,
        "file_type": file_record.file_type,
        "status": file_record.status,
        "summary": file_record.summary or "该文件还没有摘要，请先解析文件。",
    }


def _run_pdf_retrieval_tool(state: AgentState, db: Session) -> dict[str, Any]:
    file_record = _get_primary_file(state, db)
    result = answer_pdf_question(db=db, file_record=file_record, question=state.user_input)
    return {
        "file_id": file_record.id,
        "filename": file_record.filename,
        "query": state.user_input,
        "answer": result["answer"],
        "sources": result["sources"],
        "results": result["results"],
        "message": result.get("message"),
    }


def _run_image_ocr_tool(state: AgentState, db: Session) -> dict[str, Any]:
    file_record = _get_primary_file(state, db)
    result = get_or_run_image_ocr(db=db, file_record=file_record)
    return {
        "file_id": file_record.id,
        "filename": file_record.filename,
        "file_type": file_record.file_type,
        "ocr_result": result,
    }


def _run_report_writer_tool(state: AgentState, db: Session) -> dict[str, Any]:
    llm_summary = state.tool_results.get("_llm_report_summary", {}).get("summary")
    report = generate_task_report(
        db=db,
        task_id=state.task_id,
        task_type=state.task_type,
        final_answer=state.final_answer,
        conclusion_override=llm_summary,
    )
    return {
        "task_id": state.task_id,
        "title": report["title"],
        "report_path": report["report_path"],
        "download_url": report["download_url"],
        "llm_summary_used": bool(llm_summary),
    }


def _get_primary_file(state: AgentState, db: Session) -> File:
    if not state.file_ids:
        raise ValueError("请至少选择一个文件")

    file_record = db.get(File, state.file_ids[0])
    if file_record is None:
        raise ValueError("文件不存在")

    return file_record


def _load_schema(schema_json: str | None) -> dict[str, Any]:
    if not schema_json:
        return {}

    try:
        data = json.loads(schema_json)
    except json.JSONDecodeError:
        return {}

    return data if isinstance(data, dict) else {}
