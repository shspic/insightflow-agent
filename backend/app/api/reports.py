from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse as DownloadFileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.report import ReportResponse
from app.services.report_service import (
    ReportServiceError,
    generate_task_report,
    get_task_report,
    resolve_report_file,
)

router = APIRouter(tags=["reports"])


@router.post("/api/tasks/{task_id}/report", response_model=ReportResponse)
def create_task_report(task_id: int, db: Session = Depends(get_db)) -> ReportResponse:
    try:
        return generate_task_report(db, task_id)
    except ReportServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc


@router.get("/api/reports/{task_id}", response_model=ReportResponse)
def get_report(task_id: int, db: Session = Depends(get_db)) -> ReportResponse:
    try:
        return get_task_report(db, task_id)
    except ReportServiceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc


@router.get("/api/reports/{task_id}/download")
def download_report(task_id: int, db: Session = Depends(get_db)) -> DownloadFileResponse:
    try:
        report = get_task_report(db, task_id)
        report_file = resolve_report_file(report["report_path"])
    except ReportServiceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc

    return DownloadFileResponse(
        path=report_file,
        media_type="text/markdown; charset=utf-8",
        filename=report_file.name,
    )
