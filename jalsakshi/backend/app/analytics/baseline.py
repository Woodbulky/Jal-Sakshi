"""What each sensor normally reads at this time of day.

Rural water demand is strongly diurnal: 40 lpm at the morning peak and 12 lpm at
03:00 are both perfectly healthy. A single global mean would call every morning
an anomaly and miss a genuine collapse at night. So the baseline is a *day
shape*: the readings are bucketed by local time of day and each bucket keeps a
median and a MAD.

Median and MAD rather than mean and standard deviation because the history the
baseline learns from is not guaranteed clean. A few faulted samples pull a mean
badly; they barely move a median.

Two rules keep the baseline honest:

* the newest ``exclude_recent_minutes`` are never learned from, so a fault
  developing right now cannot quietly redefine "normal";
* a monotonic counter (``RUN_HOURS``) has no meaningful level baseline and is
  skipped here. Its *rate* is a classifier feature instead — see `features.py`.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.schemas.detection import BaselineBand, SensorBaselineProfile
from app.schemas.network import QualityFlag, Sensor, SensorReading, SensorType
from app.services.repository import Repository

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

#: 0.6745 = Phi^-1(0.75); it rescales a MAD to a standard-deviation equivalent.
_MAD_TO_SIGMA = 0.6745

#: Sensor types with no meaningful level baseline.
SKIP_BASELINE_TYPES: frozenset[SensorType] = frozenset({SensorType.RUN_HOURS})

_USABLE_FLAGS = frozenset({QualityFlag.GOOD, QualityFlag.SUSPECT})


def minutes_of_day(ts: datetime) -> int:
    local = ts.astimezone(IST)
    return local.hour * 60 + local.minute


@dataclass(frozen=True)
class BucketStats:
    median: float
    mad: float
    count: int


@dataclass
class SensorBaseline:
    """The learned day-shape of one sensor."""

    sensor_id: str
    sensor_code: str
    bucket_minutes: int
    buckets: dict[int, BucketStats] = field(default_factory=dict)
    global_stats: BucketStats | None = None
    #: Smallest spread treated as real; below it, noise would explode the z.
    spread_floor: float = 1e-6
    learned_from: int = 0
    window_start: datetime | None = None
    window_end: datetime | None = None

    def bucket_index(self, ts: datetime) -> int:
        return minutes_of_day(ts) // self.bucket_minutes

    def stats_at(self, ts: datetime) -> tuple[BucketStats | None, bool]:
        """Return (stats, weak). `weak` means we fell back off the day shape."""
        stats = self.buckets.get(self.bucket_index(ts))
        if stats is not None:
            return stats, False
        return self.global_stats, True

    def robust_z(self, value: float, ts: datetime) -> tuple[float, float, bool] | None:
        """(z, baseline, weak) for `value` at `ts`, or None with no baseline."""
        stats, weak = self.stats_at(ts)
        if stats is None:
            return None
        spread = max(stats.mad, self.spread_floor)
        z = _MAD_TO_SIGMA * (value - stats.median) / spread
        return z, stats.median, weak

    def band(self, ts: datetime, *, z: float) -> BaselineBand:
        """The shaded band the console draws around a live series."""
        stats, weak = self.stats_at(ts)
        if stats is None:
            return BaselineBand(
                sensor_id=self.sensor_id, sensor_code=self.sensor_code, ts=ts, weak=True
            )
        half = z * max(stats.mad, self.spread_floor) / _MAD_TO_SIGMA
        return BaselineBand(
            sensor_id=self.sensor_id,
            sensor_code=self.sensor_code,
            ts=ts,
            baseline=stats.median,
            lower=stats.median - half,
            upper=stats.median + half,
            sample_count=stats.count,
            weak=weak,
        )

    def to_profile(self) -> SensorBaselineProfile:
        return SensorBaselineProfile(
            sensor_id=self.sensor_id,
            sensor_code=self.sensor_code,
            bucket_minutes=self.bucket_minutes,
            learned_from=self.learned_from,
            window_start=self.window_start,
            window_end=self.window_end,
            buckets=[
                {
                    "minute_of_day": float(index * self.bucket_minutes),
                    "median": stats.median,
                    "spread": max(stats.mad, self.spread_floor),
                    "count": float(stats.count),
                }
                for index, stats in sorted(self.buckets.items())
            ],
        )


def _mad(values: list[float], median: float) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.median([abs(v - median) for v in values])


def _spread_floor(sensor: Sensor, samples: list[float]) -> float:
    """A floor under the MAD, so a quiet channel does not produce infinite z.

    Overnight a flow meter can read the same value for an hour; its MAD is then
    zero and any daytime value would score infinitely anomalous. The floor is
    taken from the instrument's own configured range and from the level it
    actually sits at — whichever is *smaller*, because a floor exists only to
    stop a division by zero. Too generous a floor would mask real deviations on
    a channel whose configured range dwarfs its working point (a 0-600 lpm
    meter that spends its life around 25 lpm).
    """
    candidates: list[float] = []
    if sensor.expected_min is not None and sensor.expected_max is not None:
        span = sensor.expected_max - sensor.expected_min
        if span > 0:
            candidates.append(span * 0.004)
    if samples:
        level = abs(statistics.median(samples))
        if level > 0:
            candidates.append(level * 0.02)
    return min(candidates) if candidates else 1e-6


def build_sensor_baseline(
    sensor: Sensor,
    readings: list[SensorReading],
    *,
    bucket_minutes: int = 30,
    min_bucket_samples: int = 6,
) -> SensorBaseline:
    """Learn one sensor's day shape from `readings` (already time-filtered)."""
    baseline = SensorBaseline(
        sensor_id=sensor.id,
        sensor_code=sensor.sensor_code,
        bucket_minutes=bucket_minutes,
    )
    usable = [
        r
        for r in readings
        if r.value is not None and r.quality_flag in _USABLE_FLAGS
    ]
    if not usable:
        return baseline

    values = [float(r.value) for r in usable]  # type: ignore[arg-type]
    baseline.learned_from = len(usable)
    baseline.window_start = min(r.ts for r in usable)
    baseline.window_end = max(r.ts for r in usable)
    baseline.spread_floor = _spread_floor(sensor, values)

    global_median = statistics.median(values)
    baseline.global_stats = BucketStats(
        median=global_median, mad=_mad(values, global_median), count=len(values)
    )

    bucket_count = max(1, (24 * 60) // bucket_minutes)
    by_bucket: dict[int, list[float]] = {}
    for reading in usable:
        index = minutes_of_day(reading.ts) // bucket_minutes
        by_bucket.setdefault(index, []).append(float(reading.value))  # type: ignore[arg-type]

    # A bucket borrows from its neighbours until it has enough samples. Demand
    # varies smoothly, so ±30 minutes is still the same part of the day.
    for index in range(bucket_count):
        samples: list[float] = []
        for reach in range(0, 4):
            samples = []
            for offset in range(-reach, reach + 1):
                samples.extend(by_bucket.get((index + offset) % bucket_count, []))
            if len(samples) >= min_bucket_samples:
                break
        if len(samples) < min_bucket_samples:
            continue  # stats_at() falls back to global and flags it weak
        median = statistics.median(samples)
        baseline.buckets[index] = BucketStats(
            median=median, mad=_mad(samples, median), count=len(samples)
        )
    return baseline


class BaselineStore:
    """Caches the learned day-shapes and refreshes them on a timer.

    The history query is the expensive one — tens of thousands of rows — and the
    day shape barely moves between ticks, so recomputing it every ten seconds
    would be waste. Everything the detector does per tick reads only the last
    few minutes.
    """

    def __init__(
        self,
        repository: Repository,
        *,
        baseline_hours: int = 48,
        refresh_seconds: float = 900.0,
        exclude_recent_minutes: float = 45.0,
        bucket_minutes: int = 30,
        min_bucket_samples: int = 6,
    ) -> None:
        self._repository = repository
        self.baseline_hours = baseline_hours
        self.refresh_seconds = refresh_seconds
        self.exclude_recent_minutes = exclude_recent_minutes
        self.bucket_minutes = bucket_minutes
        self.min_bucket_samples = min_bucket_samples

        self._baselines: dict[str, SensorBaseline] = {}
        self.refreshed_at: datetime | None = None

    @property
    def baselines(self) -> dict[str, SensorBaseline]:
        return self._baselines

    def get(self, sensor_id: str) -> SensorBaseline | None:
        return self._baselines.get(sensor_id)

    def invalidate(self) -> None:
        """Force a relearn on the next pass.

        Called when history is rewritten underneath us — a backfill changes what
        "normal" means, and serving a day-shape learned from the old data would
        report the new history as one long anomaly.
        """
        self.refreshed_at = None

    def is_stale(self, now: datetime) -> bool:
        if self.refreshed_at is None:
            return True
        return (now - self.refreshed_at).total_seconds() >= self.refresh_seconds

    async def ensure(
        self, sensors: list[Sensor], *, now: datetime, force: bool = False
    ) -> bool:
        """Refresh if the cache has expired. Returns True if it did."""
        if not force and not self.is_stale(now):
            return False
        await self.refresh(sensors, now=now)
        return True

    async def refresh(self, sensors: list[Sensor], *, now: datetime) -> None:
        learnable = [s for s in sensors if s.sensor_type not in SKIP_BASELINE_TYPES]
        if not learnable:
            self._baselines = {}
            self.refreshed_at = now
            return

        end = now - timedelta(minutes=self.exclude_recent_minutes)
        start = end - timedelta(hours=self.baseline_hours)
        sensor_ids = [s.id for s in learnable]
        # Generous cap: 48h of 5-minute points is ~576 rows per sensor.
        readings = await self._repository.list_readings(
            sensor_ids, start=start, end=end, limit=len(sensor_ids) * 1200
        )

        by_sensor: dict[str, list[SensorReading]] = {sid: [] for sid in sensor_ids}
        for reading in readings:
            by_sensor.setdefault(reading.sensor_id, []).append(reading)

        self._baselines = {
            sensor.id: build_sensor_baseline(
                sensor,
                by_sensor.get(sensor.id, []),
                bucket_minutes=self.bucket_minutes,
                min_bucket_samples=self.min_bucket_samples,
            )
            for sensor in learnable
        }
        self.refreshed_at = now
        logger.info(
            "baseline refreshed: %s sensors, %s readings over %sh ending %s",
            len(self._baselines),
            len(readings),
            self.baseline_hours,
            end.isoformat(),
        )


__all__ = [
    "BaselineStore",
    "BucketStats",
    "SensorBaseline",
    "SKIP_BASELINE_TYPES",
    "build_sensor_baseline",
    "minutes_of_day",
]
