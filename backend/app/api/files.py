from fastapi import APIRouter, Depends, File as FormFile, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.file import FileResponse
from app.schemas.rag import FileIndexResponse, FileSearchRequest, FileSearchResponse
from app.services.analysis_service import FileAnalysisError, analyze_file
from app.services.chart_service import FileChartError, generate_charts
from app.services.file_service import FileUploadError, get_file_by_id, list_files, save_uploaded_file
from app.services.parser_service import FileParseError, parse_file
from app.services.rag_service import RagServiceError, index_pdf_file, search_pdf_chunks

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/upload", response_model=FileResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(file: UploadFile = FormFile(...), db: Session = Depends(get_db)) -> FileResponse:
    try:
        return await save_uploaded_file(db=db, upload_file=file)
    except FileUploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("", response_model=list[FileResponse])
def get_files(db: Session = Depends(get_db)) -> list[FileResponse]:
    return list_files(db)


@router.get("/{file_id}", response_model=FileResponse)
def get_file(file_id: int, db: Session = Depends(get_db)) -> FileResponse:
    file_record = get_file_by_id(db, file_id)
    if file_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    return file_record


@router.post("/{file_id}/parse", response_model=FileResponse)
def parse_uploaded_file(file_id: int, db: Session = Depends(get_db)) -> FileResponse:
    file_record = get_file_by_id(db, file_id)
    if file_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    try:
        return parse_file(db, file_record)
    except FileParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc


@router.post("/{file_id}/analyze", response_model=FileResponse)
def analyze_uploaded_file(file_id: int, db: Session = Depends(get_db)) -> FileResponse:
    file_record = get_file_by_id(db, file_id)
    if file_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    try:
        return analyze_file(db, file_record)
    except FileAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc


@router.post("/{file_id}/charts", response_model=FileResponse)
def generate_file_charts(file_id: int, db: Session = Depends(get_db)) -> FileResponse:
    file_record = get_file_by_id(db, file_id)
    if file_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    try:
        return generate_charts(db, file_record)
    except FileChartError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc


@router.post("/{file_id}/index", response_model=FileIndexResponse)
def index_pdf(file_id: int, db: Session = Depends(get_db)) -> FileIndexResponse:
    file_record = get_file_by_id(db, file_id)
    if file_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    try:
        return index_pdf_file(db, file_record)
    except RagServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc


@router.post("/{file_id}/search", response_model=FileSearchResponse)
def search_pdf(file_id: int, payload: FileSearchRequest, db: Session = Depends(get_db)) -> FileSearchResponse:
    file_record = get_file_by_id(db, file_id)
    if file_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    try:
        return search_pdf_chunks(db, file_record, query=payload.query, top_k=payload.top_k)
    except RagServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
