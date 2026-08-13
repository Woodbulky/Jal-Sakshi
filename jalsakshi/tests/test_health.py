from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_reports_ok_when_repository_is_present(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"
    assert body["app_env"] == "local"


def test_health_reports_degraded_without_a_database(
    unconfigured_client: TestClient,
) -> None:
    body = unconfigured_client.get("/api/v1/health").json()

    assert body["status"] == "degraded"
    assert body["database"] == "unconfigured"


def test_data_endpoints_return_503_without_a_database(
    unconfigured_client: TestClient,
) -> None:
    response = unconfigured_client.get("/api/v1/service-areas")

    assert response.status_code == 503
    assert "SUPABASE_URL" in response.json()["detail"]
