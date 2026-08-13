"""The simulator control surface, as the demo console drives it."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_status_reports_a_loaded_idle_simulator(client: TestClient) -> None:
    response = client.get("/api/v1/simulation/status")

    assert response.status_code == 200
    body = response.json()
    assert body["service_area_code"] == "demo-vitpur"
    assert body["running"] is False
    assert body["sensor_count"] == 17
    assert body["active_injections"] == []


def test_a_manual_tick_produces_telemetry_on_the_network_endpoint(
    client: TestClient,
) -> None:
    assert client.post("/api/v1/simulation/tick").status_code == 200

    network = client.get("/api/v1/service-areas/demo-vitpur/network").json()
    latest = {s["sensor_code"]: s["latest"] for s in network["sensors"]}
    assert all(reading is not None for reading in latest.values())
    assert latest["SNS-PMP-01-FLW"]["value"] > 0


def test_inject_then_clear_follows_the_demo_script(client: TestClient) -> None:
    created = client.post(
        "/api/v1/simulation/inject",
        json={
            "service_area_id": "demo-vitpur",
            "fault_type": "VALVE_CLOSURE",
            "asset_id": "VLV-01",
        },
    )
    assert created.status_code == 201
    injection = created.json()
    assert injection["fault_type"] == "VALVE_CLOSURE"

    active = client.get("/api/v1/simulation/status").json()["active_injections"]
    assert [i["id"] for i in active] == [injection["id"]]

    cleared = client.post(f"/api/v1/simulation/injections/{injection['id']}/clear")
    assert cleared.status_code == 200
    assert cleared.json()["is_active"] is False
    assert client.get("/api/v1/simulation/status").json()["active_injections"] == []


def test_injecting_on_an_unknown_asset_is_a_400(client: TestClient) -> None:
    response = client.post(
        "/api/v1/simulation/inject",
        json={"fault_type": "PUMP_FAILURE", "asset_id": "PMP-99"},
    )
    assert response.status_code == 400
    assert "PMP-99" in response.json()["detail"]


def test_clearing_an_unknown_injection_is_a_404(client: TestClient) -> None:
    missing = "00000000-0000-0000-0000-0000000000ff"
    response = client.post(f"/api/v1/simulation/injections/{missing}/clear")
    assert response.status_code == 404


def test_backfill_gives_detection_a_baseline(client: TestClient) -> None:
    response = client.post("/api/v1/simulation/backfill?hours=6&step_minutes=5")

    assert response.status_code == 200
    body = response.json()
    assert body["readings_written"] == 73 * 17
    assert body["hours"] == 6

    telemetry = client.get("/api/v1/assets/PMP-01/telemetry?hours=6").json()
    assert len(telemetry["readings"]) > 200


def test_telemetry_never_leaks_the_injected_fault(client: TestClient) -> None:
    """The whole demo rests on this: the agent must diagnose, not look it up."""
    client.post(
        "/api/v1/simulation/inject",
        json={"fault_type": "PIPELINE_BURST", "asset_id": "VLV-02"},
    )
    client.post("/api/v1/simulation/tick")

    for path in (
        "/api/v1/service-areas/demo-vitpur/network",
        "/api/v1/assets/VLV-02/telemetry?hours=2",
        "/api/v1/sensors/SNS-VLV-02-FLW/readings?hours=2",
    ):
        body = client.get(path).text
        assert "PIPELINE_BURST" not in body
        assert "fault" not in body.lower()


def test_the_simulator_is_unavailable_without_a_database(
    unconfigured_client: TestClient,
) -> None:
    response = unconfigured_client.get("/api/v1/simulation/status")

    assert response.status_code == 503
    assert "SUPABASE_SERVICE_ROLE_KEY" in response.json()["detail"]
