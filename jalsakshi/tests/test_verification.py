"""Sensor-verified closure, tested against the hydraulic model.

No mocked verdicts here. A fault is physically injected, a crew "reports" the
repair, and the verification service is given nothing but telemetry — the same
thing it would have in a village.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.schemas.simulation import FaultType
from app.schemas.workorder import VerificationOutcome, WorkOrderStatus
from app.services.memory_repository import InMemoryRepository
from app.workorders.service import WorkOrderService
from detection_fixtures import build_history
from workorder_fixtures import drive_to_assigned

pytestmark = pytest.mark.asyncio


async def _report_fixed(
    work_orders: WorkOrderService, order, *, at, sender: str = "Ramesh"
):
    """The field actor says the job is done — which starts verification."""
    return await work_orders.record_field_update(
        order, message="Fixed", sender=sender, now=at
    )


async def test_a_still_broken_network_reopens_the_order(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """The crew says done; the valve is still shut. The sensors win."""
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    _, order = await drive_to_assigned(repository, work_orders, now=now)
    order = await _report_fixed(work_orders, order, at=now)

    later = now + timedelta(minutes=15)
    await build_history(
        repository,
        fault_type=FaultType.VALVE_CLOSURE,
        asset_code="VLV-01",
        now=later,
    )
    order, report = await work_orders.verify(
        order, fault_type=FaultType.VALVE_CLOSURE, now=later
    )

    assert report.outcome is VerificationOutcome.FAILED
    assert order.status is WorkOrderStatus.REOPENED
    assert order.closed_at is None
    assert order.reopen_count == 1
    assert any(not check.passed for check in report.checks)


async def test_a_genuine_repair_closes_the_order_with_a_ttwr(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    event, order = await drive_to_assigned(repository, work_orders, now=now)
    order = await _report_fixed(work_orders, order, at=now)

    # The valve is actually opened and telemetry keeps flowing.
    for injection in list(repository.fault_injections):
        await repository.clear_fault_injection(injection.id)
    later = now + timedelta(minutes=30)
    await build_history(repository, now=later)

    order, report = await work_orders.verify(
        order,
        fault_type=FaultType.VALVE_CLOSURE,
        detected_at=event.detected_at,
        now=later,
    )

    assert report.outcome is VerificationOutcome.PASSED
    assert order.status is WorkOrderStatus.CLOSED
    assert order.closed_at is not None
    assert order.ttwr_minutes == pytest.approx(30.0, abs=1.0)
    assert all(check.passed for check in report.checks)


async def test_closing_is_the_only_thing_that_writes_a_ttwr(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """TTWR is time to *verified* restoration, not time to a phone call."""
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    _, order = await drive_to_assigned(repository, work_orders, now=now)
    order = await _report_fixed(work_orders, order, at=now)

    assert order.status is WorkOrderStatus.RESTORATION_DETECTED
    assert order.ttwr_minutes is None


async def test_too_soon_after_the_repair_is_pending_not_a_pass(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """One lucky sample must not close an incident."""
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    _, order = await drive_to_assigned(repository, work_orders, now=now)
    order = await _report_fixed(work_orders, order, at=now)

    for injection in list(repository.fault_injections):
        await repository.clear_fault_injection(injection.id)
    barely_later = now + timedelta(minutes=2)  # window is 10 in the fixture
    await build_history(repository, now=barely_later)

    order, report = await work_orders.verify(
        order, fault_type=FaultType.VALVE_CLOSURE, now=barely_later
    )

    assert report.outcome is VerificationOutcome.PENDING
    assert order.status is WorkOrderStatus.VERIFYING
    assert order.closed_at is None


async def test_dead_instruments_produce_unverifiable_never_a_pass(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """Guardrail 7. A sensor that died during the repair is not a green light.

    This is the case that separates JAL-SAKSHI from a ticketing system: the
    honest answer is 'I cannot tell', and it goes to a human rather than
    closing an incident the village would then have to reopen themselves.
    """
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    _, order = await drive_to_assigned(repository, work_orders, now=now)
    order = await _report_fixed(work_orders, order, at=now)

    # Repair the valve, but the instruments watching it go dark.
    for injection in list(repository.fault_injections):
        await repository.clear_fault_injection(injection.id)
    later = now + timedelta(minutes=30)
    await build_history(
        repository,
        fault_type=FaultType.SENSOR_FAULT,
        params={
            "sensor_codes": [
                "SNS-VLV-01-FLW",
                "SNS-VLV-01-PRU",
                "SNS-ZONE-A-PRT",
                "SNS-ZONE-A-FLW",
            ],
            "quality_flag": "MISSING",
        },
        now=later,
    )

    order, report = await work_orders.verify(
        order, fault_type=FaultType.VALVE_CLOSURE, now=later
    )

    assert report.outcome is VerificationOutcome.UNVERIFIABLE
    assert order.status is WorkOrderStatus.UNVERIFIABLE
    assert order.closed_at is None
    assert order.ttwr_minutes is None
    assert report.untrusted_sensors
    assert "human" in report.summary.lower()


async def test_an_unverifiable_order_can_still_be_verified_later(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """UNVERIFIABLE means 'not yet', not 'never'."""
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    event, order = await drive_to_assigned(repository, work_orders, now=now)
    order = await _report_fixed(work_orders, order, at=now)

    for injection in list(repository.fault_injections):
        await repository.clear_fault_injection(injection.id)
    dark = now + timedelta(minutes=30)
    await build_history(
        repository,
        fault_type=FaultType.SENSOR_FAULT,
        params={
            "sensor_codes": ["SNS-VLV-01-FLW", "SNS-VLV-01-PRU", "SNS-ZONE-A-PRT",
                             "SNS-ZONE-A-FLW"],
            "quality_flag": "MISSING",
        },
        now=dark,
    )
    order, _ = await work_orders.verify(
        order, fault_type=FaultType.VALVE_CLOSURE, now=dark
    )
    assert order.status is WorkOrderStatus.UNVERIFIABLE

    # The technician replaces the instruments and telemetry returns.
    for injection in list(repository.fault_injections):
        await repository.clear_fault_injection(injection.id)
    repaired = dark + timedelta(minutes=30)
    await build_history(repository, now=repaired)

    order, report = await work_orders.verify(
        order,
        fault_type=FaultType.VALVE_CLOSURE,
        detected_at=event.detected_at,
        now=repaired,
    )

    assert report.outcome is VerificationOutcome.PASSED
    assert order.status is WorkOrderStatus.CLOSED


async def test_the_report_says_which_condition_failed(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """A verdict a human cannot interrogate is not evidence."""
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    _, order = await drive_to_assigned(repository, work_orders, now=now)
    order = await _report_fixed(work_orders, order, at=now)

    later = now + timedelta(minutes=15)
    await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01", now=later
    )
    _, report = await work_orders.verify(
        order, fault_type=FaultType.VALVE_CLOSURE, now=later
    )

    names = {check.name for check in report.checks}
    assert "verification_window" in names
    assert "diurnal_pattern" in names
    failed = [check for check in report.checks if not check.passed]
    assert all(check.detail for check in failed)
    # The numbers behind the verdict travel with it.
    assert any(check.observed is not None for check in failed)
