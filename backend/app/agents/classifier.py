def classify_task(user_input: str) -> str:
    text = user_input.strip()

    if any(keyword in text for keyword in ["分析", "统计", "数据概况", "缺失值", "字段"]):
        return "data_analysis"

    if any(keyword in text for keyword in ["图表", "可视化", "柱状图", "趋势图", "折线图"]):
        return "chart_generation"

    if any(keyword in text for keyword in ["总结", "概括", "摘要", "这个文件有什么"]):
        return "file_summary"

    return "unsupported"
