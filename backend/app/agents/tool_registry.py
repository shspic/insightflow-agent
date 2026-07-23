import json
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agents.v2_state import AgentStateV2
from app.models.task import Task
from app.models.task_step import TaskStep
from app.models.tool_call import ToolCall
from app.services.security_service import sanitize_details
from app.services.task_event_service import append_task_event
from app.services.workspace_service import safe_public_text


class ToolExecutionError(Exception):
    def __init__(self, message: str, code: str = "TOOL_EXECUTION_FAILED") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class FileIdsInput(BaseModel):
    file_ids: list[int] = Field(min_length=1, max_length=20)


class DataAnalysisInput(FileIdsInput):
    generate_charts: bool = True


class DocumentRetrievalInput(FileIdsInput):
    query: str = Field(min_length=1, max_length=5000)
    top_k: int = Field(default=5, ge=1, le=20)
    retrieval_mode: str = Field(default="auto", pattern=r"^(auto|vector|keyword)$")


class ReportToolInput(BaseModel):
    task_id: int


class QualityReviewInput(BaseModel):
    task_id: int


class GenericToolOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    allowed_agent_types: frozenset[str]
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    timeout_seconds: int
    idempotent: bool
    supports_cancellation: bool
    cost_category: str
    enabled: bool
    handler: Callable[["ToolContext", BaseModel], dict[str, Any]]


@dataclass
class ToolContext:
    db: Session
    task: Task
    step: TaskStep
    state: AgentStateV2


def _registry() -> dict[str, ToolDefinition]:
    from app.agents.v2_tools import (
        run_document_retrieval,
        run_multi_table_analysis,
        run_quality_review,
        run_structured_report,
        run_workspace_context_lookup,
    )

    definitions = [
        ToolDefinition(
            "workspace_context_lookup",
            "读取 V2-03 Profile、关系和 Workspace Context",
            frozenset({"file_understanding_agent"}),
            FileIdsInput,
            GenericToolOutput,
            30,
            True,
            True,
            "low",
            True,
            run_workspace_context_lookup,
        ),
        ToolDefinition(
            "preset_multi_table_analysis",
            "执行预设 Pandas 多表统计和鉴权图表生成",
            frozenset({"data_analysis_agent"}),
            DataAnalysisInput,
            GenericToolOutput,
            120,
            True,
            True,
            "medium",
            True,
            run_multi_table_analysis,
        ),
        ToolDefinition(
            "selected_document_retrieval",
            "只检索当前任务选择的 PDF 和 Markdown 分块",
            frozenset({"document_research_agent"}),
            DocumentRetrievalInput,
            GenericToolOutput,
            90,
            True,
            True,
            "medium",
            True,
            run_document_retrieval,
        ),
        ToolDefinition(
            "structured_markdown_report",
            "根据结构化 Agent 输出幂等生成 Markdown 报告",
            frozenset({"report_agent"}),
            ReportToolInput,
            GenericToolOutput,
            60,
            True,
            True,
            "low",
            True,
            run_structured_report,
        ),
        ToolDefinition(
            "deterministic_quality_review",
            "确定性审核数字、引用、步骤、章节和敏感信息",
            frozenset({"quality_review_agent"}),
            QualityReviewInput,
            GenericToolOutput,
            60,
            True,
            True,
            "low",
            True,
            run_quality_review,
        ),
    ]
    return {item.name: item for item in definitions}


def get_tool_definition(name: str) -> ToolDefinition:
    definition = _registry().get(name)
    if definition is None or not definition.enabled:
        raise ToolExecutionError("工具未注册或已停用", "UNREGISTERED_TOOL")
    return definition


def validate_agent_tool(agent_type: str, tool_name: str) -> ToolDefinition:
    definition = get_tool_definition(tool_name)
    if agent_type not in definition.allowed_agent_types:
        raise ToolExecutionError("当前 Agent 无权调用该工具", "TOOL_PERMISSION_DENIED")
    return definition


def execute_registered_tool(
    context: ToolContext,
    *,
    agent_type: str,
    tool_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    definition = validate_agent_tool(agent_type, tool_name)
    if context.task.cancellation_requested_at is not None:
        raise ToolExecutionError("任务已请求取消", "TASK_CANCELLED")
    if context.state.tool_budget <= 0:
        raise ToolExecutionError("任务工具调用预算已用尽", "TOOL_BUDGET_EXHAUSTED")
    context.state.tool_budget -= 1
    try:
        validated_input = definition.input_schema.model_validate(payload)
    except Exception as exc:
        raise ToolExecutionError(f"工具输入未通过 Schema 校验：{exc}", "INVALID_TOOL_INPUT") from exc

    trace = ToolCall(
        task_id=context.task.id,
        node_name=agent_type,
        tool_name=tool_name,
        input_json=json.dumps(
            sanitize_details(validated_input.model_dump()),
            ensure_ascii=False,
            default=str,
        ),
        status="running",
    )
    context.db.add(trace)
    context.db.flush()
    append_task_event(
        context.db,
        task_id=context.task.id,
        event_type="tool_started",
        message=f"{agent_type} 开始调用 {tool_name}",
        status=context.task.status,
        progress_percent=context.task.progress_percent,
        step_id=context.step.id,
        agent_type=agent_type,
        payload={"tool_name": tool_name, "tool_call_id": trace.id},
    )
    try:
        raw_output = definition.handler(context, validated_input)
        output = definition.output_schema.model_validate(raw_output).model_dump()
    except ToolExecutionError as exc:
        trace.status = "failed"
        trace.error_message = safe_public_text(exc.message)
        append_task_event(
            context.db,
            task_id=context.task.id,
            event_type="tool_failed",
            message=f"{tool_name} 调用失败。",
            status=context.task.status,
            progress_percent=context.task.progress_percent,
            step_id=context.step.id,
            agent_type=agent_type,
            payload={"tool_name": tool_name, "error_code": exc.code},
        )
        context.db.flush()
        raise
    except Exception as exc:
        trace.status = "failed"
        trace.error_message = safe_public_text(str(exc))
        context.db.flush()
        raise ToolExecutionError(str(exc)) from exc

    trace.status = "success"
    trace.output_json = json.dumps(
        _summarize_output(output),
        ensure_ascii=False,
        default=str,
    )
    append_task_event(
        context.db,
        task_id=context.task.id,
        event_type="tool_completed",
        message=f"{tool_name} 调用完成",
        status=context.task.status,
        progress_percent=context.task.progress_percent,
        step_id=context.step.id,
        agent_type=agent_type,
        payload={"tool_name": tool_name, "tool_call_id": trace.id, "status": output["status"]},
    )
    context.db.flush()
    return output


def registered_tool_names() -> set[str]:
    return set(_registry())


def _summarize_output(value: dict[str, Any]) -> dict[str, Any]:
    summarized = sanitize_details(value)
    for key in ("content", "document_text", "raw_output"):
        summarized.pop(key, None)
    text = json.dumps(summarized, ensure_ascii=False, default=str)
    if len(text) <= 12000:
        return summarized
    return {"status": value.get("status"), "summary": text[:12000] + "…"}
