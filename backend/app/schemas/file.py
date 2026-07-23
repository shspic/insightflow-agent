from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    filename: str
    file_type: str | None
    status: str
    summary: str | None
    schema_json_: str | None = Field(default=None, alias="schema_json")
    created_at: datetime
    updated_at: datetime
