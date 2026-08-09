import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


SAFE_TEST_ENV = {
    "APP_NAME": "InsightFlow Agent",
    "ENV": "testing",
    "DATABASE_URL": "sqlite:///:memory:",
    "LLM_PROVIDER": "deepseek",
    "LLM_API_KEY": "",
    "DEEPSEEK_MODEL": "deepseek-v4-flash",
    "LLM_BASE_URL": "",
    "LLM_ENABLED": "false",
    "LLM_MAX_RETRIES": "1",
    "EMBEDDING_PROVIDER": "local",
    "VECTOR_STORE": "local",
    "RAG_RETRIEVAL_MODE": "auto",
    "RAG_TOP_K": "5",
    "RAG_CHUNK_SIZE": "800",
    "RAG_CHUNK_OVERLAP": "100",
    # 测试上传目录：所有测试阶段（v2/v3/4A-4C）生成的真实上传文件
    # 均写入 backend/storage/test_uploads，不再污染默认 backend/storage/uploads
    "UPLOAD_DIR": "./storage/test_uploads",
    "CHART_DIR": "./storage/charts",
    "REPORT_DIR": "./storage/reports",
    "CORS_ORIGINS": "http://localhost:5173",
    "TESSERACT_CMD": "",
    "OCR_LANG": "chi_sim+eng",
    "AUTH_SECRET_KEY": "test-only-auth-secret-key-with-at-least-32-chars",
    "SESSION_TTL_SECONDS": "3600",
    "AUTH_COOKIE_SECURE": "false",
    "AUTH_COOKIE_SAMESITE": "lax",
    "ENABLE_LEGACY_V1_API": "true",
    "PASSWORD_MIN_LENGTH": "10",
    "LOGIN_ACCOUNT_LIMIT": "3",
    "LOGIN_IP_LIMIT": "10",
    "REGISTRATION_IP_LIMIT": "10",
    "RESET_REQUEST_LIMIT": "3",
    "AUTH_RATE_WINDOW_SECONDS": "60",
    "AUTH_BLOCK_SECONDS": "60",
    "WORKER_POLL_INTERVAL_SECONDS": "0.05",
    "WORKER_LEASE_SECONDS": "30",
    "WORKER_HEARTBEAT_SECONDS": "5",
    "TASK_MAX_RETRIES": "1",
    "AGENT_MAX_REPLAN_COUNT": "1",
    "AGENT_MAX_REVIEW_RETRIES": "1",
    "TASK_MAX_CLARIFICATION_ROUNDS": "2",
    "TASK_EVENT_HEARTBEAT_SECONDS": "1",
}


for key, value in SAFE_TEST_ENV.items():
    os.environ[key] = value


import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: E402,F401
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = testing_session()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(db_session):
    request_session = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )

    def override_get_db():
        db = request_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ── 会话级存储隔离（Stage 5B 最终补修）────────────────────────────────


def _default_storage_snapshot() -> dict[str, dict]:
    """默认 reports/retrieval 摘要：文件数 + 路径清单 SHA + 内容组合 SHA。

    内容组合 SHA 用规范化文件清单（相对路径 + 内容 SHA-256 排序拼接）计算，
    任何新增/删除/改写都会改变摘要。
    """
    import hashlib

    def _dir_snapshot(rel: str) -> dict:
        root = BACKEND_DIR / rel
        entries: list[tuple[str, str]] = []
        count = 0
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    count += 1
                    entries.append((str(p.relative_to(root)), hashlib.sha256(p.read_bytes()).hexdigest()))
        names_blob = "\n".join(name for name, _ in entries)
        content_blob = "\n".join(f"{name}\t{digest}" for name, digest in entries)
        return {
            "count": count,
            "names_sha": hashlib.sha256(names_blob.encode("utf-8")).hexdigest(),
            "content_sha": hashlib.sha256(content_blob.encode("utf-8")).hexdigest(),
        }

    return {"reports": _dir_snapshot("storage/reports"), "retrieval": _dir_snapshot("storage/retrieval")}


@pytest.fixture(scope="session", autouse=True)
def isolated_storage_session(tmp_path_factory):
    """整个 pytest 会话使用测试专属 uploads/charts/reports/retrieval 根目录。

    - 目录生命周期由 pytest tmp_path_factory 管理（无 mkdtemp 残留、无递归删除）
    - 同步覆盖 settings 属性与环境变量（子进程测试继承同一路径）
    - 替换 retrieval service 模块变量 _INDEX_ROOT（含 ENV 配置覆盖，子进程同样生效）
    - teardown 恢复全部原值并断言；同时断言默认 reports/retrieval 摘要前后一致
    """
    import app.services.engineering_retrieval_service as svc_mod

    storage_root = tmp_path_factory.mktemp("pytest-storage")
    uploads = storage_root / "uploads"
    charts = storage_root / "charts"
    reports = storage_root / "reports"
    retrieval = storage_root / "retrieval" / "workspaces"
    for directory in (uploads, charts, reports, retrieval):
        directory.mkdir(parents=True, exist_ok=True)

    originals = {
        "upload_dir": settings.upload_dir,
        "chart_dir": settings.chart_dir,
        "report_dir": settings.report_dir,
        "index_root": svc_mod._INDEX_ROOT,
        "env": {key: os.environ.get(key) for key in (
            "UPLOAD_DIR", "CHART_DIR", "REPORT_DIR", "ENGINEERING_RETRIEVAL_INDEX_ROOT")},
    }
    default_before = _default_storage_snapshot()

    object.__setattr__(settings, "upload_dir", str(uploads))
    object.__setattr__(settings, "chart_dir", str(charts))
    object.__setattr__(settings, "report_dir", str(reports))
    os.environ["UPLOAD_DIR"] = str(uploads)
    os.environ["CHART_DIR"] = str(charts)
    os.environ["REPORT_DIR"] = str(reports)
    os.environ["ENGINEERING_RETRIEVAL_INDEX_ROOT"] = str(retrieval)
    svc_mod._INDEX_ROOT = retrieval

    yield

    # teardown：恢复全部原值
    object.__setattr__(settings, "upload_dir", originals["upload_dir"])
    object.__setattr__(settings, "chart_dir", originals["chart_dir"])
    object.__setattr__(settings, "report_dir", originals["report_dir"])
    svc_mod._INDEX_ROOT = originals["index_root"]
    for key, value in originals["env"].items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    # 断言恢复完整
    assert settings.upload_dir == originals["upload_dir"], "settings.upload_dir 未恢复"
    assert settings.chart_dir == originals["chart_dir"], "settings.chart_dir 未恢复"
    assert settings.report_dir == originals["report_dir"], "settings.report_dir 未恢复"
    assert svc_mod._INDEX_ROOT == originals["index_root"], "_INDEX_ROOT 未恢复"
    for key, value in originals["env"].items():
        assert os.environ.get(key) == value, f"环境变量 {key} 未恢复"

    # 断言整个会话期间默认 reports/retrieval 未被改写
    default_after = _default_storage_snapshot()
    assert default_after == default_before, (
        "pytest 会话改写了默认 storage/reports 或 storage/retrieval："
        f"{default_before} -> {default_after}"
    )
