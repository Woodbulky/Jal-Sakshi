"""A small hydraulic model of the Vitpur network.

Sensor values are *derived*, not scripted. Demand follows a diurnal curve, the
pump is level-controlled, pressures fall out of static head minus friction, and
the tank level is integrated across steps. A fault changes a physical input and
every downstream sensor moves accordingly -- which is the whole point: the
classifier sees a coherent hydraulic signature rather than a labelled pattern.

Topology::

    SRC-01 -> PMP-01 -> OHT-01 -+-> VLV-01 -> ZONE-A (212 households)
                                +-> VLV-02 -> ZONE-B (168 households)

Signatures the four demo faults produce:

===================  ===========================================================
VALVE_CLOSURE        branch flow collapses, valve upstream pressure *rises*
                     (friction disappears), zone tail pressure collapses
PIPELINE_BURST       pump and branch flow spike, tail pressure collapses, tank
                     drains against a saturated pump, turbidity spikes
PUMP_FAILURE         pump flow 0 while energy is still drawn and run-hours
                     still count
POWER_OUTAGE         pump flow 0, energy exactly 0, run-hours frozen
===================  ===========================================================

The last two differ only in the energy and run-hours channels. That is
deliberate: it forces the classifier to use more than flow.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.schemas.network import QualityFlag
from app.simulation.faults import FaultEffect

IST = timezone(timedelta(hours=5, minutes=30))

# -- network constants ------------------------------------------------------
TANK_LITRES_PER_METRE = 10_000.0
TANK_MAX_M = 5.0
TANK_MIN_M = 0.05
TANK_SETPOINT_M = 3.5
TANK_BASE_ELEVATION_M = 12.0

PUMP_MAX_LPM = 260.0
PUMP_RATED_KW = 7.5
PUMP_IDLE_KW_FRACTION = 0.22  # energised but delivering nothing
PUMP_DISCHARGE_BASE_BAR = 1.75

#: Standing water column in the borewell. Inside the level sensor's configured
#: range (8-40 m) when healthy, and below it once the source is depleting --
#: which is what makes the seeded range a usable check rather than decoration.
SOURCE_LEVEL_M = 18.0

BAR_PER_METRE = 1.0 / 10.197

#: Average litres/minute per zone, derived from households x 264 L/household/day.
ZONE_MEAN_DEMAND_LPM = {"ZONE-A": 38.9, "ZONE-B": 30.8}

#: valve -> zone it feeds
BRANCHES: dict[str, str] = {"VLV-01": "ZONE-A", "VLV-02": "ZONE-B"}

_BRANCH_FRICTION_BAR = 0.35  # at _FRICTION_REF_LPM
_ZONE_FRICTION_BAR = 0.25
_FRICTION_REF_LPM = 60.0
_MIN_PRESSURE_BAR = 0.01

#: Mean of the diurnal curve below, used to normalise it to 1.0 over a day.
_DIURNAL_MEAN = 0.75


def _local_hour(ts: datetime) -> float:
    local = ts.astimezone(IST)
    return local.hour + local.minute / 60.0 + local.second / 3600.0


def diurnal_factor(ts: datetime) -> float:
    """Rural demand: a strong morning peak, a strong evening peak, a night trough."""
    h = _local_hour(ts)
    curve = (
        0.45
        + 1.15 * math.exp(-(((h - 7.3) / 1.5) ** 2))
        + 1.05 * math.exp(-(((h - 18.4) / 1.7) ** 2))
        + 0.25 * math.exp(-(((h - 12.5) / 2.2) ** 2))
    )
    return curve / _DIURNAL_MEAN


def _noise(sensor_code: str, ts: datetime, spread: float) -> float:
    """Deterministic per-(sensor, timestamp) jitter.

    Seeded rather than random so a backfill can be re-run and produce exactly
    the same history, and so tests are reproducible.
    """
    seed = f"{sensor_code}@{int(ts.timestamp())}"
    return random.Random(seed).uniform(-spread, spread)


def _friction_bar(flow_lpm: float, loss_at_reference: float) -> float:
    if flow_lpm <= 0:
        return 0.0
    return loss_at_reference * (flow_lpm / _FRICTION_REF_LPM) ** 1.85


@dataclass
class HydraulicState:
    """Everything that has to survive between steps."""

    oht_level_m: float = TANK_SETPOINT_M
    pump_run_hours: float = 0.0


@dataclass
class StepResult:
    values: dict[str, float | None] = field(default_factory=dict)
    quality: dict[str, QualityFlag] = field(default_factory=dict)
    #: Handy for tests and for the operator console; not persisted as telemetry.
    pump_running: bool = True
    total_demand_lpm: float = 0.0


class VitpurModel:
    """Steps the network forward and reports what each sensor would read."""

    def __init__(self, state: HydraulicState | None = None) -> None:
        self.state = state or HydraulicState()
        # A flatlined instrument repeats whatever it read when it died.
        self._flatline_hold: dict[str, float] = {}

    # -- main entry point --------------------------------------------------
    def step(
        self,
        ts: datetime,
        *,
        dt_seconds: float,
        effect: FaultEffect,
    ) -> StepResult:
        dt_minutes = dt_seconds / 60.0
        demand_factor = diurnal_factor(ts)

        # Branch flows: demand modulated by valve position, plus any leak on
        # that branch. A leak is a hole, so it flows whatever the valve allows.
        branch_flow: dict[str, float] = {}
        zone_flow: dict[str, float] = {}
        for valve, zone in BRANCHES.items():
            opening = max(0.0, min(1.0, effect.opening(valve) * effect.opening(zone)))
            demand = ZONE_MEAN_DEMAND_LPM[zone] * demand_factor
            leak = effect.leak(valve) + effect.leak(zone)
            zone_flow[zone] = demand * opening
            branch_flow[valve] = zone_flow[zone] + leak * opening

        main_leak = effect.leak("OHT-01") + effect.leak("PMP-01")
        outflow_lpm = sum(branch_flow.values()) + main_leak

        # Level-controlled pump (VFD holding the tank at setpoint). It cannot
        # exceed its rating, so a large burst saturates it and the tank falls.
        level_error = TANK_SETPOINT_M - self.state.oht_level_m
        commanded = outflow_lpm + max(-250.0, min(400.0, level_error * 900.0))
        commanded = max(0.0, min(PUMP_MAX_LPM, commanded))
        if self.state.oht_level_m >= TANK_MAX_M:
            commanded = 0.0

        pump_powered = effect.pump_powered
        pump_commanded_on = commanded > 1.0 and pump_powered
        inflow_lpm = commanded if (pump_commanded_on and effect.pump_delivering) else 0.0

        # Integrate the tank.
        net_litres = (inflow_lpm - outflow_lpm) * dt_minutes
        self.state.oht_level_m = max(
            TANK_MIN_M,
            min(TANK_MAX_M, self.state.oht_level_m + net_litres / TANK_LITRES_PER_METRE),
        )

        # An empty tank cannot feed the zones.
        if self.state.oht_level_m <= TANK_MIN_M + 1e-6:
            for zone in zone_flow:
                zone_flow[zone] *= 0.05
            for valve in branch_flow:
                branch_flow[valve] *= 0.05

        # Meters. A power outage freezes both; a failed-but-energised pump does not.
        running_now = pump_commanded_on
        if running_now:
            self.state.pump_run_hours += dt_minutes / 60.0

        if not pump_powered:
            kw = 0.0
        elif running_now and effect.pump_delivering:
            kw = PUMP_RATED_KW * (0.25 + 0.75 * (inflow_lpm / PUMP_MAX_LPM))
        elif running_now:
            kw = PUMP_RATED_KW * PUMP_IDLE_KW_FRACTION
        else:
            kw = 0.0
        interval_kwh = kw * (dt_minutes / 60.0)

        static_bar = (TANK_BASE_ELEVATION_M + self.state.oht_level_m) * BAR_PER_METRE

        result = StepResult(pump_running=running_now, total_demand_lpm=outflow_lpm)
        v = result.values

        v["SNS-SRC-01-LVL"] = SOURCE_LEVEL_M * effect.source_level_factor + 0.05 * math.sin(
            ts.timestamp() / 86400.0
        )
        v["SNS-PMP-01-FLW"] = inflow_lpm
        v["SNS-PMP-01-PRU"] = (
            PUMP_DISCHARGE_BASE_BAR + 0.30 * (inflow_lpm / 200.0) ** 1.85
            if inflow_lpm > 0
            else 0.05
        )
        v["SNS-PMP-01-ENR"] = interval_kwh
        v["SNS-PMP-01-RNH"] = self.state.pump_run_hours
        v["SNS-OHT-01-LVL"] = self.state.oht_level_m

        # Water quality at the tank.
        v["SNS-OHT-01-CHL"] = max(0.0, 0.55 * effect.chlorine_factor)
        v["SNS-OHT-01-TRB"] = max(0.05, 1.10 + effect.turbidity_add_ntu)
        v["SNS-OHT-01-PH"] = 7.32 + effect.ph_offset

        for valve, zone in BRANCHES.items():
            q_branch = branch_flow[valve]
            opening = max(0.0, min(1.0, effect.opening(valve) * effect.opening(zone)))
            upstream = max(
                _MIN_PRESSURE_BAR,
                static_bar - _friction_bar(q_branch, _BRANCH_FRICTION_BAR),
            )
            # Throttling across a nearly shut valve destroys downstream pressure.
            tail = max(
                _MIN_PRESSURE_BAR,
                upstream * (opening**1.5)
                - _friction_bar(zone_flow[zone], _ZONE_FRICTION_BAR),
            )
            v[f"SNS-{valve}-FLW"] = q_branch
            v[f"SNS-{valve}-PRU"] = upstream
            v[f"SNS-{zone}-FLW"] = zone_flow[zone]
            v[f"SNS-{zone}-PRT"] = tail

        self._apply_noise(v, ts)
        self._apply_sensor_faults(result, effect)
        return result

    def _apply_sensor_faults(self, result: StepResult, effect: FaultEffect) -> None:
        for sensor_code, flag in effect.stuck_sensors.items():
            result.quality[sensor_code] = flag
            if flag in (QualityFlag.MISSING, QualityFlag.STALE):
                result.values[sensor_code] = None
            elif flag is QualityFlag.FLATLINE:
                held = self._flatline_hold.setdefault(
                    sensor_code, float(result.values.get(sensor_code) or 0.0)
                )
                result.values[sensor_code] = held
            elif flag is QualityFlag.OUT_OF_RANGE:
                current = result.values.get(sensor_code) or 1.0
                result.values[sensor_code] = current * 42.0
        # Instruments that recovered should stop holding their last value.
        for sensor_code in list(self._flatline_hold):
            if sensor_code not in effect.stuck_sensors:
                self._flatline_hold.pop(sensor_code)

    # -- helpers -----------------------------------------------------------
    _NOISE_SPREAD: dict[str, float] = {
        "FLW": 0.015,
        "PRU": 0.008,
        "PRT": 0.010,
        "LVL": 0.003,
        "ENR": 0.012,
        "CHL": 0.030,
        "TRB": 0.060,
        "PH": 0.004,
    }

    def _apply_noise(self, values: dict[str, float | None], ts: datetime) -> None:
        for code, value in values.items():
            if value is None or code.endswith("-RNH"):
                continue  # an odometer does not jitter
            suffix = code.rsplit("-", 1)[-1]
            spread = self._NOISE_SPREAD.get(suffix, 0.01)
            values[code] = round(value * (1.0 + _noise(code, ts, spread)), 4)
