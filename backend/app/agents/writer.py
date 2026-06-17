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
    else:
        state.final_answer = "暂不支持该任务类型。当前支持：数据分析、图表生成、文件总结。"

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
        f"文件 ID：{result.get('file_id')}\n"
        f"文件名：{result.get('filename')}\n"
        f"文件类型：{result.get('file_type')}\n"
        f"当前状态：{result.get('status')}\n"
        f"摘要：{result.get('summary')}"
    )


def _join_or_empty(values: list[str]) -> str:
    return "、".join(values) if values else "无"
