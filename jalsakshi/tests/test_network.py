from __future__ import annotations

from fastapi.testclient import TestClient


def test_network_returns_the_vitpur_topology(client: TestClient) -> None:
    network = client.get("/api/v1/service-areas/demo-vitpur/network").json()

    codes = {node["asset_code"] for node in network["nodes"]}
    assert codes == {
        "SRC-01", "PMP-01", "OHT-01", "VLV-01", "VLV-02", "ZONE-A", "ZONE-B",
    }
    assert len(network["edges"]) == 6
    assert len(network["sensors"]) == 17


def test_every_edge_points_at_known_nodes(client: TestClient) -> None:
    network = client.get("/api/v1/service-areas/demo-vitpur/network").json()
    node_ids = {node["id"] for node in network["nodes"]}

    for edge in network["edges"]:
        assert edge["from_asset_id"] in node_ids
        assert edge["to_asset_id"] in node_ids


def test_topology_flows_source_to_zones(client: TestClient) -> None:
    network = client.get("/api/v1/service-areas/demo-vitpur/network").json()
    by_id = {node["id"]: node["asset_code"] for node in network["nodes"]}
    edges = {
        (by_id[edge["from_asset_id"]], by_id[edge["to_asset_id"]])
        for edge in network["edges"]
    }

    assert edges == {
        ("SRC-01", "PMP-01"),
        ("PMP-01", "OHT-01"),
        ("OHT-01", "VLV-01"),
        ("OHT-01", "VLV-02"),
        ("VLV-01", "ZONE-A"),
        ("VLV-02", "ZONE-B"),
    }


def test_sensors_carry_latest_value_when_readings_exist(
    settings, repository_with_readings
) -> None:
    from app.main import create_app

    app = create_app(settings)
    app.state.repository = repository_with_readings

    with TestClient(app) as client:
        network = client.get("/api/v1/service-areas/demo-vitpur/network").json()

    sensors = {sensor["sensor_code"]: sensor for sensor in network["sensors"]}
    assert sensors["SNS-PMP-01-FLW"]["latest"]["value"] == 820.0
    assert sensors["SNS-OHT-01-LVL"]["latest"] is None
