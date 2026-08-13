"""Wire schemas for the simulator.

Everything in this module is *operator-facing*. The fault label carried here is
ground truth: it is written to `fault_injections`, it is served under
`/api/v1/simulation/*` for the demo console, and it must never be read by the
fault classifier or the agent. Detection has to earn its answer from telemetry.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.network import QualityFlag


class FaultType(str, Enum):
    PUMP_FAILURE = "PUMP_FAILURE"
    POWER_OUTAGE = "POWER_OUTAGE"
    PIPELINE_BURST = "PIPELINE_BURST"
    VALVE_CLOSURE = "VALVE_CLOSURE"
    SOURCE_DEPLETION = "SOURCE_DEPLETION"
    SENSOR_FAULT = "SENSOR_FAULT"
    THEFT_OR_UNAUTHORISED_TAPPING = "THEFT_OR_UNAUTHORISED_TAPPING"
    UNKNOWN = "UNKNOWN"


#: The four faults the demo must be able to inject and diagnose.
DEMO_FAULTS: tuple[FaultType, ...] = (
    FaultType.VALVE_CLOSURE,
    FaultType.PIPELINE_BURST,
    FaultType.PUMP_FAILURE,
    FaultType.POWER_OUTAGE,
)


class FaultInjection(BaseModel):
    """A fault the simulator is applying. Ground truth, never a classifier input."""

    id: str
    service_area_id: str
    asset_id: str | None = None
    fault_type: FaultType
    started_at: datetime
    ends_at: datetime | None = None
    cleared_at: datetime | None = None
    is_active: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


class InjectFaultRequest(BaseModel):
    service_area_id: str = "demo-vitpur"
    fault_type: FaultType
    asset_id: str | None = None
    ends_at: datetime | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class GeneratedReading(BaseModel):
    """One simulated sample, keyed by sensor code for readability in tests."""

    sensor_code: str
    sensor_id: str
    ts: datetime
    value: float | None
    quality_flag: QualityFlag = QualityFlag.GOOD


class SimulationStatus(BaseModel):
    service_area_id: str
    service_area_code: str
    running: bool
    tick_seconds: float
    #: Hydraulic integration runs this many times faster than the wall clock, so
    #: tank level and meter counters move visibly during a 90-second demo.
    #: Timestamps stay real, so SLA and TTWR remain honest.
    time_scale: float
    sensor_count: int
    last_tick_at: datetime | None = None
    readings_written: int = 0
    active_injections: list[FaultInjection] = Field(default_factory=list)


class BackfillResult(BaseModel):
    hours: int
    step_minutes: int
    readings_written: int
    window_start: datetime
    window_end: datetime
