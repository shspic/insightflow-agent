from sqlalchemy import select

from app.models.task import Task
from app.models.task_event import TaskEvent
from app.services.task_state_machine import TaskStateError, transition_task


def _task(db_session, status: str = "draft") -> Task:
    task = Task(user_input="分析资料", status=status, file_ids_json="[]")
    db_session.add(task)
    db_session.commit()
    return task


def test_legal_transition_writes_matching_event(db_session):
    task = _task(db_session)
    transition_task(
        db_session,
        task,
        "planning",
        message="开始规划",
        progress_percent=5,
    )
    db_session.commit()

    event = db_session.scalar(select(TaskEvent).where(TaskEvent.task_id == task.id))
    assert task.status == "planning"
    assert task.progress_percent == 5
    assert event.status == "planning"
    assert event.progress_percent == 5


def test_illegal_and_terminal_transitions_are_rejected(db_session):
    task = _task(db_session)
    try:
        transition_task(db_session, task, "running", message="非法跳转")
    except TaskStateError as exc:
        assert exc.code == "INVALID_TASK_TRANSITION"
    else:
        raise AssertionError("非法状态转换必须拒绝")

    completed = _task(db_session, status="completed")
    try:
        transition_task(db_session, completed, "running", message="不能重跑")
    except TaskStateError:
        pass
    else:
        raise AssertionError("已完成任务不能重新进入 running")


def test_cancel_and_progress_range(db_session):
    task = _task(db_session)
    transition_task(db_session, task, "cancelled", message="用户取消")
    assert task.status == "cancelled"

    other = _task(db_session)
    try:
        transition_task(
            db_session,
            other,
            "planning",
            message="无效进度",
            progress_percent=101,
        )
    except TaskStateError as exc:
        assert exc.code == "INVALID_PROGRESS"
    else:
        raise AssertionError("越界进度必须拒绝")
