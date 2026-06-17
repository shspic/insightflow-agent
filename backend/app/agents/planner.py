PLAN_MAP = {
    "data_analysis": ["加载文件", "执行数据分析", "整理分析结果"],
    "chart_generation": ["加载文件", "生成图表", "整理图表结果"],
    "file_summary": ["加载文件", "读取文件摘要", "整理摘要结果"],
    "unsupported": ["返回暂不支持提示"],
}


def build_plan(task_type: str) -> list[str]:
    return PLAN_MAP.get(task_type, PLAN_MAP["unsupported"])
