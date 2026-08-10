from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    workspace_type: str | None = Field(default="general", pattern="^(engineering|general)$")


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = None


class WorkspaceResponse(BaseModel):
    id: int
    name: str
    description: str | None
    workspace_type: str
    review_template_key: str | None = None
    status: str
    is_deleted: bool
    file_count: int
    task_count: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class WorkspaceFileResponse(BaseModel):
    file_id: int
    display_name: str
    file_type: str | None
    mime_type: str | None
    size_bytes: int | None
    status: str
    summary: str | None
    structure: dict[str, Any] | None
    download_url: str
    created_at: datetime
    updated_at: datetime


class WorkspaceFileUploadResult(BaseModel):
    filename: str
    status: str
    file: WorkspaceFileResponse | None = None
    error_status: int | None = None
    error_code: str | None = None
    message: str


class WorkspaceFileBatchUploadResponse(BaseModel):
    status: str
    results: list[WorkspaceFileUploadResult]


class WorkspaceTaskResponse(BaseModel):
    id: int
    workspace_id: int
    user_input: str
    task_type: str | None
    status: str
    file_ids: list[int]
    final_answer: str | None
    has_report: bool
    created_at: datetime
    updated_at: datetime


class V2ReportResponse(BaseModel):
    task_id: int
    title: str
    download_url: str
    content: str
