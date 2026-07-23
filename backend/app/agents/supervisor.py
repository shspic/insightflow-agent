import json
from typing import Any

from pydantic import BaseModel, Field

from app.agents.prompt_registry import get_prompt
from app.agents.tool_registry import validate_agent_tool
from app.schemas.task_execution import PlanStepInput
from app.services.llm_service import call_llm, is_llm_ready, safe_json_dumps


class SupervisorPlan(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    steps: list[PlanStepInput] = Field(min_length=3, max_length=10)
    estimated_model_calls: int = Field(default=0, ge=0, le=12)
    estimated_tool_calls: int = Field(default=0, ge=1, le=20)


class SupervisorPlanResult(BaseModel):
    plan: SupervisorPlan
    fallback_used: bool
    model_attempted: bool
    model_message: str | None = None
    token_usage: dict[str, Any] | None = None
    duration_ms: int | None = None


class SupervisorAgent:
    agent_type = "supervisor"

    def generate_plan(
        self,
        *,
        user_request: str,
        workspace_context: dict[str, Any],
        use_deepseek: bool,
    ) -> SupervisorPlanResult:
        fallback = self._deterministic_plan(user_request, workspace_context)
        if not use_deepseek or not is_llm_ready():
            return SupervisorPlanResult(
                plan=fallback,
                fallback_used=use_deepseek,
                model_attempted=False,
                model_message="DeepSeek 未启用或不可用，使用确定性基础计划。",
            )

        prompt = get_prompt("planning")
        result = call_llm(
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Prompt {prompt.prompt_name}@{prompt.version}。"
                        "只返回严格 JSON，不得生成 Python、Shell、SQL、URL 或未注册工具。"
                        "步骤只能使用给定 Agent 和工具组合，保留报告与质量审核。"
                    ),
                },
                {
                    "role": "user",
                    "content": safe_json_dumps(
                        {
                            "user_request": user_request,
                            "workspace_context": workspace_context,
                            "allowed_plan": fallback.model_dump(),
                        },
                        max_length=12000,
                    ),
                },
            ],
            temperature=0,
            max_tokens=1600,
        )
        if result.success and result.content:
            try:
                candidate = SupervisorPlan.model_validate_json(result.content)
                validate_plan_steps(candidate.steps)
                return SupervisorPlanResult(
                    plan=candidate,
                    fallback_used=False,
                    model_attempted=True,
                    token_usage=result.token_usage,
                    duration_ms=result.duration_ms,
                )
            except Exception as exc:
                return SupervisorPlanResult(
                    plan=fallback,
                    fallback_used=True,
                    model_attempted=True,
                    model_message=f"DeepSeek 计划未通过 Schema 校验，已降级：{exc}",
                    token_usage=result.token_usage,
                    duration_ms=result.duration_ms,
                )
        return SupervisorPlanResult(
            plan=fallback,
            fallback_used=True,
            model_attempted=True,
            model_message=result.message or "DeepSeek 计划调用失败，已降级。",
            token_usage=result.token_usage,
            duration_ms=result.duration_ms,
        )

    def _deterministic_plan(
        self,
        user_request: str,
        workspace_context: dict[str, Any],
    ) -> SupervisorPlan:
        files = workspace_context.get("files") or []
        file_types = {(item.get("file_type") or "").lower() for item in files}
        steps: list[PlanStepInput] = [
            PlanStepInput(
                step_key="understand_files",
                title="汇总文件理解结果",
                description="读取 V2-03 Profile、角色、质量问题和已确认关系。",
                agent_type="file_understanding_agent",
                tool_name="workspace_context_lookup",
            )
        ]
        report_dependencies = ["understand_files"]
        if file_types & {"csv", "xlsx"}:
            steps.append(
                PlanStepInput(
                    step_key="analyze_tables",
                    title="分析表格数据",
                    description="执行预设 Pandas 多工作表统计并生成可鉴权图表。",
                    agent_type="data_analysis_agent",
                    tool_name="preset_multi_table_analysis",
                    depends_on=["understand_files"],
                    parameters={"generate_charts": True},
                    optional=True,
                )
            )
            report_dependencies.append("analyze_tables")
        if file_types & {"pdf", "md", "markdown"}:
            steps.append(
                PlanStepInput(
                    step_key="research_documents",
                    title="检索文档证据",
                    description="只检索当前任务选择的 PDF 和 Markdown 分块并保留引用定位。",
                    agent_type="document_research_agent",
                    tool_name="selected_document_retrieval",
                    depends_on=["understand_files"],
                    parameters={"top_k": 5, "retrieval_mode": "auto"},
                    optional=True,
                )
            )
            report_dependencies.append("research_documents")
        steps.extend(
            [
                PlanStepInput(
                    step_key="write_report",
                    title="生成结构化 Markdown 报告",
                    description="只使用结构化结论、引用和图表资产生成报告。",
                    agent_type="report_agent",
                    tool_name="structured_markdown_report",
                    depends_on=report_dependencies,
                ),
                PlanStepInput(
                    step_key="review_quality",
                    title="审核结果质量",
                    description="确定性审核数字、引用、步骤、章节和敏感信息。",
                    agent_type="quality_review_agent",
                    tool_name="deterministic_quality_review",
                    depends_on=["write_report"],
                ),
            ]
        )
        validate_plan_steps(steps)
        assumptions = []
        if len(files) > 1 and not workspace_context.get("confirmed_relations"):
            assumptions.append("未确认文件关系；只做文件级并列分析，不自动执行行级拼接。")
        if workspace_context.get("unready_files"):
            assumptions.append("部分文件 Profile 未 ready；执行时只使用现有安全元数据并记录限制。")
        return SupervisorPlan(
            goal=user_request.strip(),
            assumptions=assumptions,
            steps=steps,
            estimated_model_calls=1 if use_semantic_review(user_request) else 0,
            estimated_tool_calls=len(steps),
        )


def validate_plan_steps(steps: list[PlanStepInput]) -> None:
    if not 1 <= len(steps) <= 10:
        raise ValueError("计划步骤数量必须在 1 到 10 之间")
    keys = [step.step_key for step in steps]
    if len(keys) != len(set(keys)):
        raise ValueError("计划 step_key 不能重复")
    required_agents = {
        "file_understanding_agent",
        "report_agent",
        "quality_review_agent",
    }
    if not required_agents.issubset({step.agent_type for step in steps}):
        raise ValueError("计划必须保留文件理解、报告和质量审核步骤")
    allowed_parameters = {
        "workspace_context_lookup": set(),
        "preset_multi_table_analysis": {"generate_charts"},
        "selected_document_retrieval": {"top_k", "retrieval_mode"},
        "structured_markdown_report": set(),
        "deterministic_quality_review": set(),
    }
    seen: set[str] = set()
    for step in steps:
        validate_agent_tool(step.agent_type, step.tool_name)
        if not set(step.parameters).issubset(allowed_parameters[step.tool_name]):
            raise ValueError(f"步骤 {step.step_key} 包含不受支持的参数")
        if any(dependency not in seen for dependency in step.depends_on):
            raise ValueError(f"步骤 {step.step_key} 的依赖必须位于它之前")
        seen.add(step.step_key)
    if steps[-1].agent_type != "quality_review_agent":
        raise ValueError("Quality Review 必须是最后一步")


def use_semantic_review(user_request: str) -> bool:
    return len(user_request.strip()) > 20
