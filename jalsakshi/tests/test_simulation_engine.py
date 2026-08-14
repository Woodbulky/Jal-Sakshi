"""Engine behaviour: persistence, restart, and ground-truth isolation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.simulation import FaultType
from app.services.memory_repository import InMemoryRepository
from app.simulation.engine import SimulationEngine, SimulationError

pytestmark = pytest.mark.asyncio


async def test_a_tick_writes_one_reading_per_sensor(
    engine: SimulationEngine, repository: InMemoryRepository
) -> None:
    written = await engine.tick()

    assert written == len(repository.sensors) == 17
    assert len({r.sensor_id for r in repository.readings}) == 17


async def test_backfill_is_idempotent(
    engine: SimulationEngine, repository: InMemoryRepository
) -> None:
    end = datetime.now(timezone.utc)
    first = await engine.backfill(hours=2, step_minutes=5, end=end)

    assert first.readings_written == 25 * 17  # 2h inclusive at 5-minute spacing
    count_after_first = len(repository.readings)

    await engine.backfill(hours=2, step_minutes=5, end=end)
    assert len(repository.readings) == count_after_first, "re-running must upsert"


async def test_backfill_history_is_healthy(
    engine: SimulationEngine, repository: InMemoryRepository
) -> None:
    await engine.backfill(hours=6, step_minutes=5)

    flow_sensor = next(s for s in repository.sensors if s.sensor_code == "SNS-PMP-01-FLW")
    values = [
        r.value for r in repository.readings if r.sensor_id == flow_sensor.id and r.value
    ]
    assert values and all(v > 0 for v in values)


async def test_state_survives_a_restart(
    engine: SimulationEngine, repository: InMemoryRepository
) -> None:
    await engine.backfill(hours=3, step_minutes=5)
    run_hours_before = engine._model.state.pump_run_hours  # noqa: SLF001

    restarted = SimulationEngine(
        repository, service_area_ref="demo-vitpur", tick_seconds=300.0, time_scale=1.0
    )
    await restarted.load()

    # The odometer must not reset -- that would read as an anomaly.
    assert restarted._model.state.pump_run_hours == pytest.approx(  # noqa: SLF001
        run_hours_before, rel=0.02
    )
    assert restarted._model.state.oht_level_m > 0  # noqa: SLF001


async def test_inject_accepts_an_asset_code_and_records_ground_truth(
    engine: SimulationEngine, repository: InMemoryRepository
) -> None:
    injection = await engine.inject(fault_type=FaultType.VALVE_CLOSURE, asset_ref="VLV-01")

    valve = next(a for a in repository.assets if a.asset_code == "VLV-01")
    assert injection.asset_id == valve.id
    assert injection.is_active
    assert await engine.list_injections(active_only=True) == [injection]


async def test_inject_rejects_an_unknown_asset(engine: SimulationEngine) -> None:
    with pytest.raises(SimulationError):
        await engine.inject(fault_type=FaultType.VALVE_CLOSURE, asset_ref="VLV-99")


async def test_an_injected_fault_shows_up_in_the_telemetry(
    engine: SimulationEngine, repository: InMemoryRepository
) -> None:
    zone_a = next(s for s in repository.sensors if s.sensor_code == "SNS-ZONE-A-FLW")

    await engine.tick()
    before = (await repository.latest_readings([zone_a.id]))[zone_a.id].value

    await engine.inject(
        fault_type=FaultType.VALVE_CLOSURE, asset_ref="VLV-01", params={"ramp_minutes": 0}
    )
    await engine.tick(datetime.now(timezone.utc) + timedelta(minutes=5))
    after = (await repository.latest_readings([zone_a.id]))[zone_a.id].value

    assert after < 0.2 * before


async def test_back_to_back_ticks_develop_a_fault_as_far_as_timed_ones(
    engine: SimulationEngine, repository: InMemoryRepository
) -> None:
    """The demo console ticks twice in the same second; the valve must still shut.

    Onset rides the simulated clock, which advances one tick's worth per tick.
    Deriving it from wall-clock elapsed instead left the valve ~3% closed here,
    so detection scored a healthy network and raised nothing.
    """
    zone_a = next(s for s in repository.sensors if s.sensor_code == "SNS-ZONE-A-FLW")

    await engine.tick()
    before = (await repository.latest_readings([zone_a.id]))[zone_a.id].value

    # Default 6-minute onset, and two ticks worth 5 simulated minutes each.
    await engine.inject(fault_type=FaultType.VALVE_CLOSURE, asset_ref="VLV-01")
    await engine.tick()
    await engine.tick()

    after = (await repository.latest_readings([zone_a.id]))[zone_a.id].value
    assert after < 0.2 * before


async def test_clearing_a_fault_restores_the_telemetry(
    engine: SimulationEngine, repository: InMemoryRepository
) -> None:
    zone_a = next(s for s in repository.sensors if s.sensor_code == "SNS-ZONE-A-FLW")
    now = datetime.now(timezone.utc)

    await engine.tick(now)
    before = (await repository.latest_readings([zone_a.id]))[zone_a.id].value

    injection = await engine.inject(
        fault_type=FaultType.VALVE_CLOSURE, asset_ref="VLV-01", params={"ramp_minutes": 0}
    )
    await engine.tick(now + timedelta(minutes=5))

    cleared = await engine.clear(injection.id)
    assert not cleared.is_active and cleared.cleared_at is not None

    await engine.tick(now + timedelta(minutes=10))
    after = (await repository.latest_readings([zone_a.id]))[zone_a.id].value

    # Recovery is evidence for the verification step, never a closure by itself.
    assert after == pytest.approx(before, rel=0.15)


async def test_readings_never_carry_the_fault_label(
    engine: SimulationEngine, repository: InMemoryRepository
) -> None:
    """The classifier reads `SensorReading`; the label must not be reachable there."""
    await engine.inject(fault_type=FaultType.PIPELINE_BURST, asset_ref="VLV-02")
    await engine.tick()

    fields = set(repository.readings[0].model_dump())
    assert fields == {"sensor_id", "ts", "value", "quality_flag"}
    assert not any("fault" in field for field in fields)
