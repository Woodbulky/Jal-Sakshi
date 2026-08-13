"""The console's summary endpoint and the asset-health surface behind it."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.schemas.workorder import AssetHealth
from app.services.memory_repository import InMemoryRepository


def test_summary_on_a_quiet_network_reports_nothing_wrong(client: TestClient) -> None:
    summary = client.get("/api/v1/dashboard/summary").json()

    assert summary["service_area_code"] == "demo-vitpur"
    assert summary["open_incidents"] == 0
    assert summary["open_work_orders"] == 0
    assert summary["households_affected"] == 0
    assert summary["active_ttwr_minutes"] is None
    # No incidents and no breaches, but the fixture has no telemetry either, so
    # every instrument is untrusted and the score is penalised for it. A console
    # that cannot see the network must not report a perfect one.
    assert summary["water_health_score"] < 100
    assert summary["sensors"]["trusted"] == 0


def test_summary_carries_the_committee_budget(client: TestClient) -> None:
    """The console shows spending authority beside the incident, not apart."""
    summary = client.get("/api/v1/dashboard/summary").json()

    assert summary["budget_allocated"] is not None
    assert summary["autonomous_approval_limit"] is not None
    assert summary["budget_remaining"] <= summary["budget_allocated"]


def test_summary_counts_untrusted_instruments(client: TestClient) -> None:
    """Sensor trust is a headline number: it gates every dispatch."""
    summary = client.get("/api/v1/dashboard/summary").json()

    sensors = summary["sensors"]
    assert sensors["total"] == sensors["trusted"] + len(sensors["untrusted"])


def test_summary_needs_a_database(unconfigured_client: TestClient) -> None:
    assert unconfigured_client.get("/api/v1/dashboard/summary").status_code == 503


def test_asset_health_is_addressable_by_code(client: TestClient) -> None:
    response = client.get("/api/v1/assets/VLV-01/health")

    assert response.status_code == 200
    body = response.json()
    assert body["asset"]["asset_code"] == "VLV-01"
    # Nothing has failed yet, so there is no health record to report.
    assert body["health"] is None
    assert body["incidents"] == []


def test_asset_health_returns_the_recorded_verdict(
    client: TestClient, repository: InMemoryRepository
) -> None:
    asset = next(a for a in repository.assets if a.asset_code == "VLV-01")
    repository.asset_health.append(
        AssetHealth(
            asset_id=asset.id,
            failure_count=4,
            health_score=0.42,
            recurring_failure=True,
            recommendation="Repeated failure — review the design, do not re-repair.",
        )
    )

    body = client.get("/api/v1/assets/VLV-01/health").json()

    assert body["health"]["failure_count"] == 4
    assert body["health"]["recurring_failure"] is True
    assert "review the design" in body["health"]["recommendation"]


def test_unknown_asset_returns_404(client: TestClient) -> None:
    assert client.get("/api/v1/assets/VLV-99/health").status_code == 404
