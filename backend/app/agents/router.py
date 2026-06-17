TOOL_MAP = {
    "data_analysis": ["data_analysis_tool"],
    "chart_generation": ["chart_generation_tool"],
    "file_summary": ["file_summary_tool"],
    "document_qa": ["pdf_retrieval_tool"],
    "image_extract": ["image_ocr_tool"],
    "report_generation": ["report_writer_tool"],
    "unsupported": [],
}


def select_tools(task_type: str) -> list[str]:
    return TOOL_MAP.get(task_type, [])
