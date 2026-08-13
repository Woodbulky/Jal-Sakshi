"""Whether an instrument may be believed, before its reading is acted on."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.analytics.baseline import build_sensor_baseline
from app.analytics.sensor_health import assess_sensor
from app.schemas.detection import SensorIssue
from app.schemas.network import QualityFlag, SensorReading, SensorStatus, SensorType
from app.seed import vitpur

NOW = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)


def _sensor(code: str):
    return next(s for s in vitpur.build_sensors() if s.sensor_code == code)


def _series(sensor, values: list[float], *, step_minutes: int = 5):
    start = NOW - timedelta(minutes=step_minutes * (len(values) - 1))
    return [
        SensorReading(
            sensor_id=sensor.id,
            ts=start + timedelta(minutes=step_minutes * i),
            value=value,
        )
        for i, value in enumerate(values)
    ]


def _varying_baseline(sensor):
    """A channel that normally moves, so a flat run is genuinely suspicious."""
    readings = _series(sensor, [20.0 + (i % 7) for i in range(200)])
    return build_sensor_baseline(sensor, readings)


def test_a_healthy_instrument_is_trusted() -> None:
    sensor = _sensor("SNS-VLV-01-FLW")
    health = assess_sensor(sensor, _series(sensor, [22.0, 23.5, 21.8]), now=NOW)

    assert health.trusted
    assert health.status is SensorStatus.ACTIVE
    assert health.issues == []


def test_silence_beyond_a_few_intervals_is_stale() -> None:
    sensor = _sensor("SNS-VLV-01-FLW")  # 300s interval
    readings = _series(sensor, [22.0, 22.4])
    late = NOW + timedelta(minutes=30)

    health = assess_sensor(sensor, readings, now=late)

    assert SensorIssue.STALE in health.issues
    assert not health.trusted
    assert health.status is SensorStatus.FAILED


def test_a_flatlined_channel_that_normally_moves_is_not_trusted() -> None:
    sensor = _sensor("SNS-VLV-01-FLW")
    health = assess_sensor(
        sensor,
        _series(sensor, [21.0] * 8),
        now=NOW,
        baseline=_varying_baseline(sensor),
    )

    assert SensorIssue.FLATLINE in health.issues
    assert not health.trusted


def test_a_genuinely_constant_channel_is_left_alone() -> None:
    """Overnight a meter can read the same value for an hour. That is not a fault."""
    sensor = _sensor("SNS-VLV-01-FLW")
    constant = build_sensor_baseline(sensor, _series(sensor, [21.0] * 200))

    health = assess_sensor(
        sensor, _series(sensor, [21.0] * 8), now=NOW, baseline=constant
    )

    assert SensorIssue.FLATLINE not in health.issues
    assert health.trusted


def test_out_of_range_is_caught_without_any_history() -> None:
    sensor = _sensor("SNS-OHT-01-PH")  # configured 5.5 - 9.5
    health = assess_sensor(sensor, _series(sensor, [7.3, 7.3, 21.0]), now=NOW)

    assert SensorIssue.OUT_OF_RANGE in health.issues
    assert not health.trusted


def test_a_run_hour_counter_is_exempt_from_the_range_test() -> None:
    """The odometer passes its configured per-day range within two days."""
    sensor = _sensor("SNS-PMP-01-RNH")
    assert sensor.sensor_type is SensorType.RUN_HOURS

    health = assess_sensor(
        sensor, _series(sensor, [40.1, 40.2, 40.3]), now=NOW, monotonic=True
    )

    assert health.trusted
    assert health.issues == []


def test_a_declared_bad_quality_flag_is_believed() -> None:
    sensor = _sensor("SNS-ZONE-A-PRT")
    readings = _series(sensor, [1.4, 1.4, 1.4])
    readings[-1] = readings[-1].model_copy(
        update={"value": None, "quality_flag": QualityFlag.MISSING}
    )

    health = assess_sensor(sensor, readings, now=NOW)

    assert SensorIssue.MISSING in health.issues
    assert not health.trusted
