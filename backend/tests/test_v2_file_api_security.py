import dataclasses
from io import BytesIO

import fitz
import pandas as pd
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.models.user import User
from app.services.security_service import hash_password


PASSWORD = "SafePassword!2026"


def public_csrf(client: TestClient) -> dict[str, str]:
    assert client.get("/api/v2/auth/csrf").status_code == 200
    return {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name)}


def session_csrf(client: TestClient) -> dict[str, str]:
    return {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name)}


def add_user(db_session, username: str, role: str = "user") -> User:
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        role=role,
        status="active",
        must_change_password=False,
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


def create_workspace(client: TestClient, name: str = "文件 API") -> dict:
    response = client.post(
        "/api/v2/workspaces",
        headers=session_csrf(client),
        json={"name": name},
    )
    assert response.status_code == 201
    return response.json()


def upload(client: TestClient, workspace_id: int, filename: str, content: bytes, mime: str):
    return client.post(
        f"/api/v2/workspaces/{workspace_id}/files",
        headers=session_csrf(client),
        files={"file": (filename, content, mime)},
    )


def supported_samples() -> list[tuple[str, bytes, str]]:
    xlsx = BytesIO()
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        pd.DataFrame({"id": [1], "value": [10]}).to_excel(writer, index=False)
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Safe PDF")
    pdf = document.tobytes()
    document.close()

    samples = [
        ("safe.csv", b"id,value\n1,10\n", "text/csv"),
        (
            "safe.xlsx",
            xlsx.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        ("safe.pdf", pdf, "application/pdf"),
        ("safe.md", b"# Safe Markdown\n\nText only.", "text/markdown"),
        ("safe.markdown", b"# Safe Markdown\n", "text/plain"),
    ]
    for extension, image_format, mime in (
        ("png", "PNG", "image/png"),
        ("jpg", "JPEG", "image/jpeg"),
        ("jpeg", "JPEG", "image/jpeg"),
        ("webp", "WEBP", "image/webp"),
    ):
        image = BytesIO()
        Image.new("RGB", (32, 24), color="white").save(image, format=image_format)
        samples.append((f"safe.{extension}", image.getvalue(), mime))
    return samples


def test_all_supported_upload_types_pass_server_validation(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr("app.services.file_service._resolve_upload_dir", lambda: tmp_path)
    add_user(db_session, "upload.supported")
    assert login(client, "upload.supported").status_code == 200
    workspace = create_workspace(client)

    for filename, content, mime in supported_samples():
        response = upload(client, workspace["id"], filename, content, mime)
        assert response.status_code == 201, (filename, response.text)
        assert response.json()["display_name"] == filename
        assert response.json()["status"] == "uploaded"


def test_upload_rejects_extension_mime_content_size_batch_and_quota(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr("app.services.file_service._resolve_upload_dir", lambda: tmp_path)
    add_user(db_session, "upload.security")
    assert login(client, "upload.security").status_code == 200
    workspace = create_workspace(client)

    unsupported = upload(client, workspace["id"], "malware.exe", b"MZ", "application/octet-stream")
    assert unsupported.status_code == 415

    mime_mismatch = upload(client, workspace["id"], "fake.csv", b"a,b\n1,2\n", "image/png")
    assert mime_mismatch.status_code == 415

    bad_header = upload(client, workspace["id"], "fake.pdf", b"not a pdf", "application/pdf")
    assert bad_header.status_code == 422

    monkeypatch.setattr(
        "app.services.file_service.settings",
        dataclasses.replace(settings, upload_max_file_size_bytes=8),
    )
    too_large = upload(client, workspace["id"], "large.csv", b"a,b\n123,456\n", "text/csv")
    assert too_large.status_code == 413

    monkeypatch.setattr(
        "app.api.v2.workspace_files.settings",
        dataclasses.replace(settings, upload_max_batch_files=1),
    )
    batch = client.post(
        f"/api/v2/workspaces/{workspace['id']}/files/batch",
        headers=session_csrf(client),
        files=[
            ("files", ("a.csv", b"a,b\n1,2\n", "text/csv")),
            ("files", ("b.csv", b"a,b\n3,4\n", "text/csv")),
        ],
    )
    assert batch.status_code == 413

    monkeypatch.setattr(
        "app.services.file_service.settings",
        settings,
    )
    monkeypatch.setattr(
        "app.api.v2.workspace_files.settings",
        dataclasses.replace(settings, user_storage_quota_bytes=5),
    )
    quota = upload(client, workspace["id"], "quota.csv", b"a,b\n1,2\n", "text/csv")
    assert quota.status_code == 429


def test_directory_traversal_name_is_safely_normalized(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr("app.services.file_service._resolve_upload_dir", lambda: tmp_path)
    add_user(db_session, "upload.path")
    assert login(client, "upload.path").status_code == 200
    workspace = create_workspace(client)
    response = upload(
        client,
        workspace["id"],
        "../../private.csv",
        b"id,value\n1,10\n",
        "text/csv",
    )
    assert response.status_code == 201
    assert response.json()["display_name"] == "private.csv"
    assert response.json()["display_name"].find("..") == -1


def test_understanding_profile_relations_and_context_api_flow(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr("app.services.file_service._resolve_upload_dir", lambda: tmp_path)
    add_user(db_session, "file.flow")
    assert login(client, "file.flow").status_code == 200
    workspace = create_workspace(client)
    first = upload(
        client,
        workspace["id"],
        "jobs_2025.csv",
        b"job_id,skill\n1,Python\n",
        "text/csv",
    ).json()
    second = upload(
        client,
        workspace["id"],
        "jobs_2026.csv",
        b"job_id,skill\n2,SQL\n",
        "text/csv",
    ).json()

    batch = client.post(
        f"/api/v2/workspaces/{workspace['id']}/files/understand",
        headers=session_csrf(client),
        json={
            "file_ids": [first["file_id"], second["file_id"], 999999],
            "options": {"use_deepseek": False, "run_ocr": True},
        },
    )
    assert batch.status_code == 200
    assert batch.json()["status"] == "partial"
    assert [item["status"] for item in batch.json()["results"]] == [
        "ready",
        "ready",
        "failed",
    ]

    profile = client.get(
        f"/api/v2/workspaces/{workspace['id']}/files/{first['file_id']}/profile"
    )
    assert profile.status_code == 200
    assert profile.json()["profile_version"] == 1
    assert "file_path" not in profile.text

    patched = client.patch(
        f"/api/v2/workspaces/{workspace['id']}/files/{first['file_id']}/profile",
        headers=session_csrf(client),
        json={"confirmed_role": "primary_dataset", "user_tags": ["求职", "优先"]},
    )
    assert patched.status_code == 200
    assert patched.json()["effective_role"] == "primary_dataset"

    discovered = client.post(
        f"/api/v2/workspaces/{workspace['id']}/file-relations/discover",
        headers=session_csrf(client),
        json={"use_deepseek": False},
    )
    assert discovered.status_code == 200
    relation = discovered.json()["relations"][0]
    confirmed = client.patch(
        f"/api/v2/workspaces/{workspace['id']}/file-relations/{relation['id']}",
        headers=session_csrf(client),
        json={"action": "confirm", "user_note": "确认连续数据"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"

    context = client.post(
        f"/api/v2/workspaces/{workspace['id']}/context-preview",
        headers=session_csrf(client),
        json={"file_ids": [first["file_id"], second["file_id"]]},
    )
    assert context.status_code == 200
    assert context.json()["context_version"] == "2.03"
    assert context.json()["confirmed_relations"]
    assert str(tmp_path) not in context.text

    removed = client.delete(
        f"/api/v2/workspaces/{workspace['id']}/files/{second['file_id']}",
        headers=session_csrf(client),
    )
    assert removed.status_code == 200
    assert (
        client.get(f"/api/v2/workspaces/{workspace['id']}/file-relations").json()
        == []
    )


def test_user_cannot_understand_another_users_file(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr("app.services.file_service._resolve_upload_dir", lambda: tmp_path)
    add_user(db_session, "understand.a")
    add_user(db_session, "understand.b")
    assert login(client, "understand.a").status_code == 200
    workspace_a = create_workspace(client, "A")
    file_a = upload(
        client,
        workspace_a["id"],
        "a.csv",
        b"id,value\n1,10\n",
        "text/csv",
    ).json()
    client.post("/api/v2/auth/logout", headers=session_csrf(client))

    assert login(client, "understand.b").status_code == 200
    workspace_b = create_workspace(client, "B")
    response = client.post(
        f"/api/v2/workspaces/{workspace_b['id']}/files/{file_a['file_id']}/understand",
        headers=session_csrf(client),
        json={"use_deepseek": False},
    )
    assert response.status_code == 404
