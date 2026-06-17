from pydantic import BaseModel


class ReportResponse(BaseModel):
    task_id: int
    title: str
    report_path: str
    download_url: str
    content: str
