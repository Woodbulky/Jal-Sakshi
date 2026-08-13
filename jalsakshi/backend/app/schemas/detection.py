"""Wire schemas for sensor health, anomalies and classified fault events.

Everything here is *inferred* from telemetry. Nothing in this module may be
populated from `fault_injections`: that table is the simulator's ground truth
and reading it would hand the classifier its answer.

`FaultEvent.fault_type` is therefore a claim, not a fact, and it always travels
with the confidence and the evidence that produced it.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.network import QualityFlag, SensorStatus
from app.schemas.simulation import FaultType


class SensorIssue(str, Enum):
    """Why an instrument is not to be trusted."""

    STALE = "STALE"
    MISSING = "MISSING"
    FLATLINE = "FLATLINE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    NO_BASELINE = "NO_BASELINE"


class SensorHealth(BaseModel):
    """Verdict on one instrument, computed before any fault is diagnosed.

    Guardrail 1 of the agent contract: check sensor health before dispatch. A
    crew must never be sent for a fault that only a broken sensor reports.
    """

    sensor_id: str
    sensor_code: str
    asset_id: str
    status: SensorStatus
    trusted: bool
    issues: list[SensorIssue] = Field(default_factory=list)
    last_value: float | None = None
    last_seen_at: datetime | None = None
    seconds_since_last_reading: float | None = None
    quality_flag: QualityFlag = QualityFlag.GOOD
    note: str | None = None


class AnomalyMethod(str, Enum):
    ROBUST_Z = "ROBUST_Z"  # median/MAD against the diurnal baseline
    RANGE = "RANGE"  # outside the sensor's configured expected range
    SENSOR_HEALTH = "SENSOR_HEALTH"  # the instrument itself, not the network


class Anomaly(BaseModel):
    """One channel departing from what this time of day usually looks like."""

    id: str | None = None
    service_area_id: str
    asset_id: str | None = None
    sensor_id: str | None = None
    sensor_code: str | None = None
    detected_at: datetime
    window_start: datetime | None = None
    window_end: datetime | None = None
    method: AnomalyMethod = AnomalyMethod.ROBUST_Z
    metric: str
    observed_value: float | None = None
    baseline_value: float | None = None
    residual: float | None = None
    z_score: float | None = None
    #: 0..1. Normalised |z|, so severities from different channels compare.
    severity: float = 0.0
    status: str = "OPEN"
    fault_event_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def direction(self) -> str:
        if self.z_score is None:
            return "FLAT"
        return "HIGH" if self.z_score > 0 else "LOW"


class ClassificationCandidate(BaseModel):
    """A fault class the signature rules considered, and how well it fitted."""

    fault_type: FaultType
    score: float
    asset_code: str | None = None
    matched: list[str] = Field(default_factory=list)
    missed: list[str] = Field(default_factory=list)


class Classification(BaseModel):
    """What the classifier concluded, with the reasoning kept attached."""

    fault_type: FaultType
    confidence: float
    asset_id: str | None = None
    asset_code: str | None = None
    severity_score: float = 0.0
    households_affected: int = 0
    classifier_version: str
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    candidates: list[ClassificationCandidate] = Field(default_factory=list)
    #: True when every anomalous channel came from an untrusted instrument.
    sensor_health_blocked: bool = False


class FaultEvent(BaseModel):
    """A classified incident. `/incidents` in the API contract."""

    id: str
    service_area_id: str
    asset_id: str | None = None
    fault_type: FaultType = FaultType.UNKNOWN
    confidence: float = 0.0
    detected_at: datetime
    severity_score: float = 0.0
    households_affected: int = 0
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: str = "OPEN"
    resolved_at: datetime | None = None
    ttwr_minutes: float | None = None
    classifier_version: str | None = None
    created_at: datetime | None = None


class BaselineBand(BaseModel):
    """Expected band for one sensor at one instant — what the chart shades."""

    sensor_id: str
    sensor_code: str
    ts: datetime
    baseline: float | None = None
    lower: float | None = None
    upper: float | None = None
    sample_count: int = 0
    weak: bool = False


class SensorBaselineProfile(BaseModel):
    """The learned day-shape of one sensor, for the console's overlay."""

    sensor_id: str
    sensor_code: str
    bucket_minutes: int
    learned_from: int
    window_start: datetime | None = None
    window_end: datetime | None = None
    #: Local-time bucket start (minutes past midnight IST) -> median, spread.
    buckets: list[dict[str, float]] = Field(default_factory=list)


class DetectionRun(BaseModel):
    """One pass of the detector: health, anomalies, verdict, persisted event."""

    service_area_id: str
    service_area_code: str
    ran_at: datetime
    window_start: datetime
    window_end: datetime
    sensors_checked: int
    untrusted_sensors: list[str] = Field(default_factory=list)
    sensor_health: list[SensorHealth] = Field(default_factory=list)
    anomalies: list[Anomaly] = Field(default_factory=list)
    classification: Classification | None = None
    fault_event: FaultEvent | None = None
    baseline_refreshed: bool = False
    note: str | None = None
