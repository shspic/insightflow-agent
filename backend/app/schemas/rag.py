from pydantic import BaseModel, Field


class FileIndexResponse(BaseModel):
    file_id: int
    filename: str
    status: str
    page_count: int
    chunk_count: int
    message: str


class FileSearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


class FileSearchResult(BaseModel):
    chunk_id: int
    page_number: int
    chunk_index: int
    chunk_text: str
    score: float
    filename: str


class FileSearchResponse(BaseModel):
    file_id: int
    query: str
    results: list[FileSearchResult]
    message: str | None = None
