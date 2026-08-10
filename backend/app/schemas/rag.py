from pydantic import BaseModel, Field


class FileIndexResponse(BaseModel):
    file_id: int
    filename: str
    status: str
    page_count: int
    chunk_count: int
    retrieval_mode: str
    chunk_size: int
    chunk_overlap: int
    message: str


class FileSearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    retrieval_mode: str | None = Field(default=None, pattern="^(auto|tfidf|vector|keyword)$")


class FileSearchResult(BaseModel):
    chunk_id: int
    page_number: int
    chunk_index: int
    chunk_text: str
    score: float
    retrieval_mode: str
    filename: str


class FileSearchResponse(BaseModel):
    file_id: int
    query: str
    top_k: int
    retrieval_mode: str
    fallback_used: bool
    result_count: int
    results: list[FileSearchResult]
    message: str | None = None
