"""Outbound messaging: what leaves the system, and what happens when it can't.

The claim being tested is not "we can POST JSON". It is that the messaging
layer is *subordinate* to the water logic: an n8n outage degrades JAL-SAKSHI to
a system that still detects, dispatches, verifies and closes correctly and
records that it could not tell anyone. Every failure test here asserts the work
order came through unharmed.
"""

from __future__ import annotations

import hmac
import json
from datetime import timedelta

import httpx
import pytest

from app.core.config import Settings
from app.integrations.n8n import EVENT_HEADER, SIGNATURE_HEADER, N8nNotifier, sign
from app.schemas.notification import (
    NotificationDirection,
    NotificationEvent,
    NotificationStatus,
)
from app.schemas.simulation import FaultType
from app.schemas.workorder import WorkOrderStatus
from app.services.memory_repository import InMemoryRepository
from app.workorders.service import WorkOrderService
from app.workorders.verification import VerificationService
from detection_fixtures import build_history
from workorder_fixtures import drive_to_assigned, open_order

pytestmark = pytest.mark.asyncio

WEBHOOK = "https://n8n.example.test/webhook/jal-sakshi"
SECRET = "shared-secret-for-tests"


class Capture:
    """A fake n8n. Records what arrived; answers however the test wants."""

    def __init__(self, *, status_code: int = 200, body: dict | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._status_code = status_code
        self._body = body if body is not None else {"ok": True}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status_code, json=self._body)

    @property
    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    @property
    def payloads(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]


def make_settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        app_env="local",
        supabase_url="",
        supabase_service_role_key="",
        n8n_webhook_url=WEBHOOK,
        n8n_webhook_secret=SECRET,
        public_base_url="https://jal-sakshi.example.test",
    )
    base.update(overrides)
    return Settings(**base)


def build_service(
    repository: InMemoryRepository,
    verification: VerificationService,
    capture: Capture | None = None,
    **setting_overrides,
) -> tuple[WorkOrderService, Capture]:
    capture = capture or Capture()
    notifier = N8nNotifier(
        repository, make_settings(**setting_overrides), client=capture.client
    )
    return (
        WorkOrderService(repository, verification=verification, notifier=notifier),
        capture,
    )


# -- the contract -----------------------------------------------------------
async def test_dispatch_posts_the_contract_payload(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    service, capture = build_service(repository, verification)

    _, order = await drive_to_assigned(repository, service, households=212)

    assert len(capture.requests) == 1
    payload = capture.payloads[0]
    # Field names are the n8n workflow author's, not ours to rename.
    assert payload["event"] == NotificationEvent.WORK_ORDER_CREATED.value
    assert payload["work_order_id"] == order.wo_code
    assert payload["asset_id"] == "VLV-01"
    assert payload["fault_type"] == FaultType.VALVE_CLOSURE.value
    assert payload["service_area"]
    assert payload["assigned_to"]
    assert payload["sla_hours"] == order.sla_hours
    assert payload["households_affected"] == 212
    assert payload["callback_url"].endswith("/api/v1/integrations/n8n/callback")


async def test_the_message_states_the_facts_a_field_actor_needs(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    service, capture = build_service(repository, verification)

    _, order = await drive_to_assigned(repository, service, households=212)

    text = capture.payloads[0]["text"]
    assert "JAL-SAKSHI WORK ORDER" in text
    assert "Valve Closure" in text  # not VALVE_CLOSURE
    assert "VLV-01" in text
    assert "212" in text
    assert order.wo_code in text
    # The promise the product is built on, said to the person replying.
    assert "Sensors will confirm restoration" in text


async def test_the_body_is_signed_over_the_bytes_sent(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    service, capture = build_service(repository, verification)

    await drive_to_assigned(repository, service)

    request = capture.requests[0]
    assert request.headers[EVENT_HEADER] == NotificationEvent.WORK_ORDER_CREATED.value
    assert hmac.compare_digest(
        request.headers[SIGNATURE_HEADER], sign(request.content, SECRET)
    )
    # A body altered in flight fails the check.
    assert sign(request.content + b" ", SECRET) != request.headers[SIGNATURE_HEADER]


async def test_an_unsigned_deployment_still_sends(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    service, capture = build_service(repository, verification, n8n_webhook_secret="")

    await drive_to_assigned(repository, service)

    assert SIGNATURE_HEADER not in capture.requests[0].headers


# -- every attempt is evidence ---------------------------------------------
async def test_a_sent_message_is_recorded_against_the_work_order(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    service, _ = build_service(repository, verification)

    _, order = await drive_to_assigned(repository, service)

    sent = await repository.list_notifications(work_order_id=order.id)
    assert [n.status for n in sent] == [NotificationStatus.SENT]
    assert sent[0].direction is NotificationDirection.OUTBOUND
    assert sent[0].sent_at is not None
    assert sent[0].external_message_id is None  # the fake returns {"ok": true}


async def test_a_telegram_message_id_is_kept_when_the_workflow_returns_one(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    capture = Capture(body={"result": {"message_id": 4711}})
    service, _ = build_service(repository, verification, capture)

    _, order = await drive_to_assigned(repository, service)

    sent = await repository.list_notifications(work_order_id=order.id)
    assert sent[0].external_message_id == "4711"


# -- failure is not the incident's problem ---------------------------------
async def test_without_a_webhook_the_message_is_composed_and_recorded_not_sent(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    service, capture = build_service(repository, verification, n8n_webhook_url="")

    _, order = await drive_to_assigned(repository, service)

    assert capture.requests == []
    assert order.status is WorkOrderStatus.ASSIGNED
    recorded = await repository.list_notifications(work_order_id=order.id)
    assert recorded[0].status is NotificationStatus.SKIPPED
    # The console can still show the village exactly what would have been sent.
    assert "JAL-SAKSHI WORK ORDER" in recorded[0].payload["text"]


async def test_an_n8n_error_response_fails_the_message_not_the_dispatch(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    capture = Capture(status_code=500, body={"error": "workflow not active"})
    service, _ = build_service(repository, verification, capture)

    _, order = await drive_to_assigned(repository, service)

    assert order.status is WorkOrderStatus.ASSIGNED
    assert order.assigned_role is not None  # a crew is still committed
    failed = await repository.list_notifications(work_order_id=order.id)
    assert failed[0].status is NotificationStatus.FAILED
    assert "500" in failed[0].error


async def test_an_unreachable_webhook_fails_the_message_not_the_dispatch(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("n8n is down", request=request)

    notifier = N8nNotifier(
        repository,
        make_settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(explode)),
    )
    service = WorkOrderService(
        repository, verification=verification, notifier=notifier
    )

    _, order = await drive_to_assigned(repository, service)

    assert order.status is WorkOrderStatus.ASSIGNED
    failed = await repository.list_notifications(work_order_id=order.id)
    assert failed[0].status is NotificationStatus.FAILED
    assert failed[0].error


async def test_a_timeout_records_a_reason_even_though_it_stringifies_empty(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    """`str(httpx.ReadTimeout())` is `''`, and an empty reason is no reason.

    A phone on a tunnel times out occasionally, and FAILED with a blank error
    sends an operator looking at signatures instead of at the network.
    """

    def stall(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)

    notifier = N8nNotifier(
        repository,
        make_settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(stall)),
    )
    service = WorkOrderService(
        repository, verification=verification, notifier=notifier
    )

    _, order = await drive_to_assigned(repository, service)

    failed = await repository.list_notifications(work_order_id=order.id)
    assert failed[0].status is NotificationStatus.FAILED
    assert failed[0].error == "ReadTimeout"


async def test_a_notifier_that_raises_outright_does_not_stop_the_lifecycle(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    class Broken:
        async def notify(self, *args, **kwargs):
            raise RuntimeError("integration bug")

    service = WorkOrderService(
        repository, verification=verification, notifier=Broken()
    )

    _, order = await drive_to_assigned(repository, service)

    assert order.status is WorkOrderStatus.ASSIGNED


# -- which moments produce a message ---------------------------------------
async def test_approval_needed_asks_the_committee_before_anyone_is_sent(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    service, capture = build_service(repository, verification)

    _, order = await open_order(
        repository, service, fault_type=FaultType.PUMP_FAILURE, asset_code="PMP-01"
    )
    order = await service.triage(order)
    from workorder_fixtures import make_classification  # noqa: PLC0415

    order = await service.classify(
        order, make_classification(fault_type=FaultType.PUMP_FAILURE)
    )
    order = await service.assess(order)

    assert order.requires_approval  # pump work is over the ₹15,000 limit
    events = [payload["event"] for payload in capture.payloads]
    assert events == [NotificationEvent.APPROVAL_REQUIRED.value]
    assert "APPROVAL NEEDED" in capture.payloads[0]["text"]
    assert "No crew has been dispatched" in capture.payloads[0]["text"]


async def test_an_escalation_sends_one_message_not_a_second_dispatch(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    service, capture = build_service(repository, verification)
    _, order = await drive_to_assigned(repository, service)
    capture.requests.clear()

    await service.escalate(order, reason="SLA passed")

    events = [payload["event"] for payload in capture.payloads]
    assert events == [NotificationEvent.WORK_ORDER_ESCALATED.value]
    assert "ESCALATION" in capture.payloads[0]["text"]


async def test_a_verified_closure_tells_the_crew_the_sensors_agreed(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    service, capture = build_service(repository, verification)
    event, order = await drive_to_assigned(repository, service, now=now)
    order = await service.record_field_update(order, message="Fixed", now=now)

    for injection in list(repository.fault_injections):
        await repository.clear_fault_injection(injection.id)
    later = now + timedelta(minutes=30)
    await build_history(repository, now=later)
    capture.requests.clear()

    order, report = await service.verify(
        order,
        fault_type=FaultType.VALVE_CLOSURE,
        detected_at=event.detected_at,
        now=later,
    )

    assert order.status is WorkOrderStatus.CLOSED
    events = [payload["event"] for payload in capture.payloads]
    assert events == [NotificationEvent.WORK_ORDER_CLOSED.value]
    text = capture.payloads[0]["text"]
    assert "CLOSED" in text
    assert "Closed on sensor evidence, not on the field report." in text
    assert report.ttwr_minutes is not None


async def test_a_failed_verification_sends_the_crew_back(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    service, capture = build_service(repository, verification)
    _, order = await drive_to_assigned(repository, service, now=now)
    order = await service.record_field_update(order, message="Fixed", now=now)

    # The valve was never actually opened.
    later = now + timedelta(minutes=15)
    await build_history(
        repository,
        fault_type=FaultType.VALVE_CLOSURE,
        asset_code="VLV-01",
        now=later,
    )
    capture.requests.clear()

    order, _ = await service.verify(
        order, fault_type=FaultType.VALVE_CLOSURE, now=later
    )

    assert order.status is WorkOrderStatus.REOPENED
    events = [payload["event"] for payload in capture.payloads]
    assert events == [NotificationEvent.WORK_ORDER_REOPENED.value]
    assert "REOPENED" in capture.payloads[0]["text"]


async def test_nothing_is_sent_for_states_nobody_needs_told_about(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    service, capture = build_service(repository, verification)

    _, order = await open_order(repository, service)
    await service.triage(order)

    assert capture.requests == []
