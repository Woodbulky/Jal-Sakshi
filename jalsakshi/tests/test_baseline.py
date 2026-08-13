"""The learned day-shape, and why a global mean would not do."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.analytics.baseline import (
    SKIP_BASELINE_TYPES,
    BaselineStore,
    build_sensor_baseline,
    minutes_of_day,
)
from app.schemas.network import QualityFlag, SensorReading, SensorType
from app.seed import vitpur
from app.services.memory_repository import InMemoryRepository
from detection_fixtures import build_history

IST = timezone(timedelta(hours=5, minutes=30))


def _sensor(code: str = "SNS-VLV-01-FLW"):
    return next(s for s in vitpur.build_sensors() if s.sensor_code == code)


def _daily_series(sensor, days: int = 3, step_minutes: int = 5):
    """A pure square-wave day: 40 lpm by day, 10 lpm by night."""
    end = datetime(2026, 6, 1, tzinfo=IST)
    start = end - timedelta(days=days)
    readings = []
    ts = start
    while ts < end:
        hour = ts.astimezone(IST).hour
        value = 40.0 if 6 <= hour < 18 else 10.0
        readings.append(SensorReading(sensor_id=sensor.id, ts=ts, value=value))
        ts += timedelta(minutes=step_minutes)
    return readings


def test_baseline_follows_the_time_of_day_not_the_daily_mean() -> None:
    sensor = _sensor()
    baseline = build_sensor_baseline(sensor, _daily_series(sensor))

    noon = datetime(2026, 6, 2, 12, tzinfo=IST)
    midnight = datetime(2026, 6, 2, 2, tzinfo=IST)

    assert baseline.stats_at(noon)[0].median == pytest.approx(40.0)
    assert baseline.stats_at(midnight)[0].median == pytest.approx(10.0)

    # 10 lpm at 02:00 is healthy; the same 10 lpm at noon is not. A global mean
    # (25 lpm) would have called both of them equally odd.
    assert abs(baseline.robust_z(10.0, midnight)[0]) < 1.0
    assert abs(baseline.robust_z(10.0, noon)[0]) > 5.0


def test_spread_floor_keeps_a_quiet_channel_from_exploding() -> None:
    """A perfectly constant channel has MAD 0; without a floor, z is infinite."""
    sensor = _sensor()
    flat = [
        SensorReading(
            sensor_id=sensor.id,
            ts=datetime(2026, 6, 1, tzinfo=IST) + timedelta(minutes=5 * i),
            value=20.0,
        )
        for i in range(200)
    ]
    baseline = build_sensor_baseline(sensor, flat)
    ts = datetime(2026, 6, 1, 3, tzinfo=IST)

    z, median, _ = baseline.robust_z(20.05, ts)
    assert median == pytest.approx(20.0)
    assert abs(z) < 100.0  # finite, and not a false alarm on rounding noise


def test_bad_quality_readings_are_not_learned_from() -> None:
    sensor = _sensor()
    readings = _daily_series(sensor)
    readings.extend(
        SensorReading(
            sensor_id=sensor.id,
            ts=readings[-1].ts + timedelta(minutes=5 * i),
            value=9999.0,
            quality_flag=QualityFlag.FLATLINE,
        )
        for i in range(1, 30)
    )
    baseline = build_sensor_baseline(sensor, readings)

    assert baseline.global_stats.median < 100.0


def test_minutes_of_day_uses_local_time() -> None:
    ts = datetime(2026, 6, 1, 0, 30, tzinfo=timezone.utc)  # 06:00 IST
    assert minutes_of_day(ts) == 360


@pytest.mark.asyncio
async def test_store_excludes_the_newest_slice_from_learning(
    repository: InMemoryRepository, settings
) -> None:
    """A fault developing now must not be absorbed into "normal"."""
    now = await build_history(repository)
    store = BaselineStore(
        repository,
        baseline_hours=settings.detection_baseline_hours,
        exclude_recent_minutes=settings.detection_baseline_exclude_recent_minutes,
    )
    await store.refresh(repository.sensors, now=now)

    cutoff = now - timedelta(minutes=settings.detection_baseline_exclude_recent_minutes)
    for baseline in store.baselines.values():
        if baseline.window_end is not None:
            assert baseline.window_end <= cutoff


@pytest.mark.asyncio
async def test_monotonic_counters_get_no_level_baseline(
    repository: InMemoryRepository, settings
) -> None:
    now = await build_history(repository)
    store = BaselineStore(repository)
    await store.refresh(repository.sensors, now=now)

    run_hours = next(
        s for s in repository.sensors if s.sensor_type is SensorType.RUN_HOURS
    )
    assert SensorType.RUN_HOURS in SKIP_BASELINE_TYPES
    assert store.get(run_hours.id) is None
