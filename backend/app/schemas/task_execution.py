from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


AgentType = Literal[
    "file_understanding_agent",
    "data_analysis_agent",
    "document_research_agent",
    "report_agent",
    "quality_review_agent",
]

ToolName = Literal[
    "workspace_context_lookup",
    "preset_multi_table_analysis",
    "selected_document_retrieval",
    "structured_markdown_report",
    "deterministic_quality_review",
]


class PlanStepInput(BaseModel):
    step_key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    agent_type: AgentType
    tool_name: ToolName
    depends_on: list[str] = Field(default_factory=list, max_length=10)
    parameters: dict[str, Any] = Field(default_factory=dict)
    optional: bool = False


class TaskDraftCreate(BaseModel):
    user_request: str = Field(min_length=1, max_length=5000)
    selected_file_ids: list[int] = Field(default_factory=list, max_length=20)
    use_deepseek: bool = False
    report_preferences: dict[str, Any] | None = None

    @field_validator("selected_file_ids")
    @classmethod
    def deduplicate_ids(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))


class ClarificationAnswerRequest(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)
    continue_with_recommendation: bool = False


class PlanPatchRequest(BaseModel):
    goal: str | None = Field(default=None, min_length=1, max_length=2000)
    selected_file_ids: list[int] | None = Field(default=None, max_length=20)
    steps: list[PlanStepInput] | None = Field(default=None, min_length=1, max_length=10)
    assumptions: list[str] | None = Field(default=None, max_length=20)


class TaskEventResponse(BaseModel):
    id: int
    task_id: int
    event_type: str
    event_version: str
    step_id: int | None
    agent_type: str | None
    status: str | None
    progress_percent: int | None
    message: str
    payload: dict[str, Any] | None
    created_at: datetime


class TaskStepResponse(BaseModel):
    id: int
    step_key: str
    step_order: int
    agent_type: str
    tool_name: str
    title: str
    description: str | None
    status: str
    progress_percent: int
    retry_count: int
    max_retries: int
    depends_on: list[str]
    output: dict[str, Any] | None
    error_code: str | None
    error_message: str | None


class TaskPlanResponse(BaseModel):
    id: int
    task_id: int
    version: int
    status: str
    goal: str
    assumptions: list[str]
    steps: list[dict[str, Any]]
    selected_file_ids: list[int]
    estimated_model_calls: int
    estimated_tool_calls: int
    created_by: str
    created_at: datetime
    confirmed_at: datetime | None


class TaskClarificationResponse(BaseModel):
    id: int
    round_number: int
    questions: list[dict[str, Any]]
    answers: dict[str, Any] | None
    status: str
    created_at: datetime
    answered_at: datetime | None


class TaskExecutionDetail(BaseModel):
    id: int
    workspace_id: int
    user_request: str
    task_type: str | None
    status: str
    selected_file_ids: list[int]
    current_plan: TaskPlanResponse | None
    clarifications: list[TaskClarificationResponse]
    steps: list[TaskStepResponse]
    progress_percent: int
    current_step_id: int | None
    cancellation_requested_at: datetime | None
    retry_count: int
    max_retries: int
    result_summary: dict[str, Any] | None
    final_result: dict[str, Any] | None
    report_id: int | None
    has_report: bool
    latest_events: list[TaskEventResponse]
    model_available: bool
    created_at: datetime
    updated_at: datetime


class QualityReviewOutput(BaseModel):
    status: Literal["passed", "retry_required", "passed_with_warnings", "failed"]
    issues: list[dict[str, Any]] = Field(default_factory=list)
    retry_step_ids: list[int] = Field(default_factory=list)
