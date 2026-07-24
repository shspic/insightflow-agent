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
    "UPLOAD_DIR": "./storage/uploads",
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
