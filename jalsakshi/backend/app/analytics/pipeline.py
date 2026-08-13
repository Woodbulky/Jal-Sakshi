"""One pass of detection, end to end.

    sensor health -> baseline -> anomalies -> features -> classification -> event

Ordering matters. Health comes first because an untrusted instrument must not
be allowed to invent a network fault, and the baseline comes before the
anomalies because "abnormal" is meaningless without a definition of normal.

The pass is cheap enough to run after every simulator tick: the day-shape is
cached and refreshed on a timer, so a tick reads only the last few minutes of
telemetry.

What this service will *not* do:

* close anything. Detection may observe that telemetry has recovered and move a
  fault event to RESTORING; only verification may resolve it.
* read `fault_injections`. The classifier earns its answer from telemetry.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.analytics.baseline import BaselineStore, SKIP_BASELINE_TYPES
from app.analytics.detector import anomaly_key, detect_anomalies
from app.analytics.features import NetworkFeatures, build_features
from app.analytics.lightgbm_adapter import LightGBMAdapter
from app.analytics.sensor_health import assess_sensor
from app.analytics.signatures import CLASSIFIER_VERSION, classify
from app.core.config import Settings
from app.schemas.detection import (
    Anomaly,
    BaselineBand,
    Classification,
    DetectionRun,
    FaultEvent,
    SensorBaselineProfile,
    SensorHealth,
)
from app.schemas.network import SensorType
from app.schemas.simulation import FaultType
from app.services.repository import Repository

logger = logging.getLogger(__name__)

#: Statuses a fault event moves through while detection still owns it.
STATUS_OPEN = "OPEN"
STATUS_RESTORING = "RESTORING"
#: Terminal, and only verification writes it: an incident is resolved when the
#: sensors say so, never because a work order was ticked off.
STATUS_RESOLVED = "RESOLVED"


class DetectionError(RuntimeError):
    """Raised when detection is asked to run somewhere it cannot."""


class DetectionService:
    def __init__(
        self,
        repository: Repository,
        settings: Settings,
        *,
        service_area_ref: str | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._service_area_ref = service_area_ref or settings.demo_service_area_id
        self._lock = asyncio.Lock()
        self._loaded = False

        self.baselines = BaselineStore(
            repository,
            baseline_hours=settings.detection_baseline_hours,
            refresh_seconds=settings.detection_baseline_refresh_seconds,
            exclude_recent_minutes=settings.detection_baseline_exclude_recent_minutes,
            bucket_minutes=settings.detection_bucket_minutes,
            min_bucket_samples=settings.detection_min_bucket_samples,
        )
        self.booster = LightGBMAdapter(
            settings.lightgbm_model_path, blend_weight=settings.lightgbm_blend_weight
        )

        self._area = None
        self._assets: list = []
        self._connections: list = []
        self._sensors: list = []
        self.last_run: DetectionRun | None = None

    # -- wiring ------------------------------------------------------------
    async def load(self, *, force: bool = False) -> None:
        if self._loaded and not force:
            return
        area = await self._repository.get_service_area(self._service_area_ref)
        if area is None:
            raise DetectionError(
                f"Service area '{self._service_area_ref}' not found. "
                "Apply the seed migration before running detection."
            )
        self._area = area
        self._assets = await self._repository.list_assets(area.id)
        self._connections = await self._repository.list_connections(area.id)
        self._sensors = await self._repository.list_sensors(service_area_id=area.id)
        if not self._sensors:
            raise DetectionError(f"Service area '{area.code}' has no sensors.")
        self._loaded = True

    @property
    def service_area_id(self) -> str:
        return self._area.id if self._area else ""

    @property
    def total_households(self) -> int:
        if self._area and self._area.households:
            return self._area.households
        return sum(asset.households_served for asset in self._assets)

    # -- reporting helpers -------------------------------------------------
    async def sensor_health(self, *, now: datetime | None = None) -> list[SensorHealth]:
        await self.load()
        now = now or datetime.now(timezone.utc)
        await self.baselines.ensure(self._sensors, now=now)
        readings = await self._recent_readings(now)
        return self._assess_all(readings, now)

    async def features(
        self, *, now: datetime | None = None, window_minutes: float | None = None
    ) -> NetworkFeatures:
        """The hydraulic picture at `now`, without scoring or persisting it.

        Verification needs the same channels the classifier reasons over, but
        must not open incidents while looking.
        """
        await self.load()
        now = now or datetime.now(timezone.utc)
        await self.baselines.ensure(self._sensors, now=now)
        readings = await self._recent_readings(now)
        health = self._assess_all(readings, now)
        window = window_minutes or self._settings.detection_window_minutes
        return build_features(
            service_area_id=self.service_area_id,
            assets=self._assets,
            connections=self._connections,
            sensors=self._sensors,
            readings_by_sensor=readings,
            baselines=self.baselines.baselines,
            untrusted_sensor_ids={i.sensor_id for i in health if not i.trusted},
            now=now,
            window_start=now - timedelta(minutes=window),
        )

    async def baseline_profile(self, sensor_ref: str) -> SensorBaselineProfile | None:
        """The learned day-shape of one sensor — what the console overlays."""
        await self.load()
        sensor = next(
            (
                s
                for s in self._sensors
                if sensor_ref in (s.id, s.sensor_code)
            ),
            None,
        )
        if sensor is None:
            return None
        now = datetime.now(timezone.utc)
        await self.baselines.ensure(self._sensors, now=now)
        baseline = self.baselines.get(sensor.id)
        return baseline.to_profile() if baseline else None

    async def baseline_band(self, sensor_ref: str, ts: datetime) -> BaselineBand | None:
        await self.load()
        sensor = next(
            (s for s in self._sensors if sensor_ref in (s.id, s.sensor_code)), None
        )
        if sensor is None:
            return None
        await self.baselines.ensure(self._sensors, now=datetime.now(timezone.utc))
        baseline = self.baselines.get(sensor.id)
        if baseline is None:
            return None
        return baseline.band(ts, z=self._settings.detection_z_threshold)

    # -- the pass ----------------------------------------------------------
    def invalidate_baseline(self) -> None:
        """Relearn the day-shape on the next pass (after a backfill rewrites it)."""
        self.baselines.invalidate()

    async def run(
        self,
        *,
        now: datetime | None = None,
        persist: bool = True,
        refresh_baseline: bool = False,
    ) -> DetectionRun:
        """Score the current window and, unless asked not to, record the result."""
        await self.load()
        now = now or datetime.now(timezone.utc)

        async with self._lock:
            refreshed = await self.baselines.ensure(
                self._sensors, now=now, force=refresh_baseline
            )
            window_start = now - timedelta(
                minutes=self._settings.detection_window_minutes
            )
            readings = await self._recent_readings(now)
            health = self._assess_all(readings, now)
            health_by_id = {item.sensor_id: item for item in health}
            untrusted = {
                item.sensor_id for item in health if not item.trusted
            }

            features = build_features(
                service_area_id=self.service_area_id,
                assets=self._assets,
                connections=self._connections,
                sensors=self._sensors,
                readings_by_sensor=readings,
                baselines=self.baselines.baselines,
                untrusted_sensor_ids=untrusted,
                now=now,
                window_start=window_start,
            )
            anomalies = detect_anomalies(
                features,
                sensors_by_id={sensor.id: sensor for sensor in self._sensors},
                health_by_id=health_by_id,
                z_threshold=self._settings.detection_z_threshold,
            )

            classification: Classification | None = None
            if anomalies:
                classification = classify(
                    features,
                    sensor_health=health,
                    total_households=self.total_households,
                    min_confidence=self._settings.detection_min_confidence,
                    classifier_version=CLASSIFIER_VERSION,
                    booster=self.booster,
                )

            run = DetectionRun(
                service_area_id=self.service_area_id,
                service_area_code=self._area.code if self._area else "",
                ran_at=now,
                window_start=window_start,
                window_end=now,
                sensors_checked=len(self._sensors),
                untrusted_sensors=[
                    item.sensor_code for item in health if not item.trusted
                ],
                sensor_health=health,
                anomalies=anomalies,
                classification=classification,
                baseline_refreshed=refreshed,
            )

            if persist:
                run.fault_event = await self._persist(run, now=now)
            elif not anomalies:
                run.note = "no anomalies; network reads normal for this time of day"

            self.last_run = run
            return run

    # -- persistence -------------------------------------------------------
    async def _persist(self, run: DetectionRun, *, now: datetime) -> FaultEvent | None:
        open_events = await self._repository.list_fault_events(
            service_area_id=self.service_area_id, status=STATUS_OPEN, limit=5
        )
        restoring = await self._repository.list_fault_events(
            service_area_id=self.service_area_id, status=STATUS_RESTORING, limit=5
        )
        current = (open_events or restoring or [None])[0]

        if not run.anomalies:
            run.note = "no anomalies; network reads normal for this time of day"
            if current is not None and current.status == STATUS_OPEN:
                # Telemetry has recovered. That is evidence for verification to
                # weigh, not authority to resolve anything.
                return await self._repository.update_fault_event(
                    current.id,
                    status=STATUS_RESTORING,
                    evidence={
                        **current.evidence,
                        "restoration_observed_at": now.isoformat(),
                    },
                )
            return current

        classification = run.classification
        event = current
        if event is None:
            event = await self._repository.create_fault_event(
                FaultEvent(
                    id="",
                    service_area_id=self.service_area_id,
                    asset_id=classification.asset_id if classification else None,
                    fault_type=classification.fault_type
                    if classification
                    else FaultType.UNKNOWN,
                    confidence=classification.confidence if classification else 0.0,
                    detected_at=now,
                    severity_score=classification.severity_score if classification else 0.0,
                    households_affected=classification.households_affected
                    if classification
                    else 0,
                    evidence=self._event_evidence(run, classification),
                    status=STATUS_OPEN,
                    classifier_version=classification.classifier_version
                    if classification
                    else None,
                )
            )
            logger.info(
                "fault event %s opened: %s (confidence %.2f)",
                event.id,
                event.fault_type.value,
                event.confidence,
            )
        else:
            updates: dict = {
                "evidence": self._event_evidence(run, classification, previous=event),
                "status": STATUS_OPEN,
            }
            # Re-classify only on strictly better evidence; a confident answer
            # must not be displaced by a marginal one on the next tick.
            if classification is not None and (
                classification.confidence > event.confidence
                or classification.fault_type is event.fault_type
            ):
                updates.update(
                    fault_type=classification.fault_type.value,
                    confidence=classification.confidence,
                    severity_score=classification.severity_score,
                    households_affected=classification.households_affected,
                    classifier_version=classification.classifier_version,
                )
                if classification.asset_id:
                    updates["asset_id"] = classification.asset_id
            event = await self._repository.update_fault_event(event.id, **updates) or event

        await self._store_anomalies(run.anomalies, fault_event_id=event.id, now=now)
        return event

    def _event_evidence(
        self,
        run: DetectionRun,
        classification: Classification | None,
        *,
        previous: FaultEvent | None = None,
    ) -> dict:
        evidence: dict = dict(previous.evidence) if previous else {}
        evidence.update(
            {
                "window_start": run.window_start.isoformat(),
                "window_end": run.window_end.isoformat(),
                "anomalies": [
                    {
                        "sensor_code": anomaly.sensor_code,
                        "metric": anomaly.metric,
                        "method": anomaly.method.value,
                        "observed": anomaly.observed_value,
                        "baseline": anomaly.baseline_value,
                        "z": anomaly.z_score,
                        "severity": anomaly.severity,
                        "trusted": anomaly.details.get("sensor_trusted", True),
                    }
                    for anomaly in run.anomalies[:12]
                ],
                "untrusted_sensors": run.untrusted_sensors,
            }
        )
        if classification is not None:
            evidence.update(
                {
                    "summary": classification.summary,
                    "reasoning": classification.evidence,
                    "candidates": [c.model_dump() for c in classification.candidates],
                    "sensor_health_blocked": classification.sensor_health_blocked,
                }
            )
            if (
                previous is not None
                and previous.fault_type is not classification.fault_type
                and classification.confidence > previous.confidence
            ):
                evidence["reclassified_from"] = previous.fault_type.value
        return evidence

    async def _store_anomalies(
        self, anomalies: list[Anomaly], *, fault_event_id: str, now: datetime
    ) -> None:
        """Insert what is new; refresh what is still deviating.

        Without this the live loop would write seventeen rows every ten seconds
        and the incident's evidence would be unreadable.
        """
        cutoff = now - timedelta(
            minutes=self._settings.detection_anomaly_dedupe_minutes
        )
        existing = await self._repository.list_anomalies(
            service_area_id=self.service_area_id, since=cutoff, status="OPEN", limit=500
        )
        by_key = {anomaly_key(item): item for item in existing}

        fresh: list[Anomaly] = []
        for anomaly in anomalies:
            anomaly.fault_event_id = fault_event_id
            previous = by_key.get(anomaly_key(anomaly))
            if previous is None or previous.id is None:
                fresh.append(anomaly)
                continue
            updated = await self._repository.update_anomaly(
                previous.id,
                observed_value=anomaly.observed_value,
                baseline_value=anomaly.baseline_value,
                residual=anomaly.residual,
                z_score=anomaly.z_score,
                severity=max(anomaly.severity, previous.severity),
                window_end=anomaly.window_end,
                fault_event_id=fault_event_id,
                details={**previous.details, **anomaly.details},
            )
            if updated is not None:
                # Keep the first detection time: it is what detection latency
                # and TTWR are measured from.
                anomaly.id = updated.id
                anomaly.detected_at = updated.detected_at
        if fresh:
            stored = await self._repository.insert_anomalies(fresh)
            for anomaly, saved in zip(fresh, stored, strict=False):
                anomaly.id = saved.id

    # -- internals ---------------------------------------------------------
    async def _recent_readings(self, now: datetime) -> dict[str, list]:
        window_start = now - timedelta(minutes=self._settings.detection_window_minutes)
        sensor_ids = [sensor.id for sensor in self._sensors]
        readings = await self._repository.list_readings(
            sensor_ids,
            start=window_start,
            end=now,
            limit=max(len(sensor_ids) * 200, 500),
        )
        by_sensor: dict[str, list] = {sensor_id: [] for sensor_id in sensor_ids}
        for reading in readings:
            by_sensor.setdefault(reading.sensor_id, []).append(reading)
        for series in by_sensor.values():
            series.sort(key=lambda reading: reading.ts)
        return by_sensor

    def _assess_all(self, readings: dict[str, list], now: datetime) -> list[SensorHealth]:
        return [
            assess_sensor(
                sensor,
                readings.get(sensor.id, []),
                now=now,
                baseline=self.baselines.get(sensor.id),
                stale_multiplier=self._settings.detection_stale_interval_multiplier,
                flatline_points=self._settings.detection_flatline_points,
                monotonic=sensor.sensor_type in SKIP_BASELINE_TYPES
                or sensor.sensor_type is SensorType.RUN_HOURS,
            )
            for sensor in self._sensors
        ]


__all__ = [
    "DetectionError",
    "DetectionService",
    "STATUS_OPEN",
    "STATUS_RESOLVED",
    "STATUS_RESTORING",
]
