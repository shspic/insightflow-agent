from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RelationDiscoverRequest(BaseModel):
    file_ids: list[int] | None = Field(default=None)
    use_deepseek: bool = False

    @field_validator("file_ids")
    @classmethod
    def deduplicate_file_ids(cls, value: list[int] | None) -> list[int] | None:
        return list(dict.fromkeys(value)) if value is not None else None


class RelationMutationRequest(BaseModel):
    action: str
    relation_type: str | None = Field(default=None, max_length=80)
    custom_relation_type: str | None = Field(default=None, max_length=60)
    user_note: str | None = Field(default=None, max_length=500)


class FileRelationResponse(BaseModel):
    id: int
    workspace_id: int
    source_file_id: int
    source_filename: str
    target_file_id: int
    target_filename: str
    relation_type: str
    direction: str
    confidence: float
    confidence_level: str
    evidence: dict[str, Any]
    suggested_by: str
    status: str
    user_note: str | None
    supersedes_relation_id: int | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None


class RelationDiscoverResponse(BaseModel):
    status: str
    evaluated_pair_count: int
    created_count: int
    updated_count: int
    preserved_user_decision_count: int
    relations: list[FileRelationResponse]
