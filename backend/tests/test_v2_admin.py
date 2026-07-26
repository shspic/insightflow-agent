import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.cli.create_admin import create_or_update_admin
from app.core.config import settings
from app.main import app
from app.models.audit_log import AuditLog
from app.models.invite_code import InviteCode
from app.models.password_reset_request import PasswordResetRequest
from app.models.user import User
from app.services.security_service import hash_password, verify_password


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


def login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post(
        "/api/v2/auth/login",
        headers=public_csrf(client),
        json={"username": username, "password": password},
    )


def test_create_admin_cli_service_is_safe_and_does_not_overwrite(client, db_session):
    admin = create_or_update_admin(
        db_session,
        username="root.admin",
        password=PASSWORD,
    )
    assert admin.role == "admin"
    assert admin.password_hash != PASSWORD
    assert verify_password(admin.password_hash, PASSWORD)

    try:
        create_or_update_admin(db_session, username="root.admin", password="AnotherSafe!2026")
    except ValueError as exc:
        assert "已存在" in str(exc)
    else:
        raise AssertionError("已存在管理员不应被静默覆盖")

    updated = create_or_update_admin(
        db_session,
        username="root.admin",
        password="AnotherSafe!2026",
        update_password=True,
    )
    assert updated.role == "admin"
    assert updated.status == "active"
    assert not verify_password(updated.password_hash, PASSWORD)
    assert verify_password(updated.password_hash, "AnotherSafe!2026")
    assert login(client, "root.admin", "AnotherSafe!2026").status_code == 200
    me_response = client.get("/api/v2/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "root.admin"
    assert me_response.json()["role"] == "admin"
    assert me_response.json()["status"] == "active"


def test_non_admin_cannot_access_admin_api(client, db_session):
    add_user(db_session, "normal.user")
    assert login(client, "normal.user").status_code == 200
    assert client.get("/api/v2/admin/users").status_code == 403


def test_invite_is_returned_once_and_rotation_invalidates_old_code(client, db_session):
    add_user(db_session, "invite.admin", role="admin")
    assert login(client, "invite.admin").status_code == 200

    created = client.post(
        "/api/v2/admin/invite-codes",
        headers=session_csrf(client),
        json={"max_uses": 2},
    )
    assert created.status_code == 201
    old_code = created.json()["invite_code"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{8,64}", old_code)
    invite_id = created.json()["id"]
    assert old_code not in str(db_session.scalar(select(InviteCode).where(InviteCode.id == invite_id)).__dict__)

    listed = client.get("/api/v2/admin/invite-codes")
    assert listed.status_code == 200
    assert "invite_code" not in listed.json()[0]
    assert "code_hash" not in listed.json()[0]

    rotated = client.post(
        f"/api/v2/admin/invite-codes/{invite_id}/rotate",
        headers=session_csrf(client),
    )
    assert rotated.status_code == 200
    new_code = rotated.json()["invite_code"]
    assert new_code != old_code

    user_client = TestClient(app)
    old_registration = user_client.post(
        "/api/v2/auth/register",
        headers=public_csrf(user_client),
        json={
            "username": "old.code.user",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
            "invite_code": old_code,
        },
    )
    assert old_registration.status_code == 400
    new_registration = user_client.post(
        "/api/v2/auth/register",
        headers=public_csrf(user_client),
        json={
            "username": "new.code.user",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
            "invite_code": new_code,
        },
    )
    assert new_registration.status_code == 201
    user_client.close()


def test_custom_invite_creation_validation_conflict_and_usage_limit(client, db_session):
    add_user(db_session, "custom.invite.admin", role="admin")
    assert login(client, "custom.invite.admin").status_code == 200

    created = client.post(
        "/api/v2/admin/invite-codes",
        headers=session_csrf(client),
        json={"code": "  Custom_Code-2026  ", "max_uses": 1},
    )
    assert created.status_code == 201
    assert created.json()["invite_code"] == "Custom_Code-2026"

    duplicate = client.post(
        "/api/v2/admin/invite-codes",
        headers=session_csrf(client),
        json={"code": "Custom_Code-2026", "max_uses": 2},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "邀请码已存在"

    invalid = client.post(
        "/api/v2/admin/invite-codes",
        headers=session_csrf(client),
        json={"code": "含空格 bad", "max_uses": 1},
    )
    assert invalid.status_code == 422

    user_client = TestClient(app)
    wrong_case = user_client.post(
        "/api/v2/auth/register",
        headers=public_csrf(user_client),
        json={
            "username": "wrong.case.user",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
            "invite_code": "custom_code-2026",
        },
    )
    assert wrong_case.status_code == 400

    registered = user_client.post(
        "/api/v2/auth/register",
        headers=public_csrf(user_client),
        json={
            "username": "custom.code.user",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
            "invite_code": "Custom_Code-2026",
        },
    )
    assert registered.status_code == 201

    exhausted = user_client.post(
        "/api/v2/auth/register",
        headers=public_csrf(user_client),
        json={
            "username": "second.custom.user",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
            "invite_code": "Custom_Code-2026",
        },
    )
    assert exhausted.status_code == 400
    invite = db_session.scalar(
        select(InviteCode).where(InviteCode.id == created.json()["id"])
    )
    db_session.refresh(invite)
    assert invite.used_count == 1
    assert invite.status == "exhausted"
    user_client.close()


def test_non_admin_cannot_create_custom_invite(client, db_session):
    add_user(db_session, "no.invite.permission")
    assert login(client, "no.invite.permission").status_code == 200

    response = client.post(
        "/api/v2/admin/invite-codes",
        headers=session_csrf(client),
        json={"code": "Forbidden_Code-2026", "max_uses": 1},
    )

    assert response.status_code == 403


def test_password_reset_temporary_password_is_one_time_and_forces_change(client, db_session):
    add_user(db_session, "reset.admin", role="admin")
    target = add_user(db_session, "reset.user")
    user_client = TestClient(app)

    reset_response = user_client.post(
        "/api/v2/auth/password-reset-requests",
        headers=public_csrf(user_client),
        json={"username": "reset.user", "request_note": "无法登录"},
    )
    assert reset_response.status_code == 200
    unknown_response = user_client.post(
        "/api/v2/auth/password-reset-requests",
        headers=public_csrf(user_client),
        json={"username": "unknown.user"},
    )
    assert unknown_response.status_code == 200
    assert unknown_response.json() == reset_response.json()

    assert login(client, "reset.admin").status_code == 200
    pending = client.get("/api/v2/admin/password-reset-requests?status=pending")
    assert pending.status_code == 200
    request_id = pending.json()[0]["id"]
    issued = client.post(
        f"/api/v2/admin/password-reset-requests/{request_id}/issue-temporary-password",
        headers=session_csrf(client),
        json={"admin_note": "线下核验完成"},
    )
    assert issued.status_code == 200
    temporary_password = issued.json()["temporary_password"]
    db_session.refresh(target)
    assert target.password_hash != temporary_password
    assert verify_password(target.password_hash, temporary_password)
    assert target.must_change_password is True
    assert temporary_password not in "".join(
        value or "" for value in db_session.scalars(select(AuditLog.details_json)).all()
    )

    second_issue = client.post(
        f"/api/v2/admin/password-reset-requests/{request_id}/issue-temporary-password",
        headers=session_csrf(client),
        json={},
    )
    assert second_issue.status_code == 409
    assert "temporary_password" not in second_issue.text

    temp_login = login(user_client, "reset.user", temporary_password)
    assert temp_login.status_code == 200
    assert temp_login.json()["must_change_password"] is True
    assert user_client.get("/api/v2/admin/users").status_code == 403
    changed = user_client.post(
        "/api/v2/auth/change-password",
        headers=session_csrf(user_client),
        json={
            "current_password": temporary_password,
            "new_password": "ChangedSafePassword!2026",
            "new_password_confirm": "ChangedSafePassword!2026",
        },
    )
    assert changed.status_code == 200
    reset_record = db_session.scalar(
        select(PasswordResetRequest).where(PasswordResetRequest.id == request_id)
    )
    assert reset_record.status == "completed"
    user_client.close()


def test_admin_can_disable_normal_user_and_audit_response_is_sanitized(client, db_session):
    admin = add_user(db_session, "status.admin", role="admin")
    target = add_user(db_session, "status.user")
    db_session.add(
        AuditLog(
            user_id=admin.id,
            action="test.sensitive",
            status="success",
            details_json='{"password":"hidden","safe":"visible","token":"secret"}',
            ip_address="127.0.0.1",
        )
    )
    db_session.commit()
    assert login(client, "status.admin").status_code == 200

    disabled = client.patch(
        f"/api/v2/admin/users/{target.id}/status",
        headers=session_csrf(client),
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert "password_hash" not in disabled.json()
    assert login(TestClient(app), "status.user").status_code == 401

    self_disable = client.patch(
        f"/api/v2/admin/users/{admin.id}/status",
        headers=session_csrf(client),
        json={"status": "disabled"},
    )
    assert self_disable.status_code == 409

    audit_response = client.get("/api/v2/admin/audit-logs?action=test.sensitive")
    assert audit_response.status_code == 200
    item = audit_response.json()["items"][0]
    assert item["details"] == {"safe": "visible"}
    assert "ip_address" not in item
