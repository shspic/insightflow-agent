DOCUMENT_QA_KEYWORDS = ["PDF", "文档", "依据", "来源", "引用", "这份文件里", "文件中", "资料中", "说明", "规定", "内容有哪些"]
IMAGE_EXTRACT_KEYWORDS = ["识别", "图片", "截图", "这张图", "图片里", "图中", "OCR", "文字", "提取文字"]
REPORT_GENERATION_KEYWORDS = ["报告", "生成报告", "分析报告", "总结成报告", "整理成报告", "输出报告"]
IMAGE_FILE_TYPES = {"png", "jpg", "jpeg"}


def classify_task(user_input: str, file_type: str | None = None) -> str:
    text = user_input.strip()
    normalized_file_type = (file_type or "").lower()

    if any(keyword in text for keyword in REPORT_GENERATION_KEYWORDS):
        return "report_generation"

    if _can_route_document_qa(normalized_file_type) and any(keyword in text for keyword in DOCUMENT_QA_KEYWORDS):
        return "document_qa"

    if normalized_file_type in IMAGE_FILE_TYPES and any(keyword in text for keyword in IMAGE_EXTRACT_KEYWORDS):
        return "image_extract"

    if any(keyword in text for keyword in ["分析", "统计", "数据概况", "缺失值", "字段"]):
        return "data_analysis"

    if any(keyword in text for keyword in ["图表", "可视化", "柱状图", "趋势图", "折线图"]):
        return "chart_generation"

    if any(keyword in text for keyword in ["总结", "概括", "摘要", "这个文件有什么"]):
        return "file_summary"

    return "unsupported"


def _can_route_document_qa(file_type: str) -> bool:
    if file_type == "pdf":
        return True
    if file_type in IMAGE_FILE_TYPES or file_type in {"csv", "xlsx"}:
        return False
    return True
