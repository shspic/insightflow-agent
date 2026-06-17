from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.task import TaskCreate, TaskResponse, ToolCallResponse
from app.services.task_service import (
    TaskServiceError,
    create_task,
    get_task,
    get_task_trace,
    list_tasks,
    task_to_response,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_new_task(payload: TaskCreate, db: Session = Depends(get_db)) -> TaskResponse:
    try:
        task = create_task(db=db, user_input=payload.user_input, file_ids=payload.file_ids)
    except TaskServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc

    return task_to_response(task)


@router.get("", response_model=list[TaskResponse])
def get_tasks(db: Session = Depends(get_db)) -> list[TaskResponse]:
    return [task_to_response(task) for task in list_tasks(db)]


@router.get("/{task_id}", response_model=TaskResponse)
def get_task_detail(task_id: int, db: Session = Depends(get_db)) -> TaskResponse:
    task = get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return task_to_response(task)


@router.get("/{task_id}/trace", response_model=list[ToolCallResponse])
def get_task_tool_trace(task_id: int, db: Session = Depends(get_db)) -> list[ToolCallResponse]:
    task = get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return get_task_trace(db, task_id)
