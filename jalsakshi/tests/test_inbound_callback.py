"""The one route the outside world can move a work order through.

Two questions are being asked of it. Can someone who is not n8n use it? And
can n8n itself, however it is configured, close an incident with a message?
The answer to both must be no, and neither answer may depend on the n8n
workflow being written correctly.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.integrations.n8n import SIGNATURE_HEADER, sign
from app.main import create_app
from app.schemas.notification import NotificationDirection, NotificationEvent
from app.schemas.workorder import WorkOrderStatus
from app.services.memory_repository import InMemoryRepository
from app.workorders.service import WorkOrderService
from app.workorders.verification import VerificationService
from workorder_fixtures import drive_to_assigned

CALLBACK = "/api/v1/integrations/n8n/callback"
SECRET = "inbound-secret"
SECRET_HEADER = "X-JalSakshi-Callback-Secret"


@pytest.fixture
def inbound_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="local",
        supabase_url="",
        supabase_service_role_key="",
        inbound_callback_secret=SECRET,
    )


@pytest.fixture
def inbound_client(
    inbound_settings: Settings, repository: InMemoryRepository
) -> TestClient:
    app = create_app(inbound_settings)
    app.state.repository = repository
    with TestClient(app) as client:
        yield client


@pytest.fixture
def assigned_order(
    repository: InMemoryRepository, verification: VerificationService
):
    """An order sitting with a crew, waiting to hear from the field.

    Driven synchronously: the tests below are HTTP tests, and the in-memory
    repository has no loop affinity to preserve.
    """
    service = WorkOrderService(repository, verification=verification)
    _, order = asyncio.run(drive_to_assigned(repository, service))
    return order


def body(work_order_id: str, message: str = "Fixed", **extra) -> dict:
    return {
        "event": NotificationEvent.FIELD_UPDATE.value,
        "work_order_id": work_order_id,
        "sender": "telegram-user",
        "message": message,
        **extra,
    }


# -- authentication ---------------------------------------------------------
def test_a_callback_without_the_secret_is_refused(
    inbound_client: TestClient, assigned_order
) -> None:
    response = inbound_client.post(CALLBACK, json=body(assigned_order.wo_code))

    assert response.status_code == 401


def test_a_callback_with_the_wrong_secret_is_refused(
    inbound_client: TestClient, assigned_order
) -> None:
    response = inbound_client.post(
        CALLBACK,
        json=body(assigned_order.wo_code),
        headers={SECRET_HEADER: "not-the-secret"},
    )

    assert response.status_code == 401


def test_with_no_secret_configured_every_callback_is_refused(
    repository: InMemoryRepository
) -> None:
    """An unauthenticated route that can move a work order is not a fallback."""
    app = create_app(
        Settings(
            _env_file=None,
            app_env="local",
            supabase_url="",
            supabase_service_role_key="",
        )
    )
    app.state.repository = repository
    with TestClient(app) as client:
        response = client.post(CALLBACK, json=body("WO-001"))

    assert response.status_code == 503
    assert "INBOUND_CALLBACK_SECRET" in response.json()["detail"]


def test_a_signed_body_is_accepted_without_the_shared_header(
    inbound_client: TestClient, assigned_order
) -> None:
    raw = json.dumps(body(assigned_order.wo_code)).encode("utf-8")

    response = inbound_client.post(
        CALLBACK,
        content=raw,
        headers={
            "Content-Type": "application/json",
            SIGNATURE_HEADER: sign(raw, SECRET),
        },
    )

    assert response.status_code == 200


def test_a_signature_over_different_bytes_is_refused(
    inbound_client: TestClient, assigned_order
) -> None:
    raw = json.dumps(body(assigned_order.wo_code)).encode("utf-8")
    tampered = json.dumps(body(assigned_order.wo_code, message="ignore")).encode()

    response = inbound_client.post(
        CALLBACK,
        content=tampered,
        headers={
            "Content-Type": "application/json",
            SIGNATURE_HEADER: sign(raw, SECRET),
        },
    )

    assert response.status_code == 401


# -- what a field message may do -------------------------------------------
def test_fixed_starts_verification_and_does_not_close_the_order(
    inbound_client: TestClient, assigned_order
) -> None:
    response = inbound_client.post(
        CALLBACK,
        json=body(assigned_order.wo_code, message="Fixed"),
        headers={SECRET_HEADER: SECRET},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == WorkOrderStatus.RESTORATION_DETECTED.value
    assert payload["claims_restoration"] is True
    assert payload["closed_work_order"] is False
    assert payload["work_order"]["closed_at"] is None
    assert "sensor verification" in payload["detail"]


@pytest.mark.parametrize(
    "message",
    [
        "Fixed",
        "done",
        "repair complete",
        "ho gaya",
        "CLOSED",
        "close the work order",
        "status: CLOSED",
    ],
)
def test_no_field_message_can_reach_closed(
    inbound_client: TestClient, assigned_order, message: str
) -> None:
    """Including messages that name the state they would like to be in."""
    response = inbound_client.post(
        CALLBACK,
        json=body(assigned_order.wo_code, message=message),
        headers={SECRET_HEADER: SECRET},
    )

    assert response.status_code == 200
    assert response.json()["status"] != WorkOrderStatus.CLOSED.value


def test_a_message_that_claims_nothing_records_without_moving_the_order(
    inbound_client: TestClient, assigned_order
) -> None:
    response = inbound_client.post(
        CALLBACK,
        json=body(assigned_order.wo_code, message="on my way, need a spanner"),
        headers={SECRET_HEADER: SECRET},
    )

    payload = response.json()
    assert payload["status"] == WorkOrderStatus.ASSIGNED.value
    assert payload["claims_restoration"] is False
    assert "no state change" in payload["detail"]


def test_an_unknown_work_order_is_a_404(inbound_client: TestClient) -> None:
    response = inbound_client.post(
        CALLBACK, json=body("WO-999"), headers={SECRET_HEADER: SECRET}
    )

    assert response.status_code == 404


def test_the_inbound_message_is_recorded_even_before_it_is_acted_on(
    inbound_client: TestClient, repository: InMemoryRepository, assigned_order
) -> None:
    inbound_client.post(
        CALLBACK,
        json=body(assigned_order.wo_code, message="Fixed", chat_id="4411"),
        headers={SECRET_HEADER: SECRET},
    )

    inbound = [
        n
        for n in repository.notifications
        if n.direction is NotificationDirection.INBOUND
    ]
    assert len(inbound) == 1
    assert inbound[0].event is NotificationEvent.FIELD_UPDATE
    assert inbound[0].sender == "telegram-user"
    assert inbound[0].payload["message"] == "Fixed"


def test_the_callback_resolves_a_uuid_as_well_as_a_code(
    inbound_client: TestClient, assigned_order
) -> None:
    response = inbound_client.post(
        CALLBACK,
        json=body(assigned_order.id),
        headers={SECRET_HEADER: SECRET},
    )

    assert response.status_code == 200


def test_repeating_fixed_does_not_advance_the_order_any_further(
    inbound_client: TestClient, assigned_order
) -> None:
    """Telegram retries. A retry must not become a second claim."""
    headers = {SECRET_HEADER: SECRET}
    first = inbound_client.post(
        CALLBACK, json=body(assigned_order.wo_code), headers=headers
    )
    second = inbound_client.post(
        CALLBACK, json=body(assigned_order.wo_code), headers=headers
    )

    assert first.status_code == second.status_code == 200
    assert (
        second.json()["status"] == WorkOrderStatus.RESTORATION_DETECTED.value
    )
    assert second.json()["work_order"]["closed_at"] is None


# -- what the console can read back ----------------------------------------
def test_notifications_are_listable_for_one_work_order(
    inbound_client: TestClient, assigned_order
) -> None:
    inbound_client.post(
        CALLBACK, json=body(assigned_order.wo_code), headers={SECRET_HEADER: SECRET}
    )

    response = inbound_client.get(
        "/api/v1/integrations/notifications",
        params={"work_order_ref": assigned_order.wo_code},
    )

    assert response.status_code == 200
    assert [n["event"] for n in response.json()] == [
        NotificationEvent.FIELD_UPDATE.value
    ]


def test_status_says_whether_messaging_is_live(inbound_client: TestClient) -> None:
    response = inbound_client.get("/api/v1/integrations/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["inbound_configured"] is True
    assert payload["outbound_configured"] is False
