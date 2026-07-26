from datetime import datetime, timedelta
from pathlib import Path

from app.core.timeutils import utcnow
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.models.file import File
from app.models.task import Task
from app.models.task_event import TaskEvent
from app.models.task_plan import TaskPlan
from app.models.task_step import TaskStep
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.services.security_service import hash_password
from app.services.task_queue_service import claim_next_task, heartbeat_task
from app.workers.task_worker import TaskWorker


PASSWORD = "SafePassword!2026"


def _add_user(db_session, username: str) -> User:
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        role="user",
        status="active",
    )
    db_session.add(user)
    db_session.commit()
    return user


def _login(client: TestClient, username: str) -> dict[str, str]:
    client.get("/api/v2/auth/csrf")
    response = client.post(
        "/api/v2/auth/login",
        headers={settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name)},
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name)}


def _workspace_file(db_session, user: User, file_type: str = "png") -> tuple[Workspace, File]:
    workspace = Workspace(owner_user_id=user.id, name="V2-04", status="active")
    db_session.add(workspace)
    db_session.flush()
    file_record = File(
        owner_user_id=user.id,
        filename=f"sample.{file_type}",
        file_type=file_type,
        file_path="placeholder",
        status="ready",
    )
    db_session.add(file_record)
    db_session.flush()
    db_session.add(
        WorkspaceFile(
            workspace_id=workspace.id,
            file_id=file_record.id,
        )
    )
    db_session.commit()
    return workspace, file_record


def _create_and_confirm(
    client: TestClient,
    headers: dict[str, str],
    workspace_id: int,
    file_id: int,
) -> dict:
    draft = client.post(
        f"/api/v2/workspaces/{workspace_id}/tasks/drafts",
        headers=headers,
        json={
            "user_request": "请综合分析所选资料并生成包含风险和建议的报告",
            "selected_file_ids": [file_id],
            "use_deepseek": False,
        },
    )
    assert draft.status_code == 201, draft.text
    assert draft.json()["status"] == "awaiting_confirmation"
    plan_id = draft.json()["current_plan"]["id"]
    confirmed = client.post(
        f"/api/v2/workspaces/{workspace_id}/tasks/{draft.json()['id']}/plans/{plan_id}/confirm",
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "queued"
    return confirmed.json()


def test_draft_clarification_plan_version_and_confirmation(client, db_session):
    user = _add_user(db_session, "draft.user")
    workspace, file_record = _workspace_file(db_session, user)
    headers = _login(client, user.username)

    needs_question = client.post(
        f"/api/v2/workspaces/{workspace.id}/tasks/drafts",
        headers=headers,
        json={"user_request": "分析", "selected_file_ids": []},
    )
    assert needs_question.status_code == 201
    assert needs_question.json()["status"] == "awaiting_clarification"
    assert len(needs_question.json()["clarifications"][0]["questions"]) <= 3

    task = _create_and_confirm(client, headers, workspace.id, file_record.id)
    assert [step["agent_type"] for step in task["steps"]] == [
        "file_understanding_agent",
        "report_agent",
        "quality_review_agent",
    ]


def test_plan_patch_creates_version_and_rejects_unregistered_tool(client, db_session):
    user = _add_user(db_session, "plan.user")
    workspace, file_record = _workspace_file(db_session, user)
    headers = _login(client, user.username)
    draft = client.post(
        f"/api/v2/workspaces/{workspace.id}/tasks/drafts",
        headers=headers,
        json={
            "user_request": "请检查资料并生成结构化分析报告",
            "selected_file_ids": [file_record.id],
        },
    ).json()
    plan = draft["current_plan"]
    patched = client.patch(
        f"/api/v2/workspaces/{workspace.id}/tasks/{draft['id']}/plans/{plan['id']}",
        headers=headers,
        json={"goal": "重点输出风险与行动建议", "steps": plan["steps"]},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["version"] == plan["version"] + 1

    bad_steps = list(patched.json()["steps"])
    bad_steps[0] = {**bad_steps[0], "tool_name": "shell"}
    rejected = client.patch(
        f"/api/v2/workspaces/{workspace.id}/tasks/{draft['id']}/plans/{patched.json()['id']}",
        headers=headers,
        json={"steps": bad_steps},
    )
    assert rejected.status_code == 422


def test_queue_claim_is_exclusive_and_expired_lease_recovers(db_session):
    task = Task(
        user_input="排队任务",
        status="queued",
        file_ids_json="[]",
        queued_at=utcnow(),
    )
    db_session.add(task)
    db_session.flush()
    plan = TaskPlan(
        task_id=task.id,
        version=1,
        status="confirmed",
        goal="测试",
        assumptions_json="[]",
        steps_json="[]",
        selected_file_ids_json="[]",
        estimated_model_calls=0,
        estimated_tool_calls=0,
        created_by="test",
    )
    db_session.add(plan)
    db_session.flush()
    task.current_plan_id = plan.id
    db_session.commit()

    first = claim_next_task(db_session, worker_id="worker-a")
    assert first is not None
    assert claim_next_task(db_session, worker_id="worker-b") is None
    first.lease_expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()
    recovered = claim_next_task(db_session, worker_id="worker-b")
    assert recovered is not None
    assert recovered.worker_id == "worker-b"
    assert recovered.attempt_number == 2
    assert heartbeat_task(db_session, task_id=task.id, worker_id="worker-b") is True

    unconfirmed = Task(
        user_input="未确认",
        status="queued",
        file_ids_json="[]",
        queued_at=utcnow(),
    )
    db_session.add(unconfirmed)
    db_session.flush()
    draft_plan = TaskPlan(
        task_id=unconfirmed.id,
        version=1,
        status="draft",
        goal="不能认领",
        assumptions_json="[]",
        steps_json="[]",
        selected_file_ids_json="[]",
        estimated_model_calls=0,
        estimated_tool_calls=0,
        created_by="test",
    )
    db_session.add(draft_plan)
    db_session.flush()
    unconfirmed.current_plan_id = draft_plan.id
    db_session.commit()
    assert claim_next_task(db_session, worker_id="worker-c") is None


def test_worker_executes_confirmed_plan_idempotently(
    client,
    db_session,
    monkeypatch,
    tmp_path: Path,
):
    user = _add_user(db_session, "worker.user")
    workspace, file_record = _workspace_file(db_session, user)
    headers = _login(client, user.username)
    task_data = _create_and_confirm(client, headers, workspace.id, file_record.id)
    monkeypatch.setattr(
        "app.services.v2_report_service._report_file",
        lambda task_id: tmp_path / f"task_{task_id}_v2.md",
    )

    assert TaskWorker("worker-test").run_once(db_session) is True
    task = db_session.get(Task, task_data["id"])
    assert task.status == "completed_with_warnings"
    assert task.report_id == task.id
    assert task.worker_id is None
    assert TaskWorker("worker-other").run_once(db_session) is False
    assert len(
        db_session.scalars(
            select(TaskEvent).where(
                TaskEvent.task_id == task.id,
                TaskEvent.event_type == "task_completed",
            )
        ).all()
    ) == 1


def test_task_event_isolation_polling_and_terminal_sse(client, db_session):
    user_a = _add_user(db_session, "events.a")
    user_b = _add_user(db_session, "events.b")
    workspace_a, file_a = _workspace_file(db_session, user_a)
    headers_a = _login(client, user_a.username)
    task = _create_and_confirm(client, headers_a, workspace_a.id, file_a.id)
    cancelled = client.post(
        f"/api/v2/workspaces/{workspace_a.id}/tasks/{task['id']}/cancel",
        headers=headers_a,
    )
    assert cancelled.status_code == 200
    events = client.get(
        f"/api/v2/workspaces/{workspace_a.id}/tasks/{task['id']}/events?after_id=0"
    )
    assert events.status_code == 200
    first_id = events.json()[0]["id"]
    incremental = client.get(
        f"/api/v2/workspaces/{workspace_a.id}/tasks/{task['id']}/events?after_id={first_id}"
    )
    assert all(item["id"] > first_id for item in incremental.json())
    with client.stream(
        "GET",
        f"/api/v2/workspaces/{workspace_a.id}/tasks/{task['id']}/events/stream",
        headers={"Last-Event-ID": str(first_id)},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "id:" in body
    assert "task_cancelled" in body
    assert "placeholder" not in body

    client.post("/api/v2/auth/logout", headers=headers_a)
    headers_b = _login(client, user_b.username)
    assert (
        client.get(
            f"/api/v2/workspaces/{workspace_a.id}/tasks/{task['id']}/events"
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v2/workspaces/{workspace_a.id}/tasks/{task['id']}/cancel",
            headers=headers_b,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v2/workspaces/{workspace_a.id}/tasks/{task['id']}/retry",
            headers=headers_b,
        ).status_code
        == 404
    )
