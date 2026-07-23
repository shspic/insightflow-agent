from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class FileUnderstandOptions(BaseModel):
    use_deepseek: bool = False
    run_ocr: bool = True


class BatchFileUnderstandRequest(BaseModel):
    file_ids: list[int] = Field(min_length=1)
    options: FileUnderstandOptions = Field(default_factory=FileUnderstandOptions)

    @field_validator("file_ids")
    @classmethod
    def deduplicate_file_ids(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))


class FileUnderstandResult(BaseModel):
    file_id: int
    profile_id: int | None
    profile_version: int | None
    status: str
    message: str
    error_code: str | None = None


class BatchFileUnderstandResponse(BaseModel):
    status: str
    results: list[FileUnderstandResult]


class FileProfileUpdate(BaseModel):
    confirmed_role: str | None = Field(default=None, max_length=80)
    custom_role: str | None = Field(default=None, max_length=60)
    user_tags: list[str] | None = Field(default=None, max_length=20)


class FileProfileResponse(BaseModel):
    id: int
    file_id: int
    workspace_id: int
    profile_version: int
    status: str
    file_category: str | None
    detected_mime_type: str | None
    language: str | None
    title: str | None
    summary: str | None
    structure: dict[str, Any]
    statistics: dict[str, Any]
    quality_issues: list[dict[str, Any]]
    suggested_role: str | None
    confirmed_role: str | None
    effective_role: str | None
    system_tags: list[str]
    user_tags: list[str]
    confidence: float | None
    parser_name: str | None
    parser_version: str | None
    model_provider: str | None
    model_name: str | None
    prompt_version: str | None
    model_latency_ms: int | None
    fallback_used: bool
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class FileProfileVersionsResponse(BaseModel):
    file_id: int
    profiles: list[FileProfileResponse]
