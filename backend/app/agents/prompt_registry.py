from dataclasses import dataclass


@dataclass(frozen=True)
class PromptDefinition:
    prompt_name: str
    version: str
    purpose: str
    input_schema: str
    output_schema: str


PROMPTS = {
    item.prompt_name: item
    for item in [
        PromptDefinition("clarification", "2.04.1", "判断必要追问", "ClarificationInput", "ClarificationOutput"),
        PromptDefinition("planning", "2.04.1", "生成受限结构化计划", "PlanningInput", "TaskPlanDraft"),
        PromptDefinition(
            "file_understanding_agent",
            "2.04.1",
            "汇总 Profile 与 Workspace Context",
            "AgentStateV2",
            "FileUnderstandingOutput",
        ),
        PromptDefinition(
            "data_analysis_agent",
            "2.04.1",
            "组织预设 Pandas 结果",
            "AgentStateV2",
            "DataAnalysisOutput",
        ),
        PromptDefinition(
            "document_research_agent",
            "2.04.1",
            "组织文件检索证据",
            "AgentStateV2",
            "DocumentResearchOutput",
        ),
        PromptDefinition(
            "report_agent",
            "2.04.1",
            "基于结构化输出生成 Markdown",
            "AgentStateV2",
            "ReportOutput",
        ),
        PromptDefinition(
            "quality_review",
            "2.04.1",
            "审核数字、引用、步骤和用户要求",
            "QualityReviewInput",
            "QualityReviewOutput",
        ),
    ]
}


def get_prompt(name: str) -> PromptDefinition:
    try:
        return PROMPTS[name]
    except KeyError as exc:
        raise ValueError(f"未注册 Prompt：{name}") from exc
