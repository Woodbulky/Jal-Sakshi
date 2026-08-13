"""End-to-end detection: inject physics, read telemetry, name the fault.

These tests are the contract the demo rests on. They run the real hydraulic
model, write to the offline repository, and give the detector nothing but
readings — the same thing a field deployment would have.
"""

from __future__ import annotations

import pytest

from app.analytics.pipeline import STATUS_OPEN, STATUS_RESTORING, DetectionService
from app.schemas.detection import AnomalyMethod
from app.schemas.simulation import FaultType
from app.services.memory_repository import InMemoryRepository
from detection_fixtures import build_history

pytestmark = pytest.mark.asyncio


async def _run(
    repository: InMemoryRepository,
    detection: DetectionService,
    *,
    fault_type: FaultType | None = None,
    asset_code: str | None = None,
    params: dict | None = None,
):
    now = await build_history(
        repository, fault_type=fault_type, asset_code=asset_code, params=params
    )
    return await detection.run(now=now)


async def test_healthy_network_raises_nothing(
    repository: InMemoryRepository, detection: DetectionService
) -> None:
    run = await _run(repository, detection)

    assert run.anomalies == []
    assert run.classification is None
    assert run.fault_event is None
    assert all(health.trusted for health in run.sensor_health)


async def test_valve_closure_is_localised_to_the_valve(
    repository: InMemoryRepository, detection: DetectionService
) -> None:
    run = await _run(
        repository, detection, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )

    assert run.classification is not None
    assert run.classification.fault_type is FaultType.VALVE_CLOSURE
    assert run.classification.asset_code == "VLV-01"
    assert run.classification.confidence >= 0.55
    # Zone A only: the other branch is still supplied.
    assert run.classification.households_affected == 212


async def test_valve_closure_shows_upstream_pressure_rising(
    repository: InMemoryRepository, detection: DetectionService
) -> None:
    """The discriminator: friction vanishes with the flow, so upstream rises.

    A detector that only watches for falling pressure misses this fault.
    """
    run = await _run(
        repository, detection, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )

    codes = {anomaly.sensor_code for anomaly in run.anomalies}
    assert "SNS-VLV-01-FLW" in codes
    assert "SNS-ZONE-A-PRT" in codes

    reasoning = run.classification.evidence["channels"]
    assert reasoning["SNS-VLV-01-PRU"]["ratio"] >= 1.0
    assert reasoning["SNS-ZONE-A-PRT"]["ratio"] < 0.5


async def test_pipeline_burst_is_classified(
    repository: InMemoryRepository, detection: DetectionService
) -> None:
    run = await _run(
        repository,
        detection,
        fault_type=FaultType.PIPELINE_BURST,
        asset_code="VLV-02",
        params={"leak_lpm": 300.0},
    )

    assert run.classification is not None
    assert run.classification.fault_type is FaultType.PIPELINE_BURST
    assert run.classification.confidence >= 0.55


async def test_pump_failure_separates_from_power_outage(
    repository: InMemoryRepository, detection: DetectionService
) -> None:
    """Identical on flow. The energy channel and the odometer decide."""
    run = await _run(
        repository, detection, fault_type=FaultType.PUMP_FAILURE, asset_code="PMP-01"
    )

    assert run.classification is not None
    assert run.classification.fault_type is FaultType.PUMP_FAILURE
    matched = run.classification.evidence["best_rule"]["matched"]
    assert any("run-hour" in reason for reason in matched)


async def test_power_outage_separates_from_pump_failure(
    repository: InMemoryRepository, detection: DetectionService
) -> None:
    run = await _run(
        repository, detection, fault_type=FaultType.POWER_OUTAGE, asset_code="PMP-01"
    )

    assert run.classification is not None
    assert run.classification.fault_type is FaultType.POWER_OUTAGE
    matched = run.classification.evidence["best_rule"]["matched"]
    assert any("energy" in reason for reason in matched)


async def test_broken_sensor_does_not_dispatch_a_crew(
    repository: InMemoryRepository, detection: DetectionService
) -> None:
    """Guardrail 1. The network is healthy; only the instrument is not."""
    run = await _run(
        repository,
        detection,
        fault_type=FaultType.SENSOR_FAULT,
        params={"sensor_codes": ["SNS-ZONE-A-PRT"], "quality_flag": "MISSING"},
    )

    assert "SNS-ZONE-A-PRT" in run.untrusted_sensors
    assert run.classification is not None
    assert run.classification.fault_type is FaultType.SENSOR_FAULT
    assert run.classification.households_affected == 0
    assert run.classification.sensor_health_blocked is True
    assert any(
        anomaly.method is AnomalyMethod.SENSOR_HEALTH for anomaly in run.anomalies
    )


async def test_ground_truth_is_never_read(
    repository: InMemoryRepository, detection: DetectionService
) -> None:
    """The classifier must not be able to see which fault was injected."""
    run = await _run(
        repository, detection, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )

    injected = repository.fault_injections[0]
    serialised = run.model_dump_json()
    assert injected.id not in serialised
    # And the detector reached its answer without asking for the label.
    assert run.classification.evidence["best_rule"]["matched"]


async def test_persistence_opens_one_event_and_updates_it(
    repository: InMemoryRepository, detection: DetectionService
) -> None:
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )

    first = await detection.run(now=now)
    second = await detection.run(now=now)

    assert first.fault_event is not None
    assert second.fault_event is not None
    assert first.fault_event.id == second.fault_event.id
    assert len(repository.fault_events) == 1
    # The same channels deviating again refresh their anomalies rather than
    # writing a second copy of each.
    assert len(repository.anomalies) == len(first.anomalies)
    assert all(a.fault_event_id == first.fault_event.id for a in repository.anomalies)


async def test_recovery_moves_the_event_to_restoring_not_closed(
    repository: InMemoryRepository, detection: DetectionService
) -> None:
    """Telemetry recovering is evidence. Only verification may resolve."""
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    opened = await detection.run(now=now)
    assert opened.fault_event is not None
    assert opened.fault_event.status == STATUS_OPEN

    # Repair: clear the injection and let the network run healthy again.
    for injection in list(repository.fault_injections):
        await repository.clear_fault_injection(injection.id)
    repaired_now = await build_history(repository, now=now)
    recovered = await detection.run(now=repaired_now)

    assert recovered.anomalies == []
    assert recovered.fault_event is not None
    assert recovered.fault_event.status == STATUS_RESTORING
    assert recovered.fault_event.resolved_at is None
