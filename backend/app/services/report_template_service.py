from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ReportTemplate:
    template_key: str
    display_name: str
    description: str
    required_sections: tuple[str, ...]
    optional_sections: tuple[str, ...]
    recommended_agents: tuple[str, ...]
    output_constraints: tuple[str, ...]


_COMMON_CONSTRAINTS = (
    "不得重新计算 Data Analysis Agent 已产出的数字",
    "引用必须保留来源文件和页码或章节定位",
    "必须披露异常、风险、假设、限制和 Quality Review 状态",
)

REPORT_TEMPLATES = {
    "comprehensive_analysis": ReportTemplate(
        template_key="comprehensive_analysis",
        display_name="综合分析报告",
        description="适用于表格、文档和图片混合资料的完整分析。",
        required_sections=(
            "执行摘要",
            "任务与资料范围",
            "分析方法",
            "关键发现",
            "数据质量与异常风险",
            "图表与表格",
            "引用与证据",
            "行动建议",
            "假设与限制",
            "Quality Review",
        ),
        optional_sections=("多文件综合结论", "附录"),
        recommended_agents=("data_analysis_agent", "document_research_agent", "report_agent"),
        output_constraints=_COMMON_CONSTRAINTS,
    ),
    "student_research": ReportTemplate(
        template_key="student_research",
        display_name="学生调研报告",
        description="适用于课程作业、学生研究与小型调研。",
        required_sections=(
            "摘要",
            "研究问题",
            "资料与方法",
            "分析结果",
            "讨论",
            "引用与证据",
            "结论与建议",
            "假设与限制",
            "Quality Review",
        ),
        optional_sections=("图表与表格", "附录"),
        recommended_agents=("document_research_agent", "data_analysis_agent", "report_agent"),
        output_constraints=_COMMON_CONSTRAINTS,
    ),
    "job_application_analysis": ReportTemplate(
        template_key="job_application_analysis",
        display_name="求职资料分析",
        description="适用于简历、职位说明和求职材料的匹配与改进分析。",
        required_sections=(
            "匹配摘要",
            "岗位要求",
            "候选人证据",
            "优势与差距",
            "风险与待确认事项",
            "引用与证据",
            "行动建议",
            "假设与限制",
            "Quality Review",
        ),
        optional_sections=("关键词覆盖", "面试准备"),
        recommended_agents=("document_research_agent", "report_agent"),
        output_constraints=_COMMON_CONSTRAINTS,
    ),
}


def get_report_template(template_key: str | None) -> ReportTemplate:
    key = template_key or "comprehensive_analysis"
    template = REPORT_TEMPLATES.get(key)
    if template is None:
        raise ValueError("报告模板不在受控注册表中")
    return template


def list_report_templates() -> list[dict]:
    return [asdict(item) for item in REPORT_TEMPLATES.values()]
