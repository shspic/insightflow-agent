from typing import Any

from pydantic import BaseModel, Field, field_validator


class WorkspaceContextRequest(BaseModel):
    file_ids: list[int] | None = Field(default=None)

    @field_validator("file_ids")
    @classmethod
    def deduplicate_file_ids(cls, value: list[int] | None) -> list[int] | None:
        return list(dict.fromkeys(value)) if value is not None else None


class WorkspaceContextResponse(BaseModel):
    context_version: str
    workspace: dict[str, Any]
    user_goal: str | None
    selected_file_ids: list[int]
    files: list[dict[str, Any]]
    confirmed_relations: list[dict[str, Any]]
    pending_high_confidence_relations: list[dict[str, Any]]
    data_quality_issues: list[dict[str, Any]]
    available_tools: list[str]
    unready_files: list[dict[str, Any]]
    limits: dict[str, Any]
