PLAN_MAP = {
    "data_analysis": ["加载文件", "执行数据分析", "整理分析结果"],
    "chart_generation": ["加载文件", "生成图表", "整理图表结果"],
    "file_summary": ["加载文件", "读取文件摘要", "整理摘要结果"],
    "document_qa": ["加载 PDF 文档", "检索相关片段", "整理引用来源", "生成回答"],
    "image_extract": ["加载图片文件", "执行 OCR 识别", "整理识别结果", "返回图片文字摘要"],
    "report_generation": ["加载任务和文件信息", "收集数据分析结果", "收集图表结果", "收集 PDF 引用", "收集 OCR 结果", "生成 Markdown 报告"],
    "multi_file_analysis": [
        "加载多个文件信息",
        "按文件类型分组",
        "对表格文件执行数据分析",
        "对表格文件生成图表",
        "对 PDF 文件执行检索或摘要",
        "对图片文件执行 OCR 或复用 OCR 结果",
        "汇总各类结果",
        "生成综合回答",
    ],
    "unsupported": ["返回暂不支持提示"],
}


def build_plan(task_type: str) -> list[str]:
    return PLAN_MAP.get(task_type, PLAN_MAP["unsupported"])
