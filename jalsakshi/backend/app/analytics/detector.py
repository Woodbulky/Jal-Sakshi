"""Which channels are currently off their own day-shape.

Two independent tests, because they fail in different situations:

ROBUST_Z   the reading against the median and MAD for this time of day. Catches
           anything that has a history to compare against.
RANGE      the reading against the instrument's configured expected range.
           Catches the first hours of a deployment, before there is a baseline,
           and physically impossible values that happen to be consistent.

An anomaly is a fact about one channel. It is not a diagnosis: several
anomalies, read together with the topology, are what `signatures.py` turns into
a fault. Anomalies from untrusted instruments are still recorded — suppressing
them would hide the instrument failure as well — but they carry
`details.sensor_trusted = false` so the classifier can hold them at arm's
length.
"""

from __future__ import annotations

from app.analytics.baseline import SKIP_BASELINE_TYPES
from app.analytics.features import Channel, NetworkFeatures
from app.schemas.detection import Anomaly, AnomalyMethod, SensorHealth, SensorIssue
from app.schemas.network import Sensor

#: |z| above this is off the day shape.
DEFAULT_Z_THRESHOLD = 3.5
#: |z| at which severity saturates at 1.0.
_SEVERITY_CEILING_Z = 12.0


def _severity(z: float) -> float:
    return max(0.0, min(1.0, abs(z) / _SEVERITY_CEILING_Z))


def _metric(channel: Channel) -> str:
    return channel.sensor_type.value.lower()


def detect_anomalies(
    features: NetworkFeatures,
    *,
    sensors_by_id: dict[str, Sensor],
    health_by_id: dict[str, SensorHealth],
    z_threshold: float = DEFAULT_Z_THRESHOLD,
) -> list[Anomaly]:
    """Score every channel in the window and return those that stand out."""
    anomalies: list[Anomaly] = []

    for channel in features.channels.values():
        if channel.value is None:
            continue
        health = health_by_id.get(channel.sensor_id)
        trusted = health.trusted if health else True

        if channel.z is not None and abs(channel.z) >= z_threshold:
            anomalies.append(
                _anomaly(
                    features,
                    channel,
                    method=AnomalyMethod.ROBUST_Z,
                    trusted=trusted,
                    severity=_severity(channel.z),
                    detail={
                        "direction": "HIGH" if channel.z > 0 else "LOW",
                        "weak_baseline": channel.weak_baseline,
                        "ratio": round(channel.ratio, 4)
                        if channel.ratio is not None
                        else None,
                        "points_in_window": channel.points,
                    },
                )
            )
            continue

        sensor = sensors_by_id.get(channel.sensor_id)
        # A run-hour odometer passes its configured per-day range within two
        # days of running; range-testing a counter is meaningless.
        if sensor is None or sensor.sensor_type in SKIP_BASELINE_TYPES:
            continue
        below = sensor.expected_min is not None and channel.value < sensor.expected_min
        above = sensor.expected_max is not None and channel.value > sensor.expected_max
        if below or above:
            bound = sensor.expected_min if below else sensor.expected_max
            residual = channel.value - float(bound)  # type: ignore[arg-type]
            anomalies.append(
                _anomaly(
                    features,
                    channel,
                    method=AnomalyMethod.RANGE,
                    trusted=trusted,
                    severity=0.6,
                    residual=residual,
                    baseline=float(bound),  # type: ignore[arg-type]
                    detail={
                        "direction": "LOW" if below else "HIGH",
                        "expected_min": sensor.expected_min,
                        "expected_max": sensor.expected_max,
                    },
                )
            )

    # An instrument that failed its health check is itself worth recording,
    # even when its (held or absent) value scores no z at all.
    for health in health_by_id.values():
        if health.trusted or not health.issues:
            continue
        if health.issues == [SensorIssue.NO_BASELINE]:
            continue
        anomalies.append(
            Anomaly(
                service_area_id=features.service_area_id,
                asset_id=health.asset_id,
                sensor_id=health.sensor_id,
                sensor_code=health.sensor_code,
                detected_at=features.ts,
                window_start=features.window_start,
                window_end=features.window_end,
                method=AnomalyMethod.SENSOR_HEALTH,
                metric="sensor_health",
                observed_value=health.last_value,
                severity=0.5,
                details={
                    "issues": [issue.value for issue in health.issues],
                    "status": health.status.value,
                    "note": health.note,
                    "sensor_trusted": False,
                },
            )
        )

    anomalies.sort(key=lambda anomaly: anomaly.severity, reverse=True)
    return anomalies


def _anomaly(
    features: NetworkFeatures,
    channel: Channel,
    *,
    method: AnomalyMethod,
    trusted: bool,
    severity: float,
    residual: float | None = None,
    baseline: float | None = None,
    detail: dict | None = None,
) -> Anomaly:
    base = baseline if baseline is not None else channel.baseline
    if residual is None and base is not None and channel.value is not None:
        residual = channel.value - base
    details = dict(detail or {})
    details["sensor_trusted"] = trusted
    details["asset_code"] = channel.asset_code
    return Anomaly(
        service_area_id=features.service_area_id,
        asset_id=channel.asset_id,
        sensor_id=channel.sensor_id,
        sensor_code=channel.sensor_code,
        detected_at=features.ts,
        window_start=features.window_start,
        window_end=features.window_end,
        method=method,
        metric=_metric(channel),
        observed_value=channel.value,
        baseline_value=base,
        residual=round(residual, 6) if residual is not None else None,
        z_score=round(channel.z, 4) if channel.z is not None else None,
        severity=round(severity, 4),
        details=details,
    )


def anomaly_key(anomaly: Anomaly) -> tuple[str, str, str]:
    """Identity for de-duplication: one open anomaly per channel and test."""
    return (anomaly.sensor_id or "", anomaly.metric, anomaly.method.value)


__all__ = ["DEFAULT_Z_THRESHOLD", "anomaly_key", "detect_anomalies"]
