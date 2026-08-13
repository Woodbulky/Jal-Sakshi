"""In-process event bus behind the realtime stream.

Deliberately not Redis, not Kafka, not a message broker. JAL-SAKSHI is one
FastAPI process serving one village's console; a broker would be infrastructure
bought with nothing but a diagram to pay for it. The bus is an asyncio fan-out
with a bounded ring buffer, and the transport in front of it is SSE.

Two properties matter more than throughput:

* **A slow console cannot stall the incident loop.** Each subscriber has its
  own bounded queue. A subscriber that stops draining loses its oldest events
  and is told it did (`dropped`), rather than applying back-pressure to the
  agent that is trying to dispatch a crew.
* **A reconnect does not lose the incident.** Every event carries a monotonic
  id and the last `history` events are retained, so a browser that reconnects
  with `Last-Event-ID` is replayed forward from where it dropped.

`publish` never raises. A realtime feed that could break a state transition
would be worse than no realtime feed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class Event(BaseModel):
    """One thing that happened, as the console sees it."""

    id: int
    type: str
    ts: datetime
    data: dict[str, Any] = Field(default_factory=dict)


class Subscription:
    """One connected client. Async-iterate it; close it when the socket dies."""

    def __init__(self, bus: "EventBus", *, maxsize: int) -> None:
        self._bus = bus
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._closed = False
        #: Events discarded because this client was not keeping up.
        self.dropped = 0

    def _offer(self, event: Event) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop the oldest, not the newest: the current state of an incident
            # is more use to an operator than the state it was in a minute ago.
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover -- racing drain
                pass
            self.dropped += 1
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover -- racing drain
                pass

    def prime(self, events: list[Event]) -> None:
        """Seed the queue with replayed history before live events arrive."""
        for event in events:
            self._offer(event)

    async def get(self, timeout: float | None = None) -> Event | None:
        """Next event, or None when `timeout` elapses (the heartbeat tick)."""
        if timeout is None:
            return await self._queue.get()
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def __aiter__(self) -> AsyncIterator[Event]:
        while not self._closed:
            yield await self._queue.get()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._bus.unsubscribe(self)


class EventBus:
    def __init__(self, *, history: int = 200, queue_size: int = 100) -> None:
        self._subscribers: set[Subscription] = set()
        self._history: deque[Event] = deque(maxlen=history)
        self._queue_size = queue_size
        self._next_id = 1

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish(self, type: str, **data: Any) -> Event | None:
        """Fan out to every live subscriber. Never raises.

        The payload is normalised to JSON here rather than at the transport,
        because the transport is a generator inside an open response: a value
        that failed to encode there would break a live stream mid-incident
        instead of losing one event at the source.
        """
        try:
            payload = json.loads(
                json.dumps(
                    {k: v for k, v in data.items() if v is not None}, default=str
                )
            )
            event = Event(
                id=self._next_id,
                type=type,
                ts=datetime.now(timezone.utc),
                data=payload,
            )
        except Exception:  # noqa: BLE001
            logger.exception("could not build realtime event %s", type)
            return None

        self._next_id += 1
        self._history.append(event)
        for subscriber in list(self._subscribers):
            try:
                subscriber._offer(event)
            except Exception:  # noqa: BLE001, SLF001
                logger.exception("realtime subscriber failed; dropping it")
                self._subscribers.discard(subscriber)
        return event

    def subscribe(self, *, last_event_id: int | None = None) -> Subscription:
        subscription = Subscription(self, maxsize=self._queue_size)
        if last_event_id is not None:
            subscription.prime(self.since(last_event_id))
        self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        self._subscribers.discard(subscription)

    def since(self, last_event_id: int) -> list[Event]:
        """Everything after `last_event_id` that is still in the buffer."""
        return [event for event in self._history if event.id > last_event_id]

    def recent(self, limit: int = 50) -> list[Event]:
        return list(self._history)[-limit:]


__all__ = ["Event", "EventBus", "Subscription"]
