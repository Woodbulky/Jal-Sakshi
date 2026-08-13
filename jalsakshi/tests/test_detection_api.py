"""The detection surface, over HTTP, exactly as the console will call it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.simulation import FaultType
from app.services.memory_repository import InMemoryRepository
from detection_fixtures import build_history


@pytest.fixture
def faulted_client(
    settings: Settings, repository: InMemoryRepository, anyio_backend=None
):
    """A client whose network has had a valve wound shut for the last 25 minutes."""
    import asyncio

    asyncio.run(
        build_history(
            repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
        )
    )
    app = create_app(settings)
    app.state.repository = repository
    with TestClient(app) as client:
        yield client


def test_sensor_health_lists_every_instrument(client: TestClient) -> None:
    response = client.get("/api/v1/detection/sensor-health")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 17
    assert {"sensor_code", "trusted", "status", "issues"} <= set(body[0])


def test_run_detects_and_records_the_incident(faulted_client: TestClient) -> None:
    response = faulted_client.post("/api/v1/detection/run")

    assert response.status_code == 200
    run = response.json()
    assert run["classification"]["fault_type"] == "VALVE_CLOSURE"
    assert run["classification"]["asset_code"] == "VLV-01"
    assert run["fault_event"]["status"] == "OPEN"

    incidents = faulted_client.get("/api/v1/incidents").json()
    assert len(incidents) == 1
    assert incidents[0]["fault_type"] == "VALVE_CLOSURE"

    detail = faulted_client.get(f"/api/v1/incidents/{incidents[0]['id']}").json()
    assert detail["anomalies"]
    assert detail["evidence"]["summary"]


def test_run_without_persist_writes_nothing(
    faulted_client: TestClient, repository: InMemoryRepository
) -> None:
    response = faulted_client.post("/api/v1/detection/run?persist=false")

    assert response.status_code == 200
    assert response.json()["anomalies"]
    assert repository.fault_events == []
    assert repository.anomalies == []


def test_anomalies_are_queryable(faulted_client: TestClient) -> None:
    faulted_client.post("/api/v1/detection/run")

    response = faulted_client.get("/api/v1/anomalies?hours=1")

    assert response.status_code == 200
    body = response.json()
    assert body
    assert any(item["sensor_code"] == "SNS-VLV-01-FLW" for item in body)


def test_baseline_profile_is_served_for_the_chart(client: TestClient) -> None:
    response = client.get("/api/v1/detection/baseline/SNS-PMP-01-FLW")

    # No history has been written for this client, so the profile is empty but
    # well-formed rather than a 500.
    assert response.status_code == 200
    assert response.json()["sensor_code"] == "SNS-PMP-01-FLW"


def test_baseline_band_follows_the_day_shape(faulted_client: TestClient) -> None:
    response = faulted_client.get("/api/v1/detection/baseline/SNS-VLV-01-FLW/band")

    assert response.status_code == 200
    band = response.json()
    assert band["baseline"] is not None
    assert band["lower"] < band["baseline"] < band["upper"]


def test_detection_status_is_empty_before_the_first_run(client: TestClient) -> None:
    assert client.get("/api/v1/detection/status").json() is None


def test_endpoints_report_503_without_a_database(
    unconfigured_client: TestClient,
) -> None:
    for path in ("/api/v1/detection/sensor-health", "/api/v1/anomalies"):
        assert unconfigured_client.get(path).status_code == 503
    assert unconfigured_client.post("/api/v1/detection/run").status_code == 503


def test_health_reports_which_classifier_is_loaded(client: TestClient) -> None:
    body = client.get("/api/v1/health").json()

    assert body["classifier"] == "rules"  # no booster configured, by design
