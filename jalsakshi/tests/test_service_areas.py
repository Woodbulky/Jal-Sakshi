from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_service_areas_returns_vitpur(client: TestClient) -> None:
    areas = client.get("/api/v1/service-areas").json()

    assert [area["code"] for area in areas] == ["demo-vitpur"]
    assert areas[0]["is_demo"] is True
    assert areas[0]["households"] == 380


def test_service_area_is_addressable_by_code_and_by_uuid(client: TestClient) -> None:
    by_code = client.get("/api/v1/service-areas/demo-vitpur")
    assert by_code.status_code == 200

    by_uuid = client.get(f"/api/v1/service-areas/{by_code.json()['id']}")
    assert by_uuid.status_code == 200
    assert by_uuid.json() == by_code.json()


def test_unknown_service_area_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/service-areas/demo-nowhere")

    assert response.status_code == 404
