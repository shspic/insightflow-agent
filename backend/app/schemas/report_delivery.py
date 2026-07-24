from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CorrectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str | None = Field(default=None, max_length=1000)
    corrected_value: str | None = Field(default=None, max_length=500)
    citation_id: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("*")
    @classmethod
    def reject_executable_content(cls, value: str | None) -> str | None:
        if value is None:
            return value
        lowered = value.casefold()
        forbidden = ("```", "<script", "powershell", "subprocess", "os.system", "tool_name", "prompt_name")
        if any(token in lowered for token in forbidden):
            raise ValueError("纠正说明不能包含代码、工具或 Prompt 控制内容")
        return value.strip()


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: int | None = None
    feedback_type: Literal[
        "like",
        "dislike",
        "correction",
        "regenerate_request",
        "missing_content",
        "wrong_number",
        "wrong_citation",
        "other",
    ]
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    issue_category: str | None = Field(default=None, max_length=80)
    correction: CorrectionPayload | None = None


class ReportRegenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: int | None = None
    feedback_id: int | None = None
    template_key: Literal[
        "comprehensive_analysis",
        "student_research",
        "job_application_analysis",
    ] = "comprehensive_analysis"
    correction_note: str | None = Field(default=None, max_length=2000)
    rerun_analysis: bool = False


class ReportAssetResponse(BaseModel):
    id: int
    asset_type: str
    format: str
    display_name: str
    mime_type: str
    size_bytes: int
    checksum: str | None
    status: str
    download_url: str | None
    created_at: datetime


class ReportVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    workspace_id: int
    version: int
    status: str
    title: str
    template_key: str
    language: str
    markdown_content: str
    generation_source: str
    quality_status: str | None
    quality_summary: dict[str, Any] | None
    warnings: list[Any]
    is_current: bool
    assets: list[ReportAssetResponse]
    created_at: datetime
    completed_at: datetime | None


class FeedbackResponse(BaseModel):
    id: int
    task_id: int
    report_id: int | None
    feedback_type: str
    rating: int | None
    comment: str | None
    issue_category: str | None
    correction: dict[str, Any] | None
    status: str
    created_at: datetime
