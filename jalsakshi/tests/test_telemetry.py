from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def _client(settings, repository) -> TestClient:
    app = create_app(settings)
    app.state.repository = repository
    return TestClient(app)


def test_asset_telemetry_lists_the_assets_sensors(client: TestClient) -> None:
    body = client.get("/api/v1/assets/PMP-01/telemetry").json()

    assert body["asset"]["asset_code"] == "PMP-01"
    assert {sensor["sensor_type"] for sensor in body["sensors"]} == {
        "FLOW", "PRESSURE_UPSTREAM", "ENERGY", "RUN_HOURS",
    }
    assert body["readings"] == []


def test_asset_telemetry_returns_readings_oldest_first(
    settings, repository_with_readings
) -> None:
    with _client(settings, repository_with_readings) as client:
        body = client.get("/api/v1/assets/PMP-01/telemetry").json()

    readings = body["readings"]
    assert len(readings) == 25
    assert readings[0]["ts"] < readings[-1]["ts"]
    assert readings[-1]["value"] == 820.0


def test_sensor_readings_endpoint_is_addressable_by_code(
    settings, repository_with_readings
) -> None:
    with _client(settings, repository_with_readings) as client:
        response = client.get("/api/v1/sensors/SNS-PMP-01-FLW/readings")

    assert response.status_code == 200
    assert len(response.json()) == 25


def test_unknown_asset_and_sensor_return_404(client: TestClient) -> None:
    assert client.get("/api/v1/assets/VLV-99/telemetry").status_code == 404
    assert client.get("/api/v1/sensors/SNS-NOPE/readings").status_code == 404


def test_window_bounds_are_validated(client: TestClient) -> None:
    assert client.get("/api/v1/assets/PMP-01/telemetry?hours=0").status_code == 422
    assert client.get("/api/v1/assets/PMP-01/telemetry?hours=999").status_code == 422
