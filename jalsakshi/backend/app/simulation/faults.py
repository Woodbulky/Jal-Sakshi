"""How an injected fault deforms the hydraulic model.

A fault never writes a sensor value directly. It changes *physical* quantities
-- a valve position, a leak rate, whether the pump is energised -- and the
hydraulic model in `model.py` works out what the sensors would then read. That
is what makes the resulting telemetry diagnosable rather than merely labelled.

Each fault also ramps in over a realistic interval instead of appearing as a
step, so anomaly detection has to cope with the same onset shape it would see
in the field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.schemas.network import QualityFlag
from app.schemas.simulation import FaultInjection, FaultType

#: Default onset time per fault, in minutes. A valve is wound shut by hand, a
#: burst opens fast, and a power cut is instantaneous.
_DEFAULT_RAMP_MINUTES: dict[FaultType, float] = {
    FaultType.VALVE_CLOSURE: 6.0,
    FaultType.PIPELINE_BURST: 4.0,
    FaultType.PUMP_FAILURE: 1.5,
    FaultType.POWER_OUTAGE: 0.0,
    FaultType.SOURCE_DEPLETION: 90.0,
    FaultType.SENSOR_FAULT: 0.0,
    FaultType.THEFT_OR_UNAUTHORISED_TAPPING: 15.0,
}

_DEFAULT_CLOSURE_FRACTION = 0.04  # residual opening of a "closed" valve
_DEFAULT_BURST_LPM = 300.0
_DEFAULT_TAPPING_LPM = 45.0


@dataclass
class FaultEffect:
    """Physical deltas applied to one simulation step.

    Keys are asset codes, so the model stays readable and the effect of a fault
    is scoped to the branch it was injected on.
    """

    valve_open: dict[str, float] = field(default_factory=dict)
    leak_lpm: dict[str, float] = field(default_factory=dict)
    pump_powered: bool = True
    pump_delivering: bool = True
    source_level_factor: float = 1.0
    turbidity_add_ntu: float = 0.0
    chlorine_factor: float = 1.0
    ph_offset: float = 0.0
    stuck_sensors: dict[str, QualityFlag] = field(default_factory=dict)

    def opening(self, asset_code: str) -> float:
        return self.valve_open.get(asset_code, 1.0)

    def leak(self, asset_code: str) -> float:
        return self.leak_lpm.get(asset_code, 0.0)

    @property
    def total_leak_lpm(self) -> float:
        return sum(self.leak_lpm.values())


def _ramp(injection: FaultInjection, ts: datetime, time_scale: float) -> float:
    """0.0 just before onset, 1.0 once the fault is fully developed.

    `ramp_minutes` is *simulated* time, so it runs on the same accelerated clock
    as the hydraulic integration. At the default 30x, a six-minute valve closure
    develops in twelve wall-clock seconds -- which is what the 90-second demo
    script needs.
    """
    minutes = float(
        injection.params.get(
            "ramp_minutes", _DEFAULT_RAMP_MINUTES.get(injection.fault_type, 3.0)
        )
    )
    elapsed = (ts - injection.started_at).total_seconds() * max(time_scale, 1e-9) / 60.0
    if elapsed < 0:
        return 0.0
    if minutes <= 0:
        return 1.0  # a power cut has no onset
    return min(1.0, elapsed / minutes)


def _blend(normal: float, faulted: float, progress: float) -> float:
    return normal + (faulted - normal) * progress


def is_active_at(injection: FaultInjection, ts: datetime) -> bool:
    if injection.cleared_at is not None and ts >= injection.cleared_at:
        return False
    if injection.ends_at is not None and ts >= injection.ends_at:
        return False
    return injection.is_active and ts >= injection.started_at


def resolve_effect(
    injections: list[FaultInjection],
    ts: datetime,
    *,
    asset_codes: dict[str, str] | None = None,
    time_scale: float = 1.0,
) -> FaultEffect:
    """Combine every fault active at `ts` into one set of physical deltas.

    `asset_codes` maps asset id -> asset code, because injections reference
    assets by id once persisted. `time_scale` matches the engine's, so fault
    onset and hydraulic integration advance together.
    """
    effect = FaultEffect()
    asset_codes = asset_codes or {}

    for injection in injections:
        if not is_active_at(injection, ts):
            continue

        progress = _ramp(injection, ts, time_scale)
        if progress <= 0.0:
            continue

        code = asset_codes.get(injection.asset_id or "", injection.asset_id or "")
        params = injection.params

        if injection.fault_type is FaultType.VALVE_CLOSURE:
            closed_to = float(params.get("closure_fraction", _DEFAULT_CLOSURE_FRACTION))
            current = effect.opening(code)
            effect.valve_open[code] = min(current, _blend(1.0, closed_to, progress))

        elif injection.fault_type is FaultType.PIPELINE_BURST:
            rate = float(params.get("leak_lpm", _DEFAULT_BURST_LPM))
            effect.leak_lpm[code] = effect.leak(code) + _blend(0.0, rate, progress)
            # Disturbed sediment and ingress at the break.
            effect.turbidity_add_ntu += _blend(0.0, 6.5, progress)
            effect.chlorine_factor *= _blend(1.0, 0.45, progress)
            effect.ph_offset += _blend(0.0, -0.22, progress)

        elif injection.fault_type is FaultType.PUMP_FAILURE:
            # Motor is still energised; the pump simply moves no water. Energy
            # keeps being drawn and run-hours keep counting -- that is what
            # separates this from a power outage.
            if progress >= 0.5:
                effect.pump_delivering = False

        elif injection.fault_type is FaultType.POWER_OUTAGE:
            effect.pump_delivering = False
            effect.pump_powered = False

        elif injection.fault_type is FaultType.SOURCE_DEPLETION:
            effect.source_level_factor = min(
                effect.source_level_factor, _blend(1.0, 0.35, progress)
            )

        elif injection.fault_type is FaultType.THEFT_OR_UNAUTHORISED_TAPPING:
            rate = float(params.get("leak_lpm", _DEFAULT_TAPPING_LPM))
            effect.leak_lpm[code] = effect.leak(code) + _blend(0.0, rate, progress)

        elif injection.fault_type is FaultType.SENSOR_FAULT:
            # The network is healthy; the instrument is not. This exists so the
            # sensor-health guardrail can be tested: the agent must not dispatch
            # a crew for a fault that only a broken sensor reports.
            flag = QualityFlag(str(params.get("quality_flag", QualityFlag.FLATLINE.value)))
            for sensor_code in params.get("sensor_codes", []) or []:
                effect.stuck_sensors[str(sensor_code)] = flag
            if single := params.get("sensor_code"):
                effect.stuck_sensors[str(single)] = flag

    return effect
