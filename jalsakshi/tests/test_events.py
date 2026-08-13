"""Realtime: what the console is told, and what it costs the incident loop.

The interesting cases are not "an event arrives". They are the ones where the
console misbehaves — a browser that stops reading, a laptop that sleeps through
an incident and reconnects — and the requirement that none of that reaches the
agent dispatching a crew.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.v1.events import stream
from app.core.config import Settings
from app.integrations.events import EventBus
from app.main import create_app
from app.schemas.simulation import FaultType
from app.schemas.workorder import WorkOrderStatus
from app.services.memory_repository import InMemoryRepository
from app.workorders.service import WorkOrderService
from app.workorders.verification import VerificationService
from workorder_fixtures import drive_to_assigned, open_order


# -- the bus ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_every_subscriber_sees_every_event_in_order() -> None:
    bus = EventBus()
    first = bus.subscribe()
    second = bus.subscribe()

    await bus.publish("work_order.opened", wo_code="WO-001")
    await bus.publish("work_order.status", wo_code="WO-001", status="TRIAGING")

    for subscription in (first, second):
        opened = await subscription.get(timeout=1)
        status = await subscription.get(timeout=1)
        assert opened.type == "work_order.opened"
        assert status.data["status"] == "TRIAGING"
        assert status.id == opened.id + 1


@pytest.mark.asyncio
async def test_a_console_that_stops_reading_loses_events_and_nothing_else() -> None:
    """Back-pressure from a browser must not reach the incident loop."""
    bus = EventBus(queue_size=2)
    stalled = bus.subscribe()

    for index in range(6):
        published = await bus.publish("work_order.status", seq=index)
        assert published is not None  # publish never blocks and never fails

    assert stalled.dropped == 4
    # What is left is the newest, not the oldest: current state beats history.
    remaining = [(await stalled.get(timeout=1)).data["seq"] for _ in range(2)]
    assert remaining == [4, 5]


@pytest.mark.asyncio
async def test_a_reconnecting_console_is_replayed_from_where_it_dropped() -> None:
    bus = EventBus()
    await bus.publish("work_order.opened", wo_code="WO-001")
    missed = await bus.publish("work_order.status", status="ASSIGNED")
    await bus.publish("verification.result", outcome="PASSED")

    resumed = bus.subscribe(last_event_id=missed.id - 1)

    replayed = [(await resumed.get(timeout=1)).type for _ in range(2)]
    assert replayed == ["work_order.status", "verification.result"]


@pytest.mark.asyncio
async def test_a_payload_that_is_not_json_cannot_break_a_live_stream() -> None:
    """Normalised at the source, where losing an event is the worst outcome."""
    bus = EventBus()

    event = await bus.publish("work_order.status", deadline=object())

    assert event is not None
    assert isinstance(event.data["deadline"], str)
    json.dumps(event.model_dump(mode="json"))  # what the transport will do


@pytest.mark.asyncio
async def test_a_closed_subscription_stops_receiving() -> None:
    bus = EventBus()
    subscription = bus.subscribe()
    subscription.close()

    await bus.publish("work_order.status", status="ASSIGNED")

    assert bus.subscriber_count == 0


# -- what the lifecycle publishes ------------------------------------------
@pytest.mark.asyncio
async def test_every_state_change_reaches_the_console(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    bus = EventBus()
    service = WorkOrderService(repository, verification=verification, events=bus)

    _, order = await drive_to_assigned(repository, service)

    types = [event.type for event in bus.recent(50)]
    assert types[0] == "work_order.opened"
    assert types.count("work_order.status") >= 4  # triage, classify, assess, assign
    last = bus.recent(1)[0]
    assert last.data["status"] == WorkOrderStatus.ASSIGNED.value
    assert last.data["previous_status"] == WorkOrderStatus.ASSESSED.value
    assert last.data["wo_code"] == order.wo_code


@pytest.mark.asyncio
async def test_a_field_message_is_published_as_a_claim_not_a_closure(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    bus = EventBus()
    service = WorkOrderService(repository, verification=verification, events=bus)
    _, order = await drive_to_assigned(repository, service)

    await service.record_field_update(order, message="Fixed", sender="Ramesh")

    update = next(e for e in bus.recent(50) if e.type == "field.update")
    assert update.data["claims_restoration"] is True
    assert update.data["closes_work_order"] is False


@pytest.mark.asyncio
async def test_a_broken_event_bus_does_not_stop_a_dispatch(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    class Broken:
        async def publish(self, *args, **kwargs):
            raise RuntimeError("realtime bug")

    service = WorkOrderService(repository, verification=verification, events=Broken())

    _, order = await drive_to_assigned(repository, service)

    assert order.status is WorkOrderStatus.ASSIGNED


@pytest.mark.asyncio
async def test_an_sla_breach_is_announced(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    from datetime import timedelta  # noqa: PLC0415

    bus = EventBus()
    service = WorkOrderService(repository, verification=verification, events=bus)
    _, order = await drive_to_assigned(repository, service)

    await service.check_sla(order, now=order.sla_deadline + timedelta(minutes=5))

    breach = next(e for e in bus.recent(50) if e.type == "work_order.sla_breached")
    assert breach.data["minutes_past_deadline"] == pytest.approx(5.0, abs=0.5)


# -- the stream ------------------------------------------------------------
@pytest.fixture
def stream_client(repository: InMemoryRepository) -> TestClient:
    app = create_app(
        Settings(
            _env_file=None,
            app_env="local",
            supabase_url="",
            supabase_service_role_key="",
            realtime_heartbeat_seconds=0.2,
        )
    )
    app.state.repository = repository
    with TestClient(app) as client:
        yield client


def test_recent_lets_a_console_paint_its_first_frame(
    stream_client: TestClient, repository: InMemoryRepository, verification
) -> None:
    service = WorkOrderService(
        repository,
        verification=verification,
        events=stream_client.app.state.events,
    )
    asyncio.run(open_order(repository, service, fault_type=FaultType.PIPELINE_BURST))

    response = stream_client.get("/api/v1/events/recent")

    assert response.status_code == 200
    assert response.json()[0]["type"] == "work_order.opened"


async def _read_stream(bus: EventBus, *, last_event_id: str | None, chunks: int):
    """Drive the SSE response generator directly.

    A live SSE response never ends, so it is read here rather than through the
    test client: this asserts the framing and the replay without needing a
    socket that is never going to close.
    """
    settings = Settings(_env_file=None, realtime_heartbeat_seconds=0.05)
    headers = [(b"host", b"testserver")]
    if last_event_id:
        headers.append((b"last-event-id", last_event_id.encode()))
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/events/stream",
            "headers": headers,
            "query_string": b"",
        },
        receive=_never,
    )
    response = await stream(
        request, bus, settings, last_event_id=last_event_id  # type: ignore[arg-type]
    )
    collected: list[str] = []
    iterator = response.body_iterator
    for _ in range(chunks):
        chunk = await asyncio.wait_for(iterator.__anext__(), timeout=2)
        collected.append(chunk if isinstance(chunk, str) else chunk.decode())
    await iterator.aclose()
    return collected


async def _never() -> dict:
    await asyncio.Event().wait()  # pragma: no cover -- cancelled by the caller
    return {}


@pytest.mark.asyncio
async def test_the_stream_replays_missed_events_as_sse_frames(
    repository: InMemoryRepository, verification: VerificationService
) -> None:
    bus = EventBus()
    service = WorkOrderService(repository, verification=verification, events=bus)
    await open_order(repository, service)

    chunks = await _read_stream(bus, last_event_id="0", chunks=3)

    frame = chunks[-1]
    assert chunks[0].startswith("retry:")
    assert "event: work_order.opened" in frame
    assert frame.startswith("id: 1\n")
    data = json.loads(frame.split("data: ", 1)[1])
    assert data["type"] == "work_order.opened"
    assert data["data"]["wo_code"].startswith("WO-")


@pytest.mark.asyncio
async def test_an_idle_stream_is_kept_alive_rather_than_closed() -> None:
    """No incidents in progress: the connection holds with comment frames."""
    chunks = await _read_stream(EventBus(), last_event_id=None, chunks=3)

    assert chunks[0].startswith("retry:")
    assert chunks[1] == ": connected\n\n"
    assert chunks[2] == ": ping\n\n"
