"""The offline double must not be laxer than the database it stands in for.

Every other test in this suite runs against `InMemoryRepository`, so anything
it accepts that Postgres would have coerced is a hole the whole suite is blind
through. That is not hypothetical: `model_copy(update=...)` does no validation,
so a `fault_type` written as the string the database column wants came back out
as a `str`, and the next `.value` on it raised `AttributeError` — crashing an
agent pass and the work-order-closed Telegram message, in code the suite was
green about.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.schemas.detection import FaultEvent
from app.schemas.simulation import FaultType
from app.schemas.workorder import WorkOrder, WorkOrderPriority, WorkOrderStatus
from app.services.memory_repository import InMemoryRepository

pytestmark = pytest.mark.asyncio


def _event() -> FaultEvent:
    return FaultEvent(
        id="fe-1",
        service_area_id="sa-1",
        fault_type=FaultType.UNKNOWN,
        confidence=0.1,
        detected_at=datetime.now(timezone.utc),
        status="OPEN",
    )


async def test_an_enum_written_as_its_value_reads_back_as_the_enum() -> None:
    """`DetectionService._persist` writes `fault_type.value`, as the column wants."""
    repository = InMemoryRepository(fault_events=[_event()])

    updated = await repository.update_fault_event(
        "fe-1", fault_type=FaultType.VALVE_CLOSURE.value, confidence=0.9
    )

    assert updated.fault_type is FaultType.VALVE_CLOSURE
    assert updated.fault_type.value == "VALVE_CLOSURE"  # the call that used to crash
    assert (await repository.get_fault_event("fe-1")).fault_type is (
        FaultType.VALVE_CLOSURE
    )


async def test_a_work_order_status_written_as_a_string_reads_back_as_the_enum() -> None:
    repository = InMemoryRepository(
        work_orders=[
            WorkOrder(
                id="wo-1",
                wo_code="WO-001",
                service_area_id="sa-1",
                status=WorkOrderStatus.DETECTED,
                priority=WorkOrderPriority.P2,
            )
        ]
    )

    updated = await repository.update_work_order("wo-1", status="TRIAGING")

    assert updated.status is WorkOrderStatus.TRIAGING
    assert updated.updated_at is not None


async def test_an_update_leaves_untouched_fields_alone() -> None:
    """Re-validating the whole model must not quietly drop what it did not set."""
    repository = InMemoryRepository(fault_events=[_event()])

    updated = await repository.update_fault_event("fe-1", status="RESTORING")

    assert updated.status == "RESTORING"
    assert updated.id == "fe-1"
    assert updated.service_area_id == "sa-1"
    assert updated.confidence == pytest.approx(0.1)
