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
    elif state.task_type == "image_extract":
        state.final_answer = _write_image_extract(state.tool_results.get("image_ocr_tool", {}))
    elif state.task_type == "report_generation":
        state.final_answer = _write_report_generation(state.tool_results.get("report_writer_tool", {}))
    elif state.task_type == "multi_file_analysis":
        state.final_answer = _write_multi_file_analysis(state.tool_results.get("multi_file_analysis_tool", {}))
    else:
        state.final_answer = "暂不支持该任务类型。当前支持：数据分析、图表生成、文件总结、PDF 文档问答、图片 OCR、报告生成、多文件综合分析。"

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


def _write_image_extract(result: dict[str, Any]) -> str:
    filename = _to_text(result.get("filename"))
    ocr_result = result.get("ocr_result") or {}
    text = (ocr_result.get("text") or "").strip()
    message = ocr_result.get("message")

    if text:
        return f"图片文件：{filename}\nOCR 识别文本：\n{text}"

    return f"图片文件：{filename}\nOCR 识别文本：未识别到明显文字。\n说明：{_to_text(message)}"


def _write_report_generation(result: dict[str, Any]) -> str:
    return (
        f"报告已生成。\n"
        f"报告标题：{_to_text(result.get('title'))}\n"
        f"报告路径：{_to_text(result.get('report_path'))}\n"
        f"下载提示：请在前端点击“下载报告”，或访问 {_to_text(result.get('download_url'))}。"
    )


def _write_multi_file_analysis(result: dict[str, Any]) -> str:
    files = result.get("files") or []
    table_results = result.get("table_results") or []
    pdf_results = result.get("pdf_results") or []
    image_results = result.get("image_results") or []
    errors = result.get("errors") or []

    sections = [
        "## 综合分析结果",
        "",
        f"本次共分析 {result.get('file_count', len(files))} 个文件。",
        "",
        "### 1. 文件清单",
        _format_file_list(files),
        "",
        "### 2. 表格数据概况",
        _format_table_results(table_results),
        "",
        "### 3. 图表结果摘要",
        _format_chart_summary(table_results),
        "",
        "### 4. PDF 文档依据或摘要",
        _format_pdf_results(pdf_results),
        "",
        "### 5. 图片 OCR 结果摘要",
        _format_image_results(image_results),
        "",
        "### 6. 关键发现",
        _format_key_findings(result),
        "",
        "### 7. 风险与限制",
        _format_errors(errors),
        "当前结果基于已上传文件和本地工具自动生成，PDF 检索、OCR 和表格统计都可能存在误差，重要结论需要人工复核。",
        "",
        "### 8. 下一步建议",
        "- 先核对表格中的缺失值、异常值和关键字段含义。",
        "- 对 PDF 引用片段回到原文页码复核。",
        "- 对 OCR 结果人工校对后再用于正式报告。",
    ]
    return "\n".join(sections)


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


def _format_file_list(files: list[dict[str, Any]]) -> str:
    if not files:
        return "未找到关联文件。"
    return "\n".join(
        f"- #{_to_text(file_item.get('file_id'))} {_to_text(file_item.get('filename'))} "
        f"（{_to_text(file_item.get('file_type'))}，状态：{_to_text(file_item.get('status'))}）"
        for file_item in files
    )


def _format_table_results(table_results: list[dict[str, Any]]) -> str:
    if not table_results:
        return "本次任务未包含表格文件。"

    lines = []
    for item in table_results:
        analysis = item.get("analysis_result") or {}
        if not analysis:
            lines.append(f"- {_to_text(item.get('filename'))}：{_to_text(item.get('error') or '暂无分析结果')}")
            continue
        lines.append(
            f"- {_to_text(item.get('filename'))}：{_to_text(analysis.get('row_count'))} 行、"
            f"{_to_text(analysis.get('column_count'))} 列；字段：{_join_or_empty(analysis.get('columns'))}；"
            f"数值列：{_join_or_empty(analysis.get('numeric_columns'))}；"
            f"文本列：{_join_or_empty(analysis.get('text_columns'))}。"
        )
    return "\n".join(lines)


def _format_chart_summary(table_results: list[dict[str, Any]]) -> str:
    chart_count = sum(len(item.get("charts") or []) for item in table_results)
    if chart_count == 0:
        return "本次任务未生成图表。"
    return "\n".join(
        f"- {_to_text(item.get('filename'))}：{len(item.get('charts') or [])} 个图表结果。"
        for item in table_results
        if item.get("charts")
    )


def _format_pdf_results(pdf_results: list[dict[str, Any]]) -> str:
    if not pdf_results:
        return "本次任务未包含 PDF 文件。"

    lines = []
    for item in pdf_results:
        sources = item.get("sources") or []
        if sources:
            source_summary = "；".join(
                f"第 {_to_text(source.get('page_number'))} 页：{_to_text(source.get('chunk_text'))[:120]}"
                for source in sources[:3]
            )
            lines.append(f"- {_to_text(item.get('filename'))}：{source_summary}")
        else:
            lines.append(f"- {_to_text(item.get('filename'))}：{_to_text(item.get('message') or item.get('summary') or item.get('error'))}")
    return "\n".join(lines)


def _format_image_results(image_results: list[dict[str, Any]]) -> str:
    if not image_results:
        return "本次任务未包含图片文件。"

    lines = []
    for item in image_results:
        ocr_result = item.get("ocr_result") or {}
        text = (ocr_result.get("text") or "").strip()
        lines.append(f"- {_to_text(item.get('filename'))}：{text[:160] if text else _to_text(item.get('error') or '未识别到明显文字')}")
    return "\n".join(lines)


def _format_key_findings(result: dict[str, Any]) -> str:
    findings = [
        f"- 表格文件：{result.get('table_file_count', 0)} 个，完成分析：{result.get('analysis_count', 0)} 个。",
        f"- PDF 文件：{result.get('pdf_file_count', 0)} 个，检索到引用片段：{result.get('pdf_result_count', 0)} 个。",
        f"- 图片文件：{result.get('image_file_count', 0)} 个，完成 OCR：{result.get('ocr_count', 0)} 个。",
    ]
    return "\n".join(findings)


def _format_errors(errors: list[str]) -> str:
    if not errors:
        return "未发现工具执行错误。"
    return "工具执行中存在以下问题：\n" + "\n".join(f"- {error}" for error in errors)
