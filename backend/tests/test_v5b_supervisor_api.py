"""阶段 5B：Engineering Supervisor API 层专项测试。

完全离线：不调用 DeepSeek、不加载真实 BGE、不访问公网、不启动 MCP Server。
使用独立临时 SQLite + FakeEmbedding 索引；每个测试使用全新 TestClient
（干净 cookie 隔离，避免跨测试 CSRF/session 状态耦合）；
不写默认 app.db/uploads/retrieval；无 mkdtemp 独立残留；无递归删除。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.review_run import ReviewRun
from app.models.workspace import Workspace
from test_v5b_supervisor import _build_db, _fresh_run

PASSWORD = "SafePassword!2026"


@pytest.fixture(scope="module")
def api_env(tmp_path_factory):
    """独立临时环境：SQLite + FakeEmbedding 索引（TestClient 按测试新建）。"""
    tmp_root = tmp_path_factory.mktemp("v5b_api")
    db_path = tmp_root / "api.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    upload_dir = tmp_root / "uploads"
    original_upload = settings.upload_dir
    original_report = settings.report_dir
    original_mcp = settings.engineering_mcp_enabled
    object.__setattr__(settings, "upload_dir", str(upload_dir))
    object.__setattr__(settings, "report_dir", str(tmp_root / "reports"))
    object.__setattr__(settings, "engineering_mcp_enabled", False)
    try:
        data = _build_db(db_url, upload_dir)
    except Exception:
        object.__setattr__(settings, "upload_dir", original_upload)
        object.__setattr__(settings, "report_dir", original_report)
        object.__setattr__(settings, "engineering_mcp_enabled", original_mcp)
        raise

    import app.services.engineering_retrieval_service as svc_mod
    from app.retrieval.embedding import FakeEmbeddingProvider

    idx_root = tmp_root / "retrieval" / "workspaces"
    idx_root.mkdir(parents=True)
    original_root = svc_mod._INDEX_ROOT
    original_provider = svc_mod.LocalEmbeddingProvider
    svc_mod._INDEX_ROOT = idx_root
    svc_mod.LocalEmbeddingProvider = lambda *a, **kw: FakeEmbeddingProvider(dimension=512, seed=42)

    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(conn, _r):  # noqa: ARG001
        conn.execute("PRAGMA foreign_keys=ON")

    S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    dbs = S()
    try:
        from app.services.engineering_retrieval_service import rebuild_index

        rebuild_index(dbs, data["workspace"], data["user"])
    finally:
        dbs.close()
        engine.dispose()

    request_engine = create_engine(db_url, connect_args={"check_same_thread": False})

    @event.listens_for(request_engine, "connect")
    def _fk2(conn, _r):  # noqa: ARG001
        conn.execute("PRAGMA foreign_keys=ON")

    request_S = sessionmaker(bind=request_engine, autoflush=False, autocommit=False)
    try:
        yield {"data": data, "S": request_S}
    finally:
        svc_mod._INDEX_ROOT = original_root
        svc_mod.LocalEmbeddingProvider = original_provider
        object.__setattr__(settings, "upload_dir", original_upload)
        object.__setattr__(settings, "report_dir", original_report)
        object.__setattr__(settings, "engineering_mcp_enabled", original_mcp)
        request_engine.dispose()


@pytest.fixture()
def client(api_env):
    """每个测试全新 TestClient + 覆盖 get_db（干净 cookie 隔离）。"""
    request_S = api_env["S"]

    def override_get_db():
        db = request_S()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _api_run(api_env, **finding_kw) -> int:
    """每个测试独立的 fresh ReviewRun。"""
    db = api_env["S"]()
    try:
        return _fresh_run(db, api_env["data"], **finding_kw)
    finally:
        db.close()


def _csrf_headers(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v2/auth/csrf")
    assert response.status_code == 200
    token = client.cookies.get(settings.csrf_cookie_name)
    assert token
    return {settings.csrf_header_name: token}


def _login(api_env, client: TestClient) -> dict[str, str]:
    """登录 v5b_user 并返回该会话的 CSRF header。"""
    response = client.post(
        "/api/v2/auth/login",
        headers=_csrf_headers(client),
        json={"username": "v5b_user", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    assert client.cookies.get(settings.auth_cookie_name)
    return {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name)}


def _supervisor_base(api_env, run_id: int) -> str:
    return (f"/api/v2/workspaces/{api_env['data']['workspace']}"
            f"/review-runs/{run_id}/supervisor-runs")


def _launch_payload(**overrides) -> dict:
    payload = {
        "use_deepseek": False,
        "generate_report": False,
        "max_verification_tool_calls": 5,
        "max_step_retries": 1,
    }
    payload.update(overrides)
    return payload


def test_supervisor_api_csrf_required(api_env, client):
    """未携带 CSRF header 的 POST → 403（require_session_csrf）。"""
    run_id = _api_run(api_env)
    _login(api_env, client)
    response = client.post(_supervisor_base(api_env, run_id), json=_launch_payload())
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "CSRF_VALIDATION_FAILED"


def test_supervisor_api_create_201_then_200_idempotent(api_env, client):
    """相同稳定输入：首次 201+reused=false，再次 200+reused=true 且同一 run。"""
    run_id = _api_run(api_env)
    headers = _login(api_env, client)
    url = _supervisor_base(api_env, run_id)

    first = client.post(url, headers=headers, json=_launch_payload())
    assert first.status_code == 201
    body1 = first.json()
    assert body1["reused"] is False
    assert body1["status"] == "ready_to_report"

    second = client.post(url, headers=headers, json=_launch_payload())
    assert second.status_code == 200
    body2 = second.json()
    assert body2["reused"] is True
    assert body2["supervisor_run_id"] == body1["supervisor_run_id"]


def test_supervisor_api_list_detail_steps(api_env, client):
    """列表、详情、steps 三个 GET 接口；generate_report=false 时四节点中无 reporting。"""
    run_id = _api_run(api_env)
    headers = _login(api_env, client)
    created = client.post(_supervisor_base(api_env, run_id), headers=headers,
                          json=_launch_payload())
    assert created.status_code == 201
    supervisor_run_id = created.json()["supervisor_run_id"]

    listing = client.get(_supervisor_base(api_env, run_id), headers=headers)
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) == 1
    assert items[0]["supervisor_run_id"] == supervisor_run_id
    assert items[0]["review_run_id"] == run_id

    detail = client.get(f"{_supervisor_base(api_env, run_id)}/{supervisor_run_id}",
                        headers=headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "ready_to_report"

    steps = client.get(f"{_supervisor_base(api_env, run_id)}/{supervisor_run_id}/steps",
                       headers=headers)
    assert steps.status_code == 200
    nodes = [step["node_name"] for step in steps.json()]
    assert nodes == ["extraction", "verification", "quality_review"]
    assert all(step["status"] == "success" for step in steps.json())


def test_supervisor_api_wrong_nesting_404(api_env, client):
    """嵌套在错误 ReviewRun 下的路径 → 404。"""
    headers = _login(api_env, client)
    response = client.get(
        f"/api/v2/workspaces/{api_env['data']['workspace']}/review-runs/999999/supervisor-runs",
        headers=headers,
    )
    assert response.status_code == 404


def test_supervisor_api_general_403(api_env, client):
    """general 工作区调用 Supervisor API → 403（无 general 入口）。"""
    db = api_env["S"]()
    try:
        general = Workspace(owner_user_id=api_env["data"]["user"], name="通用",
                            workspace_type="general", status="active")
        db.add(general)
        db.commit()
        general_id = general.id
    finally:
        db.close()
    headers = _login(api_env, client)
    response = client.get(
        f"/api/v2/workspaces/{general_id}/review-runs/1/supervisor-runs", headers=headers)
    assert response.status_code == 403


def test_supervisor_api_run_not_completed(api_env, client):
    """ReviewRun 未完成时启动 Supervisor → 422 SUPERVISOR_RUN_NOT_COMPLETED。"""
    db = api_env["S"]()
    try:
        run_id = _fresh_run(db, api_env["data"])
        run = db.scalar(select(ReviewRun).where(ReviewRun.id == run_id))
        run.status = "pending"
        db.commit()
    finally:
        db.close()
    headers = _login(api_env, client)
    response = client.post(_supervisor_base(api_env, run_id), headers=headers,
                           json=_launch_payload())
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "SUPERVISOR_RUN_NOT_COMPLETED"


def test_supervisor_api_rejects_invalid_limits(api_env, client):
    """非法数值参数 → 422，且不创建任何运行。"""
    run_id = _api_run(api_env)
    headers = _login(api_env, client)
    url = _supervisor_base(api_env, run_id)
    bad_budget = client.post(url, headers=headers,
                             json=_launch_payload(max_verification_tool_calls=99))
    assert bad_budget.status_code == 422
    bad_retries = client.post(url, headers=headers,
                              json=_launch_payload(max_step_retries=-1))
    assert bad_retries.status_code == 422
    listing = client.get(url, headers=headers)
    assert listing.json() == []


def test_supervisor_api_strict_schema_rejects_coercion(api_env, client):
    """严格 Schema：字符串 bool、整数冒充 bool、浮点冒充整数、未知字段均 422。"""
    run_id = _api_run(api_env)
    headers = _login(api_env, client)
    url = _supervisor_base(api_env, run_id)

    def expect_422(payload, label):
        response = client.post(url, headers=headers, json=payload)
        assert response.status_code == 422, f"{label} 应 422，实际 {response.status_code}: {response.text[:200]}"
        return response

    expect_422(_launch_payload(use_deepseek="false"), '字符串 "false" 冒充 bool')
    expect_422(_launch_payload(use_deepseek="true"), '字符串 "true" 冒充 bool')
    expect_422(_launch_payload(generate_report="true"), 'generate_report 字符串')
    expect_422(_launch_payload(use_deepseek=1), "整数 1 冒充 bool")
    expect_422(_launch_payload(generate_report=0), "整数 0 冒充 bool")
    expect_422(_launch_payload(max_verification_tool_calls=3.5), "浮点冒充整数")
    expect_422(_launch_payload(max_step_retries=1.0), "浮点冒充整数（1.0）")
    expect_422({**_launch_payload(), "unknown_field": 1}, "未知字段")
    expect_422({**_launch_payload(), "max_verification_tool_calls": "5"}, "数字字符串")
    # 所有 422 都不创建 SupervisorRun
    listing = client.get(url, headers=headers)
    assert listing.json() == []


def test_supervisor_api_strict_schema_valid_payload_still_idempotent(api_env, client):
    """合法 payload（显式 bool/int 与默认值）保持 201/200 幂等语义。"""
    run_id = _api_run(api_env)
    headers = _login(api_env, client)
    url = _supervisor_base(api_env, run_id)

    first = client.post(url, headers=headers, json={
        "use_deepseek": False,
        "generate_report": False,
        "max_verification_tool_calls": 5,
        "max_step_retries": 1,
    })
    assert first.status_code == 201
    assert first.json()["reused"] is False

    second = client.post(url, headers=headers, json={})
    assert second.status_code == 200
    assert second.json()["reused"] is True
    assert second.json()["supervisor_run_id"] == first.json()["supervisor_run_id"]
