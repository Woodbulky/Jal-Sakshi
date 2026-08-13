"""Is the instrument to be trusted before its reading is believed?

Guardrail 1 of the agent contract. A flatlined pressure transmitter reads a
perfect zero and looks exactly like a catastrophic outage; dispatching a crew
for it wastes the one van the village has. So every reading is judged twice:
once for whether the *sensor* is healthy, and only then for whether the
*network* is.

Four failure modes are checked, in the order they mislead most:

STALE          nothing has arrived for several sampling intervals
MISSING        the reading exists but carries no value
FLATLINE       bit-identical values on a channel that normally moves
OUT_OF_RANGE   outside the instrument's own configured range

A sensor that fails any of these is marked untrusted. Its anomalies are still
recorded — suppressing them would hide the sensor failure too — but they are
excluded from the network diagnosis and reported as a SENSOR_FAULT instead.
"""

from __future__ import annotations

from datetime import datetime

from app.analytics.baseline import SensorBaseline
from app.schemas.detection import SensorHealth, SensorIssue
from app.schemas.network import QualityFlag, Sensor, SensorReading, SensorStatus

#: Quality flags the sensor itself already declared bad.
_FLAG_ISSUES: dict[QualityFlag, SensorIssue] = {
    QualityFlag.MISSING: SensorIssue.MISSING,
    QualityFlag.STALE: SensorIssue.STALE,
    QualityFlag.FLATLINE: SensorIssue.FLATLINE,
    QualityFlag.OUT_OF_RANGE: SensorIssue.OUT_OF_RANGE,
}

#: Issues severe enough that the instrument is treated as failed, not degraded.
_FAILING = frozenset(
    {SensorIssue.STALE, SensorIssue.MISSING, SensorIssue.FLATLINE, SensorIssue.OUT_OF_RANGE}
)


def _is_flat(values: list[float], *, points: int, tolerance: float) -> bool:
    if len(values) < points:
        return False
    recent = values[-points:]
    return max(recent) - min(recent) <= tolerance


def assess_sensor(
    sensor: Sensor,
    readings: list[SensorReading],
    *,
    now: datetime,
    baseline: SensorBaseline | None = None,
    stale_multiplier: float = 3.0,
    flatline_points: int = 6,
    monotonic: bool = False,
) -> SensorHealth:
    """Judge one instrument from its recent readings.

    `monotonic` marks a counter such as run-hours: holding steady is how it
    reports a stopped pump, so a flat run of values is information, not a fault.
    """
    issues: list[SensorIssue] = []
    note: str | None = None

    latest = readings[-1] if readings else None
    seconds_since = (
        (now - latest.ts).total_seconds() if latest is not None else None
    )

    if latest is None:
        issues.append(SensorIssue.STALE)
        note = "no readings in the detection window"
    else:
        if latest.quality_flag in _FLAG_ISSUES:
            issues.append(_FLAG_ISSUES[latest.quality_flag])
        if latest.value is None and SensorIssue.MISSING not in issues:
            issues.append(SensorIssue.MISSING)

        allowance = max(sensor.sampling_interval_seconds, 1) * stale_multiplier
        if seconds_since is not None and seconds_since > allowance:
            if SensorIssue.STALE not in issues:
                issues.append(SensorIssue.STALE)
            note = (
                f"silent for {seconds_since:.0f}s "
                f"(interval {sensor.sampling_interval_seconds}s)"
            )

        # A counter walks past its configured per-day range by design, so the
        # range test is meaningless for one.
        if latest.value is not None and not monotonic:
            below = sensor.expected_min is not None and latest.value < sensor.expected_min
            above = sensor.expected_max is not None and latest.value > sensor.expected_max
            if (below or above) and SensorIssue.OUT_OF_RANGE not in issues:
                issues.append(SensorIssue.OUT_OF_RANGE)
                note = (
                    f"{latest.value:g} outside "
                    f"[{sensor.expected_min:g}, {sensor.expected_max:g}]"
                    if sensor.expected_min is not None and sensor.expected_max is not None
                    else "outside configured range"
                )

    # Flatline needs a baseline: a channel that is genuinely constant overnight
    # must not be condemned for being constant.
    values = [float(r.value) for r in readings if r.value is not None]
    if not monotonic and baseline is not None and SensorIssue.FLATLINE not in issues:
        moves_normally = (
            baseline.global_stats is not None
            and baseline.global_stats.mad > baseline.spread_floor
        )
        if moves_normally and _is_flat(
            values, points=flatline_points, tolerance=baseline.spread_floor * 0.05
        ):
            issues.append(SensorIssue.FLATLINE)
            note = f"{flatline_points} identical readings on a channel that normally varies"

    if baseline is not None and not baseline.buckets and baseline.global_stats is None:
        issues.append(SensorIssue.NO_BASELINE)
        note = note or "no history to compare against"

    hard_issues = [issue for issue in issues if issue in _FAILING]
    if hard_issues:
        status = SensorStatus.FAILED
    elif issues:
        status = SensorStatus.DEGRADED
    else:
        status = SensorStatus.ACTIVE

    return SensorHealth(
        sensor_id=sensor.id,
        sensor_code=sensor.sensor_code,
        asset_id=sensor.asset_id,
        status=status,
        trusted=not hard_issues,
        issues=issues,
        last_value=latest.value if latest else None,
        last_seen_at=latest.ts if latest else None,
        seconds_since_last_reading=seconds_since,
        quality_flag=latest.quality_flag if latest else QualityFlag.MISSING,
        note=note,
    )


__all__ = ["assess_sensor"]
