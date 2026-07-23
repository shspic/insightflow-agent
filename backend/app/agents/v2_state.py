from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


AGENT_STATE_VERSION = "2.04"


class AgentStateV2(BaseModel):
    state_version: Literal["2.04"] = AGENT_STATE_VERSION
    task_id: int
    workspace_id: int
    owner_user_id: int
    user_request: str
    clarified_request: str
    assumptions: list[str] = Field(default_factory=list)
    selected_file_ids: list[int] = Field(default_factory=list)
    workspace_context: dict[str, Any] = Field(default_factory=dict)
    confirmed_relations: list[dict[str, Any]] = Field(default_factory=list)
    current_plan: dict[str, Any] = Field(default_factory=dict)
    current_step: dict[str, Any] | None = None
    completed_steps: list[str] = Field(default_factory=list)
    failed_steps: list[str] = Field(default_factory=list)
    analysis_findings: list[dict[str, Any]] = Field(default_factory=list)
    document_evidence: list[dict[str, Any]] = Field(default_factory=list)
    chart_assets: list[dict[str, Any]] = Field(default_factory=list)
    report_sections: list[str] = Field(default_factory=list)
    review_findings: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    retry_count: int = 0
    model_budget: int = Field(default=12, ge=0)
    tool_budget: int = Field(default=20, ge=0)
    final_result: dict[str, Any] = Field(default_factory=dict)
    report_id: int | None = None

    @model_validator(mode="after")
    def reject_sensitive_or_path_fields(self):
        forbidden = {
            "password",
            "token",
            "api_key",
            "secret",
            "file_path",
            "report_path",
            "absolute_path",
        }

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if str(key).lower() in forbidden:
                        raise ValueError(f"AgentState 不允许字段：{key}")
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(self.model_dump(exclude={"state_version"}))
        return self


def load_agent_state(raw: str) -> AgentStateV2:
    state = AgentStateV2.model_validate_json(raw)
    if state.state_version != AGENT_STATE_VERSION:
        raise ValueError(f"不支持的 AgentState 版本：{state.state_version}")
    return state
