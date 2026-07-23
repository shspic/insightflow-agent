from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.cli.claim_legacy_data import claim_legacy_data
from app.core.config import settings
from app.main import app
from app.models.file import File
from app.models.task import Task
from app.models.tool_call import ToolCall
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.services.security_service import hash_password


PASSWORD = "SafePassword!2026"


def public_csrf(client: TestClient) -> dict[str, str]:
    assert client.get("/api/v2/auth/csrf").status_code == 200
    return {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name)}


def session_csrf(client: TestClient) -> dict[str, str]:
    return {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name)}


def add_user(db_session, username: str, role: str = "user", must_change: bool = False) -> User:
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        role=role,
        status="active",
        must_change_password=must_change,
    )
    db_session.add(user)
    db_session.commit()
    return user


def login(client: TestClient, username: str):
    return client.post(
        "/api/v2/auth/login",
        headers=public_csrf(client),
        json={"username": username, "password": PASSWORD},
    )


def create_workspace(client: TestClient, name: str = "求职分析") -> dict:
    response = client.post(
        "/api/v2/workspaces",
        headers=session_csrf(client),
        json={"name": name, "description": "测试工作区"},
    )
    assert response.status_code == 201
    return response.json()


def upload_file(client: TestClient, workspace_id: int, filename: str = "sample.csv") -> dict:
    response = client.post(
        f"/api/v2/workspaces/{workspace_id}/files",
        headers=session_csrf(client),
        files={"file": (filename, b"name,score\nAlice,95\n", "text/csv")},
    )
    assert response.status_code == 201
    return response.json()


def test_workspace_soft_delete_restore_and_password_change_gate(client, db_session):
    add_user(db_session, "workspace.user")
    assert login(client, "workspace.user").status_code == 200
    workspace = create_workspace(client)

    deleted = client.delete(
        f"/api/v2/workspaces/{workspace['id']}",
        headers=session_csrf(client),
    )
    assert deleted.status_code == 200
    assert client.get(f"/api/v2/workspaces/{workspace['id']}").status_code == 404
    listed = client.get("/api/v2/workspaces?include_deleted=true").json()
    assert listed[0]["is_deleted"] is True
    restored = client.post(
        f"/api/v2/workspaces/{workspace['id']}/restore",
        headers=session_csrf(client),
    )
    assert restored.status_code == 200
    assert restored.json()["is_deleted"] is False

    forced_client = TestClient(app)
    add_user(db_session, "forced.user", must_change=True)
    assert login(forced_client, "forced.user").status_code == 200
    blocked = forced_client.post(
        "/api/v2/workspaces",
        headers=session_csrf(forced_client),
        json={"name": "不应创建"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    forced_client.close()


def test_users_and_admin_cannot_cross_workspace_file_boundaries(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        "app.services.file_service._resolve_upload_dir",
        lambda: tmp_path,
    )
    user_a = add_user(db_session, "isolation.a")
    user_b = add_user(db_session, "isolation.b")
    add_user(db_session, "isolation.admin", role="admin")

    assert login(client, user_a.username).status_code == 200
    workspace_a = create_workspace(client, "A")
    file_a = upload_file(client, workspace_a["id"], "a.csv")
    assert "file_path" not in file_a
    assert "storage_path" not in file_a
    assert not any(str(tmp_path) in str(value) for value in file_a.values())

    client.post("/api/v2/auth/logout", headers=session_csrf(client))
    assert login(client, user_b.username).status_code == 200
    workspace_b = create_workspace(client, "B")
    file_b = upload_file(client, workspace_b["id"], "b.csv")

    client.post("/api/v2/auth/logout", headers=session_csrf(client))
    assert login(client, user_a.username).status_code == 200
    assert client.get(f"/api/v2/workspaces/{workspace_b['id']}").status_code == 404
    assert (
        client.get(
            f"/api/v2/workspaces/{workspace_b['id']}/files/{file_b['file_id']}"
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v2/workspaces/{workspace_a['id']}/files/{file_b['file_id']}"
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v2/workspaces/{workspace_b['id']}/files/{file_b['file_id']}/download"
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v2/workspaces/{workspace_a['id']}/files/{file_a['file_id']}/download"
        ).status_code
        == 200
    )

    admin_client = TestClient(app)
    assert login(admin_client, "isolation.admin").status_code == 200
    assert (
        admin_client.get(
            f"/api/v2/workspaces/{workspace_b['id']}/files/{file_b['file_id']}"
        ).status_code
        == 404
    )
    admin_client.close()


def test_task_trace_report_and_history_are_isolated(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr("app.services.file_service._resolve_upload_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.services.task_service.run_langgraph_agent",
        lambda **kwargs: SimpleNamespace(
            task_type="data_analysis",
            final_answer="分析完成",
            errors=[],
        ),
    )
    user_a = add_user(db_session, "task.a")
    user_b = add_user(db_session, "task.b")
    assert login(client, user_a.username).status_code == 200
    workspace_a = create_workspace(client, "任务 A")
    file_a = upload_file(client, workspace_a["id"])
    created = client.post(
        f"/api/v2/workspaces/{workspace_a['id']}/tasks",
        headers=session_csrf(client),
        json={"user_input": "分析成绩", "file_ids": [file_a["file_id"]]},
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    assert "report_path" not in created.json()

    task_record = db_session.scalar(select(Task).where(Task.id == task_id))
    report_file = tmp_path / "report.md"
    report_file.write_text("# 安全报告", encoding="utf-8")
    task_record.report_path = str(report_file)
    db_session.add(
        ToolCall(
            task_id=task_id,
            node_name="test",
            tool_name="test_tool",
            input_json='{"file_path":"C:/private/file.csv","query":"成绩"}',
            output_json='{"report_path":"C:/private/report.md","result":"ok"}',
            status="success",
        )
    )
    db_session.commit()

    trace = client.get(
        f"/api/v2/workspaces/{workspace_a['id']}/tasks/{task_id}/trace"
    )
    assert trace.status_code == 200
    assert "file_path" not in trace.text
    assert "report_path" not in trace.text
    report = client.get(
        f"/api/v2/workspaces/{workspace_a['id']}/tasks/{task_id}/report"
    )
    assert report.status_code == 200
    assert "report_path" not in report.json()
    assert str(report_file) not in report.text

    client.post("/api/v2/auth/logout", headers=session_csrf(client))
    assert login(client, user_b.username).status_code == 200
    workspace_b = create_workspace(client, "任务 B")
    assert (
        client.get(
            f"/api/v2/workspaces/{workspace_a['id']}/tasks/{task_id}"
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v2/workspaces/{workspace_a['id']}/tasks/{task_id}/report/download"
        ).status_code
        == 404
    )
    assert client.get(f"/api/v2/workspaces/{workspace_b['id']}/tasks").json() == []


def test_claim_legacy_data_is_dry_run_by_default_and_idempotent(db_session):
    user = add_user(db_session, "legacy.owner")
    legacy_file = File(
        filename="legacy.csv",
        file_type="csv",
        file_path="placeholder.csv",
        status="pending",
    )
    legacy_task = Task(
        user_input="旧任务",
        status="success",
        file_ids_json="[]",
    )
    db_session.add_all([legacy_file, legacy_task])
    db_session.commit()

    preview = claim_legacy_data(db_session, username=user.username, apply=False)
    assert preview.file_count == 1
    assert preview.task_count == 1
    db_session.refresh(legacy_file)
    assert legacy_file.owner_user_id is None

    applied = claim_legacy_data(db_session, username=user.username, apply=True)
    assert applied.applied is True
    db_session.refresh(legacy_file)
    db_session.refresh(legacy_task)
    assert legacy_file.owner_user_id == user.id
    assert legacy_task.owner_user_id == user.id
    assert legacy_task.workspace_id == applied.workspace_id
    assert (
        db_session.scalar(
            select(WorkspaceFile).where(
                WorkspaceFile.workspace_id == applied.workspace_id,
                WorkspaceFile.file_id == legacy_file.id,
            )
        )
        is not None
    )

    repeated = claim_legacy_data(db_session, username=user.username, apply=True)
    assert repeated.file_count == 0
    assert repeated.task_count == 0
    assert repeated.association_count == 0
    assert db_session.scalars(
        select(Workspace).where(Workspace.owner_user_id == user.id)
    ).all().__len__() == 1
