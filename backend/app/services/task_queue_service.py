import json
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.task import Task
from app.models.task_plan import TaskPlan
from app.models.task_step import TaskStep
from app.services.task_event_service import append_task_event
from app.services.task_state_machine import (
    TERMINAL_TASK_STATUSES,
    TaskStateError,
    transition_task,
)


class TaskQueueError(Exception):
    def __init__(self, message: str, code: str = "TASK_QUEUE_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


def claim_next_task(
    db: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
) -> Task | None:
    now = now or datetime.utcnow()
    candidate = db.scalar(
        select(Task.id)
        .join(TaskPlan, TaskPlan.id == Task.current_plan_id)
        .where(
            TaskPlan.status == "confirmed",
            Task.cancellation_requested_at.is_(None),
            or_(
                Task.status == "queued",
                and_(
                    Task.status.in_(["running", "retrying", "reviewing"]),
                    Task.lease_expires_at.is_not(None),
                    Task.lease_expires_at < now,
                ),
            ),
        )
        .order_by(Task.queued_at.asc(), Task.id.asc())
        .limit(1)
    )
    if candidate is None:
        return None
    claim_condition = or_(
        Task.status == "queued",
        and_(
            Task.status.in_(["running", "retrying", "reviewing"]),
            Task.lease_expires_at.is_not(None),
            Task.lease_expires_at < now,
        ),
    )
    result = db.execute(
        update(Task)
        .where(Task.id == candidate, claim_condition)
        .values(
            status="running",
            worker_id=worker_id,
            lease_expires_at=now + timedelta(seconds=max(1, settings.worker_lease_seconds)),
            heartbeat_at=now,
            last_heartbeat_at=now,
            started_at=func.coalesce(Task.started_at, now),
            attempt_number=Task.attempt_number + 1,
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        return None
    task = db.get(Task, candidate)
    append_task_event(
        db,
        task_id=task.id,
        event_type="task_claimed",
        message=f"Worker 已认领任务（attempt {task.attempt_number}）。",
        status="running",
        progress_percent=task.progress_percent,
        payload={"worker_id": worker_id, "attempt_number": task.attempt_number},
    )
    db.commit()
    db.refresh(task)
    return task


def heartbeat_task(
    db: Session,
    *,
    task_id: int,
    worker_id: str,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.utcnow()
    result = db.execute(
        update(Task)
        .where(
            Task.id == task_id,
            Task.worker_id == worker_id,
            Task.status.in_(["running", "reviewing", "retrying"]),
        )
        .values(
            heartbeat_at=now,
            last_heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=max(1, settings.worker_lease_seconds)),
            updated_at=now,
        )
    )
    db.commit()
    return result.rowcount == 1


def release_task_lease(db: Session, task: Task) -> None:
    task.worker_id = None
    task.lease_expires_at = None
    task.heartbeat_at = None
    db.flush()


def request_task_cancellation(db: Session, task: Task) -> Task:
    if task.status in TERMINAL_TASK_STATUSES:
        return task
    task.cancellation_requested_at = datetime.utcnow()
    if task.status in {
        "draft",
        "awaiting_clarification",
        "planning",
        "awaiting_confirmation",
        "queued",
    }:
        transition_task(
            db,
            task,
            "cancelled",
            message="用户已取消任务。",
            event_type="task_cancelled",
        )
        for step in db.scalars(
            select(TaskStep).where(
                TaskStep.task_id == task.id,
                TaskStep.status.in_(["pending", "queued", "retrying"]),
            )
        ).all():
            step.status = "cancelled"
    else:
        append_task_event(
            db,
            task_id=task.id,
            event_type="cancellation_requested",
            message="已记录取消请求，Worker 将在当前步骤的可控检查点停止。",
            status=task.status,
            progress_percent=task.progress_percent,
        )
    db.commit()
    db.refresh(task)
    return task


def retry_task(db: Session, task: Task, *, step_id: int | None = None) -> Task:
    if task.status not in {"failed", "completed_with_warnings"}:
        raise TaskQueueError("只有失败或带警告完成的任务可以重试", "INVALID_TASK_STATUS")
    if task.retry_count >= task.max_retries:
        raise TaskQueueError("任务已达到最大重试次数", "TASK_RETRY_LIMIT_REACHED")
    steps = list(
        db.scalars(
            select(TaskStep)
            .where(TaskStep.task_id == task.id)
            .order_by(TaskStep.step_order.asc())
        ).all()
    )
    if step_id is not None:
        target = next((item for item in steps if item.id == step_id), None)
        if target is None or target.status != "failed":
            raise TaskQueueError("只能重试当前任务的失败步骤", "INVALID_RETRY_STEP")
        targets = _downstream_steps(steps, {target.step_key})
    else:
        failed_keys = {item.step_key for item in steps if item.status == "failed"}
        if not failed_keys:
            review = next(
                (item for item in steps if item.agent_type == "quality_review_agent"),
                None,
            )
            failed_keys = {review.step_key} if review else set()
        targets = _downstream_steps(steps, failed_keys)
    if not targets:
        raise TaskQueueError("没有可重试步骤", "NO_RETRYABLE_STEPS")

    transition_task(
        db,
        task,
        "retrying",
        message="正在准备受限局部重试。",
        event_type="task_retry_requested",
        payload={"step_ids": [item.id for item in targets]},
    )
    target_keys = {item.step_key for item in targets}
    for step in targets:
        step.status = "queued"
        step.progress_percent = 0
        step.retry_count += 1
        step.started_at = None
        step.completed_at = None
        step.failed_at = None
        step.error_code = None
        step.error_message = None
        step.output_json = None
    task.retry_count += 1
    task.cancellation_requested_at = None
    task.failed_at = None
    task.completed_at = None
    task.error_code = None
    task.error_message = None
    task.current_step_id = None
    task.worker_id = None
    task.lease_expires_at = None
    if task.agent_state_json:
        try:
            state = json.loads(task.agent_state_json)
            state["completed_steps"] = [
                key for key in state.get("completed_steps", []) if key not in target_keys
            ]
            state["failed_steps"] = [
                key for key in state.get("failed_steps", []) if key not in target_keys
            ]
            state["retry_count"] = task.retry_count
            task.agent_state_json = json.dumps(state, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    transition_task(
        db,
        task,
        "queued",
        message="局部重试步骤已进入队列；已完成的上游步骤将复用。",
        progress_percent=_completed_progress(steps),
        event_type="task_requeued",
    )
    db.commit()
    db.refresh(task)
    return task


def requeue_task_for_reanalysis(db: Session, task: Task) -> Task:
    """按用户明确请求重跑分析链路，保留文件理解结果并重新执行质量审核。"""
    if task.status not in {"completed", "completed_with_warnings", "failed"}:
        raise TaskQueueError("只有已结束任务可以重新运行分析", "INVALID_TASK_STATUS")
    steps = list(
        db.scalars(
            select(TaskStep)
            .where(TaskStep.task_id == task.id)
            .order_by(TaskStep.step_order.asc())
        ).all()
    )
    targets = [
        item
        for item in steps
        if item.agent_type
        in {
            "data_analysis_agent",
            "document_research_agent",
            "report_agent",
            "quality_review_agent",
        }
    ]
    if not targets:
        raise TaskQueueError("任务没有可重新分析的步骤", "NO_REANALYSIS_STEPS")

    transition_task(
        db,
        task,
        "retrying",
        message="用户明确请求重新分析，正在重排受控分析链路。",
        event_type="task_reanalysis_requested",
        payload={"step_ids": [item.id for item in targets]},
    )
    target_keys = {item.step_key for item in targets}
    for step in targets:
        step.status = "queued"
        step.progress_percent = 0
        step.started_at = None
        step.completed_at = None
        step.failed_at = None
        step.error_code = None
        step.error_message = None
        step.output_json = None
    task.cancellation_requested_at = None
    task.failed_at = None
    task.completed_at = None
    task.error_code = None
    task.error_message = None
    task.current_step_id = None
    task.worker_id = None
    task.lease_expires_at = None
    task.started_at = None
    task.queued_at = datetime.utcnow()
    if task.agent_state_json:
        try:
            state = json.loads(task.agent_state_json)
            state["completed_steps"] = [
                key for key in state.get("completed_steps", []) if key not in target_keys
            ]
            state["failed_steps"] = [
                key for key in state.get("failed_steps", []) if key not in target_keys
            ]
            state["analysis_findings"] = []
            state["document_evidence"] = []
            state["chart_assets"] = []
            state["report_sections"] = []
            state["review_findings"] = []
            state["final_result"] = {}
            state["report_id"] = None
            task.agent_state_json = json.dumps(state, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    transition_task(
        db,
        task,
        "queued",
        message="重新分析步骤已进入队列；文件理解结果将继续复用。",
        progress_percent=_completed_progress(steps),
        event_type="task_reanalysis_queued",
    )
    db.commit()
    db.refresh(task)
    return task


def _downstream_steps(
    steps: list[TaskStep],
    initial_keys: set[str],
) -> list[TaskStep]:
    selected = set(initial_keys)
    changed = True
    while changed:
        changed = False
        for step in steps:
            dependencies = _json_list(step.depends_on_json)
            if step.step_key not in selected and selected.intersection(dependencies):
                selected.add(step.step_key)
                changed = True
    return [item for item in steps if item.step_key in selected]


def _completed_progress(steps: list[TaskStep]) -> int:
    if not steps:
        return 5
    completed = sum(item.status in {"completed", "skipped"} for item in steps)
    return min(95, 5 + int(completed / len(steps) * 90))


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
