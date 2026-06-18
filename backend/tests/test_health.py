from fastapi.testclient import TestClient

from app.main import app


def test_health_api_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app_name"] == "InsightFlow Agent"
