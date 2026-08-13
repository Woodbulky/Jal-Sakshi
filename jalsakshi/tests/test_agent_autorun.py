"""The agent advancing itself off the simulator's tick.

Detection has always run automatically; the agent did not, so an incident
stopped dead after being noticed until somebody called `POST /agent/run`.
These tests pin the parts of running it automatically that are easy to get
wrong: the cadence, the off switch, and — most importantly — that a slow or
broken pass cannot damage the simulator that spawned it.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.core.config import Settings
from app.main import build_tick_hook


class FakeBus:
    """Records published events instead of fanning them out to sockets."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, name: str, **payload: object) -> None:
        self.events.append((name, dict(payload)))


class FakeAgent:
    """Counts passes. `gate` holds a pass open to test overlap."""

    def __init__(self, *, gate: asyncio.Event | None = None) -> None:
        self.runs = 0
        self.gate = gate
        self.fail = False

    async def run(self, *, now: datetime | None = None) -> dict:
        self.runs += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError("groq is having a day")
        return {"trace": [{"node": "observe"}], "halted": None}


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        supabase_url="",
        supabase_service_role_key="",
        detection_autorun=False,  # isolate the agent half
        **overrides,
    )


async def _tick(hook, times: int = 1) -> None:
    """Fire the hook and let any task it spawned actually start."""
    for _ in range(times):
        await hook(datetime.now(timezone.utc))
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_the_agent_runs_on_the_configured_tick_count() -> None:
    """Every third tick, not every tick.

    The agent's own `observe` node runs detection again, so a pass per tick
    would double the detection writes to learn nothing new.
    """
    agent = FakeAgent()
    passes: list[asyncio.Task] = []
    hook = build_tick_hook(
        settings=_settings(agent_autorun=True, agent_autorun_every_ticks=3),
        detection=None,
        agent=agent,
        bus=FakeBus(),
        in_flight=passes,
    )

    await _tick(hook, times=2)
    assert agent.runs == 0, "the agent should not move before its third tick"

    await _tick(hook)
    assert agent.runs == 1

    await _tick(hook, times=3)
    assert agent.runs == 2


@pytest.mark.asyncio
async def test_autorun_off_leaves_the_loop_manual() -> None:
    """The presenter's switch: step through passes by hand while narrating."""
    agent = FakeAgent()
    hook = build_tick_hook(
        settings=_settings(agent_autorun=False, agent_autorun_every_ticks=1),
        detection=None,
        agent=agent,
        bus=FakeBus(),
        in_flight=[],
    )

    await _tick(hook, times=5)

    assert agent.runs == 0


@pytest.mark.asyncio
async def test_a_slow_pass_is_never_overlapped_by_the_next_tick() -> None:
    """A dispatch pass calls an LLM, which can outlast the tick interval.

    Two passes running at once would both read the same open work order and
    both act on it — the one way an automatic loop could dispatch a crew
    twice for one fault.
    """
    gate = asyncio.Event()
    agent = FakeAgent(gate=gate)
    passes: list[asyncio.Task] = []
    hook = build_tick_hook(
        settings=_settings(agent_autorun=True, agent_autorun_every_ticks=1),
        detection=None,
        agent=agent,
        bus=FakeBus(),
        in_flight=passes,
    )

    await _tick(hook, times=4)
    assert agent.runs == 1, "later ticks must skip while a pass is in flight"

    gate.set()  # let the first pass finish
    await asyncio.gather(*passes)

    await _tick(hook)
    assert agent.runs == 2, "a finished pass must not block the next one"


@pytest.mark.asyncio
async def test_a_failing_pass_does_not_break_the_tick() -> None:
    """The simulator must keep sampling through a bad agent pass.

    Telemetry is the evidence every later verification depends on. An agent
    that cannot reach its model is a degraded system; a simulator that stopped
    writing readings is a broken one.
    """
    agent = FakeAgent()
    agent.fail = True
    passes: list[asyncio.Task] = []
    hook = build_tick_hook(
        settings=_settings(agent_autorun=True, agent_autorun_every_ticks=1),
        detection=None,
        agent=agent,
        bus=FakeBus(),
        in_flight=passes,
    )

    await _tick(hook, times=2)
    await asyncio.gather(*passes)

    assert agent.runs == 2, "a failure must not stop later passes"
    assert all(task.done() and task.exception() is None for task in passes)


@pytest.mark.asyncio
async def test_the_tick_still_publishes_for_the_console() -> None:
    """The console watches the bus; automatic passes have to show up there."""
    bus = FakeBus()
    passes: list[asyncio.Task] = []
    hook = build_tick_hook(
        settings=_settings(agent_autorun=True, agent_autorun_every_ticks=1),
        detection=None,
        agent=FakeAgent(),
        bus=bus,
        in_flight=passes,
    )

    await _tick(hook)
    await asyncio.gather(*passes)

    names = [name for name, _ in bus.events]
    assert "simulation.tick" in names
    assert "agent.run" in names
    payload = next(payload for name, payload in bus.events if name == "agent.run")
    assert payload["automatic"] is True
