"""Realtime stream for the operations console.

Server-Sent Events rather than WebSocket, because everything here flows one
way: the console watches, it does not command. SSE reconnects on its own,
carries `Last-Event-ID` for free, and survives proxies that mangle upgrades.
The API contract allows either; this is the one that costs the frontend a
single `EventSource`.

Event types on the wire:

    work_order.opened        an incident became a commitment
    work_order.status        any state transition, with its previous state
    work_order.sla_breached  a deadline passed
    work_order.escalated     raised to the next authority
    verification.result      all four outcomes, PENDING included
    field.update             a Telegram reply landed
    detection.run            a detection pass finished
    simulation.tick          the hydraulic model advanced

`GET /events/recent` returns the same events as a plain list, so a console can
paint its first frame without waiting for something to happen.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import EventBusDep, SettingsDep
from app.integrations.events import Event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


def _frame(event: Event) -> str:
    return (
        f"id: {event.id}\n"
        f"event: {event.type}\n"
        f"data: {json.dumps(event.model_dump(mode='json'), separators=(',', ':'))}\n\n"
    )


@router.get("/recent", response_model=list[Event])
async def recent_events(
    bus: EventBusDep, limit: int = Query(default=50, ge=1, le=200)
) -> list[Event]:
    """The last events, for a console painting its first frame."""
    return bus.recent(limit)


@router.get("/stream")
async def stream(
    request: Request,
    bus: EventBusDep,
    settings: SettingsDep,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Live incident events. Reconnect with `Last-Event-ID` to catch up."""
    resume_from: int | None = None
    if last_event_id and last_event_id.isdigit():
        resume_from = int(last_event_id)

    subscription = bus.subscribe(last_event_id=resume_from)
    heartbeat = settings.realtime_heartbeat_seconds

    async def publisher() -> AsyncIterator[str]:
        # Tell the browser how long to wait before reconnecting, and open the
        # stream immediately so a proxy does not sit on an empty response.
        yield f"retry: {int(heartbeat * 1000)}\n\n"
        yield ": connected\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                event = await subscription.get(timeout=heartbeat)
                if event is None:
                    # Idle. A comment frame is not an event; it only keeps the
                    # connection from being reaped.
                    yield ": ping\n\n"
                    continue
                yield _frame(event)
        except asyncio.CancelledError:  # pragma: no cover -- client vanished
            raise
        finally:
            subscription.close()
            if subscription.dropped:
                logger.warning(
                    "realtime client fell behind and lost %d events",
                    subscription.dropped,
                )

    return StreamingResponse(
        publisher(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # nginx buffers text/event-stream into uselessness without this.
            "X-Accel-Buffering": "no",
        },
    )
