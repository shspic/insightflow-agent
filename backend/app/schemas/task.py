from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TaskCreate(BaseModel):
    user_input: str
    file_ids: list[int]


class TaskResponse(BaseModel):
    id: int
    user_input: str
    task_type: str | None
    status: str
    file_ids: list[int]
    final_answer: str | None
    report_path: str | None
    created_at: datetime
    updated_at: datetime


class ToolCallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int | None
    node_name: str | None
    tool_name: str | None
    input_json: str | None
    output_json: str | None
    status: str
    latency_ms: int | None
    error_message: str | None
    created_at: datetime
