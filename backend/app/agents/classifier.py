DOCUMENT_QA_KEYWORDS = ["PDF", "文档", "依据", "来源", "引用", "这份文件里", "文件中", "资料中", "说明", "规定", "内容有哪些"]


def classify_task(user_input: str, file_type: str | None = None) -> str:
    text = user_input.strip()
    normalized_file_type = (file_type or "").lower()

    if normalized_file_type == "pdf" and any(keyword in text for keyword in DOCUMENT_QA_KEYWORDS):
        return "document_qa"

    if any(keyword in text for keyword in ["分析", "统计", "数据概况", "缺失值", "字段"]):
        return "data_analysis"

    if any(keyword in text for keyword in ["图表", "可视化", "柱状图", "趋势图", "折线图"]):
        return "chart_generation"

    if any(keyword in text for keyword in ["总结", "概括", "摘要", "这个文件有什么"]):
        return "file_summary"

    return "unsupported"
