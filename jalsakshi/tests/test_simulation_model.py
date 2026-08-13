"""The hydraulic model must produce a diagnosable signature for each fault.

These tests are the contract the fault classifier will be written against: if a
signature here changes, detection has to change with it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.network import QualityFlag
from app.schemas.simulation import FaultInjection, FaultType
from app.simulation.faults import resolve_effect
from app.simulation.model import VitpurModel

STEP_SECONDS = 300.0
START = datetime(2026, 8, 12, 6, 0, tzinfo=timezone.utc)  # 11:30 IST, mid-morning


def _run(
    injections: list[FaultInjection] | None = None,
    *,
    steps: int = 12,
    start: datetime = START,
) -> dict[str, float | None]:
    """Step the model forward and hand back the final sample."""
    model = VitpurModel()
    result = None
    ts = start
    for _ in range(steps):
        effect = resolve_effect(injections or [], ts)
        result = model.step(ts, dt_seconds=STEP_SECONDS, effect=effect)
        ts += timedelta(seconds=STEP_SECONDS)
    assert result is not None
    return result.values


def _injection(fault_type: FaultType, asset_code: str | None = None, **params) -> FaultInjection:
    return FaultInjection(
        id="00000000-0000-0000-0000-000000000001",
        service_area_id="area",
        asset_id=asset_code,  # resolve_effect falls back to the raw ref as a code
        fault_type=fault_type,
        started_at=START,
        params=params,
    )


@pytest.fixture(scope="module")
def healthy() -> dict[str, float | None]:
    return _run()


def test_a_healthy_network_moves_water(healthy: dict[str, float | None]) -> None:
    assert healthy["SNS-PMP-01-FLW"] > 0
    assert healthy["SNS-ZONE-A-FLW"] > healthy["SNS-ZONE-B-FLW"]  # 212 vs 168 households
    assert healthy["SNS-PMP-01-ENR"] > 0
    assert 1.0 < healthy["SNS-OHT-01-LVL"] < 5.0
    assert healthy["SNS-ZONE-A-PRT"] > 0.5
    assert 6.9 < healthy["SNS-OHT-01-PH"] < 7.7


def test_demand_peaks_in_the_morning_and_evening() -> None:
    night = _run(start=datetime(2026, 8, 12, 20, 30, tzinfo=timezone.utc))  # 02:00 IST
    morning = _run(start=datetime(2026, 8, 12, 1, 45, tzinfo=timezone.utc))  # 07:15 IST
    assert morning["SNS-ZONE-A-FLW"] > 2 * night["SNS-ZONE-A-FLW"]


def test_valve_closure_starves_its_branch_and_raises_upstream_pressure(
    healthy: dict[str, float | None],
) -> None:
    faulted = _run([_injection(FaultType.VALVE_CLOSURE, "VLV-01")])

    assert faulted["SNS-ZONE-A-FLW"] < 0.15 * healthy["SNS-ZONE-A-FLW"]
    assert faulted["SNS-ZONE-A-PRT"] < 0.2 * healthy["SNS-ZONE-A-PRT"]
    # Friction disappears with the flow, so the valve sees near-static head.
    assert faulted["SNS-VLV-01-PRU"] > healthy["SNS-VLV-01-PRU"]
    # The other branch carries on as normal -- that localises the fault.
    assert faulted["SNS-ZONE-B-FLW"] == pytest.approx(healthy["SNS-ZONE-B-FLW"], rel=0.1)


def test_pipeline_burst_spikes_flow_and_collapses_tail_pressure(
    healthy: dict[str, float | None],
) -> None:
    faulted = _run([_injection(FaultType.PIPELINE_BURST, "VLV-02", leak_lpm=300)])

    assert faulted["SNS-VLV-02-FLW"] > 4 * healthy["SNS-VLV-02-FLW"]
    assert faulted["SNS-PMP-01-FLW"] > healthy["SNS-PMP-01-FLW"]
    assert faulted["SNS-ZONE-B-PRT"] < 0.3 * healthy["SNS-ZONE-B-PRT"]
    # The pump saturates, so the tank cannot keep up.
    assert faulted["SNS-OHT-01-LVL"] < healthy["SNS-OHT-01-LVL"]
    assert faulted["SNS-OHT-01-TRB"] > 4 * healthy["SNS-OHT-01-TRB"]
    assert faulted["SNS-OHT-01-CHL"] < healthy["SNS-OHT-01-CHL"]


def test_pump_failure_stops_flow_while_the_motor_still_draws_power() -> None:
    faulted = _run([_injection(FaultType.PUMP_FAILURE, "PMP-01")])

    assert faulted["SNS-PMP-01-FLW"] == 0
    assert faulted["SNS-PMP-01-ENR"] > 0  # energised but moving nothing
    assert faulted["SNS-PMP-01-RNH"] > 0  # odometer still counting


def test_power_outage_stops_flow_energy_and_the_run_hour_meter() -> None:
    faulted = _run([_injection(FaultType.POWER_OUTAGE, "PMP-01")])

    assert faulted["SNS-PMP-01-FLW"] == 0
    assert faulted["SNS-PMP-01-ENR"] == 0
    assert faulted["SNS-PMP-01-RNH"] == 0


def test_pump_failure_and_power_outage_differ_only_in_the_meters() -> None:
    """The discriminator the classifier must learn: flow alone is not enough."""
    failure = _run([_injection(FaultType.PUMP_FAILURE, "PMP-01")])
    outage = _run([_injection(FaultType.POWER_OUTAGE, "PMP-01")])

    assert failure["SNS-PMP-01-FLW"] == outage["SNS-PMP-01-FLW"] == 0
    assert failure["SNS-PMP-01-ENR"] > outage["SNS-PMP-01-ENR"]
    assert failure["SNS-PMP-01-RNH"] > outage["SNS-PMP-01-RNH"]


def test_a_fault_ramps_in_rather_than_stepping() -> None:
    injection = _injection(FaultType.VALVE_CLOSURE, "VLV-01", ramp_minutes=30)
    early = _run([injection], steps=2)  # 5 minutes in
    late = _run([injection], steps=12)  # an hour in
    assert early["SNS-ZONE-A-FLW"] > late["SNS-ZONE-A-FLW"]


def test_a_sensor_fault_flatlines_one_instrument_and_leaves_the_network_alone(
    healthy: dict[str, float | None],
) -> None:
    model = VitpurModel()
    injection = _injection(
        FaultType.SENSOR_FAULT, "ZONE-A", sensor_code="SNS-ZONE-A-FLW"
    )

    ts = START
    samples = []
    for _ in range(12):
        effect = resolve_effect([injection], ts)
        result = model.step(ts, dt_seconds=STEP_SECONDS, effect=effect)
        samples.append(result)
        ts += timedelta(seconds=STEP_SECONDS)

    held = {s.values["SNS-ZONE-A-FLW"] for s in samples}
    assert len(held) == 1, "a flatlined sensor repeats its last good value"
    assert samples[-1].quality["SNS-ZONE-A-FLW"] is QualityFlag.FLATLINE
    # Water is still flowing; only the instrument is broken.
    assert samples[-1].values["SNS-ZONE-A-PRT"] == pytest.approx(
        healthy["SNS-ZONE-A-PRT"], rel=0.15
    )


def test_fault_onset_runs_on_the_accelerated_clock() -> None:
    """A 6-minute closure must develop in ~12 wall-clock seconds at 30x.

    Otherwise the demo would inject at 0:10 and still look healthy at 1:30.
    """
    injection = _injection(FaultType.VALVE_CLOSURE, "VLV-01", ramp_minutes=6)
    twelve_seconds_in = START + timedelta(seconds=12)

    real_time = resolve_effect([injection], twelve_seconds_in, time_scale=1.0)
    accelerated = resolve_effect([injection], twelve_seconds_in, time_scale=30.0)

    assert real_time.opening("VLV-01") > 0.9  # barely started
    assert accelerated.opening("VLV-01") < 0.1  # effectively shut


def test_the_same_timestamp_always_produces_the_same_noise() -> None:
    assert _run()["SNS-ZONE-A-FLW"] == _run()["SNS-ZONE-A-FLW"]
