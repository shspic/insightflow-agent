from typing import Any

from app.agents.state import AgentState


def write_result(state: AgentState) -> AgentState:
    if state.errors:
        state.final_answer = f"任务执行失败：{state.errors[-1]}"
        return state

    if state.task_type == "data_analysis":
        state.final_answer = _write_data_analysis(state.tool_results.get("data_analysis_tool", {}))
    elif state.task_type == "chart_generation":
        state.final_answer = _write_chart_generation(state.tool_results.get("chart_generation_tool", {}))
    elif state.task_type == "file_summary":
        state.final_answer = _write_file_summary(state.tool_results.get("file_summary_tool", {}))
    elif state.task_type == "document_qa":
        state.final_answer = _write_document_qa(state.tool_results.get("pdf_retrieval_tool", {}))
    else:
        state.final_answer = "暂不支持该任务类型。当前支持：数据分析、图表生成、文件总结、PDF 文档问答。"

    return state


def _write_data_analysis(result: dict[str, Any]) -> str:
    analysis = result.get("analysis_result", {})
    return (
        f"数据分析完成：共 {analysis.get('row_count', 0)} 行、"
        f"{analysis.get('column_count', 0)} 列。"
        f"数值列：{_join_or_empty(analysis.get('numeric_columns', []))}；"
        f"文本列：{_join_or_empty(analysis.get('text_columns', []))}；"
        f"日期列：{_join_or_empty(analysis.get('date_columns', []))}。"
    )


def _write_chart_generation(result: dict[str, Any]) -> str:
    charts = result.get("charts", [])
    generated = [chart for chart in charts if not chart.get("skipped")]
    skipped = [chart for chart in charts if chart.get("skipped")]
    return f"图表生成完成：生成 {len(generated)} 张图表，跳过 {len(skipped)} 张。"


def _write_file_summary(result: dict[str, Any]) -> str:
    return (
        f"文件 ID：{_to_text(result.get('file_id'))}\n"
        f"文件名：{_to_text(result.get('filename'))}\n"
        f"文件类型：{_to_text(result.get('file_type'))}\n"
        f"当前状态：{_to_text(result.get('status'))}\n"
        f"摘要：{_to_text(result.get('summary'))}"
    )


def _write_document_qa(result: dict[str, Any]) -> str:
    answer = result.get("answer") or "未在该 PDF 中找到与问题相关的内容。"
    sources = result.get("sources") or []
    if not sources:
        return f"{answer}\n\n引用来源：无"

    source_lines = ["引用来源："]
    for index, source in enumerate(sources, start=1):
        source_lines.append(
            f"{index}. 文件：{_to_text(source.get('filename'))}；"
            f"页码：第 {_to_text(source.get('page_number'))} 页；"
            f"片段：{_to_text(source.get('chunk_text'))}"
        )

    return f"{answer}\n\n" + "\n".join(source_lines)


def _join_or_empty(values: Any) -> str:
    if values is None:
        return "无"

    if isinstance(values, dict):
        values = values.keys()
    elif isinstance(values, (str, int, float, bool)):
        values = [values]

    try:
        items = list(values)
    except TypeError:
        items = [values]

    if not items:
        return "无"

    return "、".join(_to_text(item) for item in items)


def _to_text(value: Any) -> str:
    if value is None:
        return "无"

    return str(value)
