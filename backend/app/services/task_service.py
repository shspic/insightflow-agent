import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.agent_service import run_langgraph_agent
from app.models.file import File
from app.models.task import Task
from app.models.tool_call import ToolCall


class TaskServiceError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def create_task(db: Session, user_input: str, file_ids: list[int]) -> Task:
    if not file_ids:
        raise TaskServiceError("请至少选择一个文件")

    file_id = file_ids[0]
    file_record = db.get(File, file_id)
    if file_record is None:
        raise TaskServiceError("文件不存在")

    task = Task(
        user_input=user_input,
        status="running",
        file_ids_json=json.dumps([file_id], ensure_ascii=False),
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    try:
        state = run_langgraph_agent(task_id=task.id, user_input=user_input, file_ids=[file_id], db=db)
        db.refresh(task)
        if task.status == "running":
            task.task_type = state.task_type
            task.final_answer = state.final_answer
            task.status = "failed" if state.errors else "success"
    except Exception as exc:
        task.final_answer = f"任务执行失败：{exc}"
        task.status = "failed"

    db.commit()
    db.refresh(task)
    return task


def list_tasks(db: Session) -> list[Task]:
    return db.query(Task).order_by(Task.created_at.desc()).all()


def get_task(db: Session, task_id: int) -> Task | None:
    return db.get(Task, task_id)


def get_task_trace(db: Session, task_id: int) -> list[ToolCall]:
    return db.query(ToolCall).filter(ToolCall.task_id == task_id).order_by(ToolCall.created_at.asc()).all()


def task_to_response(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "user_input": task.user_input,
        "task_type": task.task_type,
        "status": task.status,
        "file_ids": _load_file_ids(task.file_ids_json),
        "final_answer": task.final_answer,
        "report_path": task.report_path,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _load_file_ids(file_ids_json: str | None) -> list[int]:
    if not file_ids_json:
        return []

    try:
        data = json.loads(file_ids_json)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    return [int(item) for item in data]
