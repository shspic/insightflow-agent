"""V3 阶段 1：workspace_type 后端 API 测试。

验证：
- 旧客户端不传类型时创建 general
- 显式创建 engineering
- 按 engineering 筛选
- 按 general 筛选
- 非法类型被拒绝
- 不同用户之间仍然隔离
- 详情、软删除和恢复没有跨用户或跨类型泄漏
"""
from app.core.config import settings
from app.services.security_service import hash_password
from app.models.user import User


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


def _login(client, username: str) -> dict[str, str]:
    client.get("/api/v2/auth/csrf")
    response = client.post(
        "/api/v2/auth/login",
        headers={settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name)},
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name)}


class TestWorkspaceTypeCreate:
    """验证创建工作区时的 workspace_type 行为。"""

    def test_default_creates_general(self, client, db_session):
        _add_user(db_session, "type.default")
        headers = _login(client, "type.default")
        response = client.post(
            "/api/v2/workspaces",
            headers=headers,
            json={"name": "默认工作区", "description": "无类型字段"},
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["workspace_type"] == "general"

    def test_explicit_general(self, client, db_session):
        _add_user(db_session, "type.gen")
        headers = _login(client, "type.gen")
        response = client.post(
            "/api/v2/workspaces",
            headers=headers,
            json={"name": "通用", "workspace_type": "general"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["workspace_type"] == "general"

    def test_explicit_engineering(self, client, db_session):
        _add_user(db_session, "type.eng")
        headers = _login(client, "type.eng")
        response = client.post(
            "/api/v2/workspaces",
            headers=headers,
            json={"name": "工程审查项目", "workspace_type": "engineering"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["workspace_type"] == "engineering"

    def test_invalid_type_rejected(self, client, db_session):
        _add_user(db_session, "type.inv")
        headers = _login(client, "type.inv")
        response = client.post(
            "/api/v2/workspaces",
            headers=headers,
            json={"name": "非法类型", "workspace_type": "invalid"},
        )
        assert response.status_code == 422, response.text

    def test_workspace_type_survives_detail(self, client, db_session):
        _add_user(db_session, "type.detail")
        headers = _login(client, "type.detail")
        created = client.post(
            "/api/v2/workspaces",
            headers=headers,
            json={"name": "详情测试", "workspace_type": "engineering"},
        )
        wid = created.json()["id"]
        detail = client.get(f"/api/v2/workspaces/{wid}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["workspace_type"] == "engineering"


class TestWorkspaceTypeList:
    """验证列表按类型筛选。"""

    def test_filter_engineering(self, client, db_session):
        _add_user(db_session, "list.eng")
        headers = _login(client, "list.eng")
        client.post("/api/v2/workspaces", headers=headers,
                    json={"name": "工程A", "workspace_type": "engineering"})
        client.post("/api/v2/workspaces", headers=headers,
                    json={"name": "通用B", "workspace_type": "general"})
        eng_list = client.get("/api/v2/workspaces?workspace_type=engineering", headers=headers)
        assert eng_list.status_code == 200
        items = eng_list.json()
        assert all(item["workspace_type"] == "engineering" for item in items)
        assert any(item["name"] == "工程A" for item in items)
        assert not any(item["name"] == "通用B" for item in items)

    def test_filter_general(self, client, db_session):
        _add_user(db_session, "list.gen")
        headers = _login(client, "list.gen")
        client.post("/api/v2/workspaces", headers=headers,
                    json={"name": "工程C", "workspace_type": "engineering"})
        client.post("/api/v2/workspaces", headers=headers,
                    json={"name": "通用D", "workspace_type": "general"})
        gen_list = client.get("/api/v2/workspaces?workspace_type=general", headers=headers)
        assert gen_list.status_code == 200
        items = gen_list.json()
        assert all(item["workspace_type"] == "general" for item in items)
        assert any(item["name"] == "通用D" for item in items)
        assert not any(item["name"] == "工程C" for item in items)

    def test_invalid_filter_rejected(self, client, db_session):
        _add_user(db_session, "list.inv")
        headers = _login(client, "list.inv")
        response = client.get("/api/v2/workspaces?workspace_type=bad", headers=headers)
        assert response.status_code == 422


class TestWorkspaceTypeIsolation:
    """验证不同用户之间 workspace 隔离不受类型影响。"""

    def test_cross_user_isolation(self, client, db_session):
        _add_user(db_session, "iso.a")
        _add_user(db_session, "iso.b")
        headers_a = _login(client, "iso.a")
        wa = client.post("/api/v2/workspaces", headers=headers_a,
                        json={"name": "A-工程", "workspace_type": "engineering"})

        # 登出 A，登录 B
        client.post("/api/v2/auth/logout", headers=headers_a)
        headers_b = _login(client, "iso.b")
        wb = client.post("/api/v2/workspaces", headers=headers_b,
                        json={"name": "B-工程", "workspace_type": "engineering"})

        # 登出 B，重新登录 A 验证隔离
        client.post("/api/v2/auth/logout", headers=headers_b)
        headers_a2 = _login(client, "iso.a")
        a_list = client.get("/api/v2/workspaces?workspace_type=engineering", headers=headers_a2)
        a_names = {item["name"] for item in a_list.json()}
        assert "A-工程" in a_names
        assert "B-工程" not in a_names

        # A 不能访问 B 的工作区详情
        detail = client.get(f"/api/v2/workspaces/{wb.json()['id']}", headers=headers_a2)
        assert detail.status_code == 404

    def test_permanent_delete_removes_and_restore_returns_410(self, client, db_session):
        import json
        _add_user(db_session, "iso.del")
        headers = _login(client, "iso.del")
        created = client.post("/api/v2/workspaces", headers=headers,
                            json={"name": "待删除工程", "workspace_type": "engineering"})
        wid = created.json()["id"]
        ws_name = created.json()["name"]

        # 永久删除需 confirmation_name
        delete_headers = {**headers, "Content-Type": "application/json"}
        delete_resp = client.request(
            "DELETE",
            f"/api/v2/workspaces/{wid}",
            content=json.dumps({"confirmation_name": ws_name}),
            headers=delete_headers,
        )
        assert delete_resp.status_code == 200

        # 永久删除后不再出现在列表中（含 include_deleted）
        deleted_list = client.get(
            "/api/v2/workspaces?include_deleted=true&workspace_type=engineering",
            headers=headers,
        )
        items = deleted_list.json()
        found = next((item for item in items if item["id"] == wid), None)
        assert found is None, "永久删除后不应出现在任何列表中"

        # restore 返回 410
        restore_resp = client.post(f"/api/v2/workspaces/{wid}/restore", headers=headers)
        assert restore_resp.status_code == 410
