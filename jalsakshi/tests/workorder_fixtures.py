"""Helpers for driving a work order without running the hydraulic model.

Most lifecycle rules — transitions, budget, SLA, escalation, the ledger — are
about bookkeeping and do not need 48 hours of simulated telemetry to exercise.
The tests that *do* need physics (verification) use `detection_fixtures`
instead.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas.detection import Classification, FaultEvent
from app.schemas.simulation import FaultType
from app.services.memory_repository import InMemoryRepository
from app.workorders.service import WorkOrderService


def make_event(
    repository: InMemoryRepository,
    *,
    fault_type: FaultType = FaultType.VALVE_CLOSURE,
    asset_code: str = "VLV-01",
    households: int = 212,
    confidence: float = 0.9,
    severity: float = 0.7,
    detected_at: datetime | None = None,
) -> FaultEvent:
    area = repository.service_areas[0]
    asset = next(a for a in repository.assets if a.asset_code == asset_code)
    return FaultEvent(
        id="",
        service_area_id=area.id,
        asset_id=asset.id,
        fault_type=fault_type,
        confidence=confidence,
        detected_at=detected_at or datetime.now(timezone.utc),
        severity_score=severity,
        households_affected=households,
        evidence={"source": "test fixture"},
        status="OPEN",
        classifier_version="test",
    )


def make_classification(
    *,
    fault_type: FaultType = FaultType.VALVE_CLOSURE,
    asset_code: str = "VLV-01",
    households: int = 212,
    confidence: float = 0.9,
    sensor_health_blocked: bool = False,
) -> Classification:
    return Classification(
        fault_type=fault_type,
        confidence=confidence,
        asset_code=asset_code,
        severity_score=0.7,
        households_affected=households,
        classifier_version="test",
        summary=f"test {fault_type.value}",
        sensor_health_blocked=sensor_health_blocked,
    )


async def open_order(
    repository: InMemoryRepository,
    service: WorkOrderService,
    *,
    fault_type: FaultType = FaultType.VALVE_CLOSURE,
    asset_code: str = "VLV-01",
    households: int = 212,
    severity: float = 0.7,
    sensor_health_blocked: bool = False,
    detected_at: datetime | None = None,
    now: datetime | None = None,
):
    """A stored fault event and the work order opened against it."""
    event = await repository.create_fault_event(
        make_event(
            repository,
            fault_type=fault_type,
            asset_code=asset_code,
            households=households,
            severity=severity,
            detected_at=detected_at,
        )
    )
    order = await service.open_for_fault(
        event,
        classification=make_classification(
            fault_type=fault_type,
            asset_code=asset_code,
            households=households,
            sensor_health_blocked=sensor_health_blocked,
        ),
        asset_code=asset_code,
        now=now,
    )
    return event, order


async def drive_to_assigned(
    repository: InMemoryRepository,
    service: WorkOrderService,
    *,
    fault_type: FaultType = FaultType.VALVE_CLOSURE,
    asset_code: str = "VLV-01",
    households: int = 212,
    now: datetime | None = None,
):
    """The ordinary path up to a crew being committed."""
    now = now or datetime.now(timezone.utc)
    event, order = await open_order(
        repository,
        service,
        fault_type=fault_type,
        asset_code=asset_code,
        households=households,
        now=now,
    )
    order = await service.triage(order)
    order = await service.classify(
        order, make_classification(fault_type=fault_type, asset_code=asset_code)
    )
    order = await service.assess(order, now=now)
    if order.requires_approval:
        order = await service.approve(order, approved_by="Test Approver", now=now)
    order, _ = await service.assign(order, fault_type=fault_type, now=now)
    return event, order


def hours(count: float) -> timedelta:
    return timedelta(hours=count)
