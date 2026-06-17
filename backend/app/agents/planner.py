PLAN_MAP = {
    "data_analysis": ["加载文件", "执行数据分析", "整理分析结果"],
    "chart_generation": ["加载文件", "生成图表", "整理图表结果"],
    "file_summary": ["加载文件", "读取文件摘要", "整理摘要结果"],
    "document_qa": ["加载 PDF 文档", "检索相关片段", "整理引用来源", "生成回答"],
    "image_extract": ["加载图片文件", "执行 OCR 识别", "整理识别结果", "返回图片文字摘要"],
    "unsupported": ["返回暂不支持提示"],
}


def build_plan(task_type: str) -> list[str]:
    return PLAN_MAP.get(task_type, PLAN_MAP["unsupported"])
