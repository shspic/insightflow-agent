from datetime import datetime, timedelta

from app.core.timeutils import utcnow
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models.auth_session import AuthSession
from app.models.invite_code import InviteCode
from app.models.user import User
from app.services.security_service import hash_password, invite_code_hash, invite_code_hint


PASSWORD = "SafePassword!2026"


def csrf_headers(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v2/auth/csrf")
    assert response.status_code == 200
    token = client.cookies.get(settings.csrf_cookie_name)
    assert token
    return {settings.csrf_header_name: token}


def add_invite(db_session, raw_code: str = "IF-test-invite-code", **values) -> InviteCode:
    invite = InviteCode(
        code_hash=invite_code_hash(raw_code),
        code_hint=invite_code_hint(raw_code),
        status=values.get("status", "active"),
        max_uses=values.get("max_uses", 5),
        used_count=values.get("used_count", 0),
        expires_at=values.get("expires_at"),
    )
    db_session.add(invite)
    db_session.commit()
    return invite


def register(client: TestClient, username: str, invite_code: str = "IF-test-invite-code"):
    return client.post(
        "/api/v2/auth/register",
        headers=csrf_headers(client),
        json={
            "username": username,
            "password": PASSWORD,
            "password_confirm": PASSWORD,
            "invite_code": invite_code,
        },
    )


def login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post(
        "/api/v2/auth/login",
        headers=csrf_headers(client),
        json={"username": username, "password": password},
    )


def test_register_success_consumes_invite_without_exposing_hash(client, db_session):
    invite = add_invite(db_session)

    response = register(client, "student.one")

    assert response.status_code == 201
    assert response.json()["username"] == "student.one"
    assert "password_hash" not in response.json()
    assert "code_hash" not in response.json()
    db_session.refresh(invite)
    assert invite.used_count == 1


def test_register_rejects_invalid_expired_and_exhausted_invites(client, db_session):
    invalid = register(client, "student.invalid", "IF-does-not-exist")
    assert invalid.status_code == 400

    add_invite(
        db_session,
        "IF-expired-code",
        expires_at=utcnow() - timedelta(seconds=1),
    )
    expired = register(client, "student.expired", "IF-expired-code")
    assert expired.status_code == 400

    add_invite(db_session, "IF-one-use", max_uses=1)
    assert register(client, "student.first", "IF-one-use").status_code == 201
    exhausted = register(client, "student.second", "IF-one-use")
    assert exhausted.status_code == 400


def test_login_cookie_me_logout_and_failed_login_are_safe(client, db_session):
    add_invite(db_session)
    assert register(client, "job.seeker").status_code == 201

    failed = login(client, "job.seeker", "WrongPassword!2026")
    assert failed.status_code == 401
    assert failed.json()["detail"] == "账号或密码错误"

    response = login(client, "job.seeker")
    assert response.status_code == 200
    assert response.json()["must_change_password"] is False
    assert client.cookies.get(settings.auth_cookie_name)
    assert client.cookies.get(settings.csrf_cookie_name)
    me_response = client.get("/api/v2/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "job.seeker"
    assert "password_hash" not in me_response.json()

    logout_response = client.post(
        "/api/v2/auth/logout",
        headers={settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name)},
    )
    assert logout_response.status_code == 200
    assert client.get("/api/v2/auth/me").status_code == 401


def test_disabled_user_and_expired_session_are_rejected(client, db_session):
    user = User(
        username="disabled.user",
        password_hash=hash_password(PASSWORD),
        role="user",
        status="disabled",
    )
    db_session.add(user)
    db_session.commit()
    assert login(client, "disabled.user").status_code == 401

    user.status = "active"
    db_session.commit()
    assert login(client, "disabled.user").status_code == 200
    session_record = db_session.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
    session_record.expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()
    assert client.get("/api/v2/auth/me").status_code == 401


def test_csrf_is_required_and_change_password_revokes_old_session(client, db_session):
    add_invite(db_session)
    assert register(client, "change.user").status_code == 201
    assert login(client, "change.user").status_code == 200
    old_session_token = client.cookies.get(settings.auth_cookie_name)

    without_csrf = client.post(
        "/api/v2/auth/change-password",
        json={
            "current_password": PASSWORD,
            "new_password": "NewSafePassword!2026",
            "new_password_confirm": "NewSafePassword!2026",
        },
    )
    assert without_csrf.status_code == 403

    response = client.post(
        "/api/v2/auth/change-password",
        headers={settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name)},
        json={
            "current_password": PASSWORD,
            "new_password": "NewSafePassword!2026",
            "new_password_confirm": "NewSafePassword!2026",
        },
    )
    assert response.status_code == 200
    assert client.cookies.get(settings.auth_cookie_name) != old_session_token

    old_client = TestClient(app)
    old_client.cookies.set(settings.auth_cookie_name, old_session_token)
    assert old_client.get("/api/v2/auth/me").status_code == 401
    old_client.close()


def test_public_csrf_failure_has_machine_readable_error_code(client):
    response = client.post(
        "/api/v2/auth/register",
        json={
            "username": "missing.csrf",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
            "invite_code": "IF-test-invite-code",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "CSRF_VALIDATION_FAILED",
        "message": "CSRF 校验失败",
    }


def test_login_rate_limit_persists_in_database(client, db_session):
    user = User(
        username="limited.user",
        password_hash=hash_password(PASSWORD),
        role="user",
        status="active",
    )
    db_session.add(user)
    db_session.commit()

    for _ in range(settings.login_account_limit):
        assert login(client, "limited.user", "WrongPassword!2026").status_code == 401
    assert login(client, "limited.user", "WrongPassword!2026").status_code == 429
