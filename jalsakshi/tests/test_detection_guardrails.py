"""The guardrails, tested on the physics rather than on mocked scores."""

from __future__ import annotations

import pytest

from app.analytics.pipeline import DetectionService
from app.core.config import Settings
from app.schemas.simulation import FaultType
from app.services.memory_repository import InMemoryRepository
from detection_fixtures import build_history

pytestmark = pytest.mark.asyncio


async def test_unknown_when_the_discriminating_sensors_are_dead(
    repository: InMemoryRepository, detection: DetectionService
) -> None:
    """Guardrail 2: below the confidence threshold, answer UNKNOWN.

    A pump reading zero flow is either a failed pump or a power cut. Energy and
    the run-hour odometer are the only channels that separate them. With both
    instruments dead the two explanations fit equally well, and an honest
    UNKNOWN is the correct answer — not a coin flip that sends the crew out
    with the wrong spare part.
    """
    now = await build_history(
        repository,
        fault_type=FaultType.PUMP_FAILURE,
        asset_code="PMP-01",
        extra_faults=[
            {
                "fault_type": FaultType.SENSOR_FAULT,
                "params": {
                    "sensor_codes": ["SNS-PMP-01-ENR", "SNS-PMP-01-RNH"],
                    "quality_flag": "MISSING",
                },
            }
        ],
    )
    run = await detection.run(now=now)

    assert run.classification is not None
    assert run.classification.fault_type is FaultType.UNKNOWN
    assert run.classification.confidence < 0.55
    assert {"SNS-PMP-01-ENR", "SNS-PMP-01-RNH"} <= set(run.untrusted_sensors)
    # It still says what it was weighing, so a human can take it from here.
    assert run.classification.candidates


async def test_detection_never_returns_the_injected_label_verbatim(
    repository: InMemoryRepository, settings: Settings
) -> None:
    """Ground-truth isolation, checked on every demo fault."""
    for fault_type, asset in (
        (FaultType.VALVE_CLOSURE, "VLV-01"),
        (FaultType.PIPELINE_BURST, "VLV-02"),
        (FaultType.PUMP_FAILURE, "PMP-01"),
        (FaultType.POWER_OUTAGE, "PMP-01"),
    ):
        fresh = InMemoryRepository(
            **{
                "service_areas": repository.service_areas,
                "assets": repository.assets,
                "connections": repository.connections,
                "sensors": repository.sensors,
            }
        )
        service = DetectionService(fresh, settings)
        now = await build_history(fresh, fault_type=fault_type, asset_code=asset)
        run = await service.run(now=now)

        payload = run.model_dump_json()
        for injection in fresh.fault_injections:
            assert injection.id not in payload
        assert run.classification is not None
