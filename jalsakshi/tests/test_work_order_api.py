"""The work-order and agent HTTP surface.

The contract Antigravity builds against, plus the two refusals that must hold
at the API boundary and not only inside the service: no endpoint sets an
arbitrary status, and no endpoint closes a work order.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.schemas.simulation import FaultType
from app.schemas.workorder import WorkOrderStatus
from app.services.memory_repository import InMemoryRepository
from detection_fixtures import build_history


@pytest.fixture
def faulted_client(
    client: TestClient, repository: InMemoryRepository
) -> TestClient:
    """The app with a real closed valve in its telemetry.

    The history is written straight into the repository the app is holding —
    the same offline fixture the detection tests use — because ticking the live
    simulator through an HTTP endpoint would take the wall-clock minutes the
    fault needs to develop.
    """
    asyncio.run(
        build_history(
            repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
        )
    )
    return client


@pytest.fixture
def opened(faulted_client: TestClient) -> dict:
    """A work order created through the API, from a real detection run."""
    run = faulted_client.post("/api/v1/detection/run").json()
    event = run["fault_event"]
    assert event is not None, "fixture needs a detected fault to work with"
    response = faulted_client.post(
        "/api/v1/work-orders",
        json={"fault_event_id": event["id"], "asset_code": "VLV-01"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_the_roster_is_served_for_the_console(client: TestClient) -> None:
    response = client.get("/api/v1/work-orders/roster")

    assert response.status_code == 200
    roles = {member["role"] for member in response.json()}
    assert "VALVE_OPERATOR" in roles
    assert "BLOCK_ENGINEER" in roles


def test_a_work_order_lists_and_reads_back_whole(
    client: TestClient, opened: dict
) -> None:
    listed = client.get("/api/v1/work-orders").json()
    assert any(order["wo_code"] == opened["wo_code"] for order in listed)

    detail = client.get(f"/api/v1/work-orders/{opened['wo_code']}").json()
    assert detail["work_order"]["id"] == opened["id"]
    # The ledger travels with it: the console shows why, not just what.
    assert detail["decisions"]


def test_an_unknown_work_order_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/work-orders/WO-404").status_code == 404


def test_assigning_names_a_crew_from_the_roster(
    client: TestClient, opened: dict
) -> None:
    # DETECTED -> ... -> ASSIGNED is driven by the agent; assigning straight
    # from DETECTED is refused by the lifecycle, which is the point.
    response = client.post(
        f"/api/v1/work-orders/{opened['id']}/assign",
        json={"role": "VALVE_OPERATOR", "fault_type": "VALVE_CLOSURE"},
    )

    assert response.status_code == 400
    assert "DETECTED -> ASSIGNED" in response.json()["detail"]


def test_a_field_update_saying_fixed_does_not_close(
    client: TestClient, opened: dict
) -> None:
    """The inbound half of the n8n/Telegram contract, at the front door."""
    agent_state = client.post("/api/v1/agent/run").json()
    order = agent_state["work_order"]
    assert order["status"] == WorkOrderStatus.ASSIGNED.value

    response = client.post(
        f"/api/v1/work-orders/{order['id']}/field-update",
        json={"message": "Fixed", "sender": "telegram-user"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == WorkOrderStatus.RESTORATION_DETECTED.value
    assert body["closed_at"] is None


def test_there_is_no_endpoint_that_closes_a_work_order(client: TestClient) -> None:
    """Structural: a model or a caller cannot reach for what does not exist."""
    paths = {
        route.path
        for route in client.app.routes
        if getattr(route, "methods", None)
    }
    assert not any(path.endswith("/close") for path in paths)
    # And no endpoint takes a free-form status.
    schema = client.get("/openapi.json").json()
    for path, methods in schema["paths"].items():
        if not path.startswith("/api/v1/work-orders"):
            continue
        for method in methods.values():
            body = method.get("requestBody", {})
            content = body.get("content", {}).get("application/json", {})
            ref = content.get("schema", {}).get("$ref", "")
            name = ref.rsplit("/", 1)[-1]
            properties = schema["components"]["schemas"].get(name, {}).get(
                "properties", {}
            )
            assert "status" not in properties, f"{path} accepts a raw status"


def test_verification_is_the_only_route_to_closed(
    client: TestClient, opened: dict
) -> None:
    agent_state = client.post("/api/v1/agent/run").json()
    order = agent_state["work_order"]
    client.post(
        f"/api/v1/work-orders/{order['id']}/field-update",
        json={"message": "Fixed", "sender": "telegram-user"},
    )

    # The valve is still shut, so the sensors refuse.
    response = client.post(
        f"/api/v1/work-orders/{order['id']}/verify",
        json={"fault_type": "VALVE_CLOSURE"},
    )

    assert response.status_code == 200
    report = response.json()
    assert report["outcome"] in ("FAILED", "PENDING")
    after = client.get(f"/api/v1/work-orders/{order['id']}").json()["work_order"]
    assert after["status"] != WorkOrderStatus.CLOSED.value


def test_escalation_records_a_level_and_a_target(
    client: TestClient, opened: dict
) -> None:
    agent_state = client.post("/api/v1/agent/run").json()
    order = agent_state["work_order"]

    response = client.post(
        f"/api/v1/work-orders/{order['id']}/escalate",
        json={"reason": "no response from the operator"},
    )

    assert response.status_code == 200
    detail = client.get(f"/api/v1/work-orders/{order['id']}").json()
    assert detail["escalations"][0]["level"] == 1
    assert detail["escalations"][0]["to_role"] == "VWSC_SECRETARY"


def test_approval_requires_a_name(client: TestClient, opened: dict) -> None:
    response = client.post(
        f"/api/v1/work-orders/{opened['id']}/approve", json={"approved_by": ""}
    )

    assert response.status_code == 422


def test_the_agent_endpoint_returns_its_reasoning(client: TestClient) -> None:
    response = client.post("/api/v1/agent/run")

    assert response.status_code == 200
    body = response.json()
    assert body["trace"]
    assert body["trace"][0]["node"] == "observe"


def test_the_decision_ledger_is_queryable(client: TestClient, opened: dict) -> None:
    client.post("/api/v1/agent/run")

    response = client.get("/api/v1/agent/decisions")

    assert response.status_code == 200
    entries = response.json()
    assert entries
    assert all(entry["actor"] for entry in entries)


def test_work_order_endpoints_report_503_without_a_database(
    unconfigured_client: TestClient,
) -> None:
    assert unconfigured_client.get("/api/v1/work-orders").status_code == 503
    assert unconfigured_client.post("/api/v1/agent/run").status_code == 503
