"""Work-order lifecycle: authority, the clock, and who may close an incident.

These are the rules a village committee would be told the system follows. Each
one has a test that fails if the rule is removed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.simulation import FaultType
from app.schemas.workorder import CrewRole, WorkOrderPriority, WorkOrderStatus
from app.services.memory_repository import InMemoryRepository
from app.workorders import policy
from app.workorders.service import WorkOrderError, WorkOrderService
from app.workorders.state_machine import InvalidTransition
from workorder_fixtures import drive_to_assigned, make_classification, open_order

pytestmark = pytest.mark.asyncio


# -- opening ----------------------------------------------------------------
async def test_opening_sets_priority_sla_and_action_from_the_fault(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    _, order = await open_order(repository, work_orders, households=212)

    assert order.status is WorkOrderStatus.DETECTED
    assert order.priority is WorkOrderPriority.P2  # 150..399 households
    assert order.sla_hours == policy.SLA_HOURS[WorkOrderPriority.P2]
    assert order.sla_deadline is not None
    assert "VLV-01" in order.action_summary
    assert order.wo_code.startswith("WO-")


async def test_a_second_pass_reuses_the_open_order_instead_of_duplicating_it(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """A village with one broken valve must not accumulate five tickets."""
    event, first = await open_order(repository, work_orders)
    second = await work_orders.open_for_fault(event)

    assert second.id == first.id
    assert len(repository.work_orders) == 1


async def test_more_households_means_a_shorter_deadline(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    # Same severity on both, so households is the only thing that differs.
    _, small = await open_order(
        repository, work_orders, households=20, severity=0.4
    )
    _, large = await open_order(
        repository, work_orders, households=380, asset_code="PMP-01", severity=0.4
    )

    # 380 households is the whole of Vitpur: the village is dry, so P1.
    assert large.priority is WorkOrderPriority.P1
    assert small.priority is WorkOrderPriority.P3
    assert large.sla_hours < small.sla_hours


async def test_a_broken_instrument_does_not_buy_a_p1_crew(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """Guardrail 1 at the dispatch boundary.

    A dead sensor can look severe. It must not out-rank a real outage, and it
    must not be counted as households without water — because they have water.
    """
    _, order = await open_order(
        repository,
        work_orders,
        fault_type=FaultType.SENSOR_FAULT,
        asset_code="PMP-01",
        households=380,
        sensor_health_blocked=True,
    )

    assert order.priority is not WorkOrderPriority.P1
    entry = repository.decisions[-1]
    assert entry.decision["households_affected"] == 0
    assert entry.decision["sensor_health_blocked"] is True
    assert "no supply crew dispatched" in entry.notes


async def test_a_sensor_fault_routes_to_the_instrument_technician(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    _, order = await drive_to_assigned(
        repository,
        work_orders,
        fault_type=FaultType.SENSOR_FAULT,
        asset_code="PMP-01",
    )

    assert order.assigned_role is CrewRole.INSTRUMENTATION_TECH


# -- authority --------------------------------------------------------------
async def test_spend_over_the_limit_stops_for_a_human(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """Vitpur's limit is ₹15,000; a pump failure is estimated at ₹18,000."""
    _, order = await open_order(
        repository, work_orders, fault_type=FaultType.PUMP_FAILURE, asset_code="PMP-01"
    )
    order = await work_orders.triage(order)
    order = await work_orders.classify(
        order,
        make_classification(fault_type=FaultType.PUMP_FAILURE, asset_code="PMP-01"),
    )
    order = await work_orders.assess(order)

    assert order.requires_approval is True
    with pytest.raises(WorkOrderError, match="approval"):
        await work_orders.assign(order, fault_type=FaultType.PUMP_FAILURE)


async def test_routine_spend_needs_nobody(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """Opening a valve costs ₹500. Waiting for a meeting to do it is absurd."""
    _, order = await drive_to_assigned(repository, work_orders)

    assert order.requires_approval is False
    assert order.status is WorkOrderStatus.ASSIGNED


async def test_approval_names_a_person_and_unblocks_dispatch(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    _, order = await open_order(
        repository, work_orders, fault_type=FaultType.PUMP_FAILURE, asset_code="PMP-01"
    )
    order = await work_orders.triage(order)
    order = await work_orders.classify(
        order,
        make_classification(fault_type=FaultType.PUMP_FAILURE, asset_code="PMP-01"),
    )
    order = await work_orders.assess(order)
    order = await work_orders.approve(order, approved_by="Kamla Singh")

    assert order.approved_by == "Kamla Singh"
    assert order.requires_approval is False
    order, _ = await work_orders.assign(order, fault_type=FaultType.PUMP_FAILURE)
    assert order.status is WorkOrderStatus.ASSIGNED


async def test_an_unnamed_approval_is_refused(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """'Approved' with nobody's name on it is not accountability."""
    _, order = await open_order(repository, work_orders)

    with pytest.raises(WorkOrderError, match="named approver"):
        await work_orders.approve(order, approved_by="   ")


async def test_reassessing_an_approved_order_does_not_ask_twice(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """A reopened repair must not send the committee back into a meeting."""
    _, order = await drive_to_assigned(
        repository, work_orders, fault_type=FaultType.PUMP_FAILURE, asset_code="PMP-01"
    )
    assert order.approved_by

    order = await work_orders.acknowledge(order, by="Sunil")
    order = await work_orders.start_repair(order, by="Sunil")
    order = await work_orders.begin_verification(order)
    order = await work_orders.reopen(order, reason="water still out")
    order = await work_orders.assess(order)

    assert order.requires_approval is False


# -- the clock --------------------------------------------------------------
async def test_the_sla_clock_only_breaches_after_the_deadline(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    now = datetime.now(timezone.utc)
    _, order = await drive_to_assigned(repository, work_orders, now=now)

    unbreached = await work_orders.check_sla(order, now=now + timedelta(hours=1))
    assert unbreached.sla_breached is False

    breached = await work_orders.check_sla(
        order, now=order.sla_deadline + timedelta(minutes=30)
    )
    assert breached.sla_breached is True


async def test_a_breach_is_recorded_once_not_on_every_pass(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    now = datetime.now(timezone.utc)
    _, order = await drive_to_assigned(repository, work_orders, now=now)
    late = order.sla_deadline + timedelta(hours=2)

    order = await work_orders.check_sla(order, now=late)
    before = len(repository.decisions)
    order = await work_orders.check_sla(order, now=late + timedelta(hours=1))

    assert len(repository.decisions) == before


async def test_escalation_climbs_the_ladder(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    now = datetime.now(timezone.utc)
    _, order = await drive_to_assigned(repository, work_orders, now=now)
    late = order.sla_deadline + timedelta(hours=1)
    order = await work_orders.check_sla(order, now=late)

    order, first = await work_orders.escalate(order, reason="SLA breach", now=late)
    assert first.level == 1
    assert first.to_role is CrewRole.VWSC_SECRETARY
    assert first.sla_breach_minutes == pytest.approx(60.0, abs=1.0)
    # The order is handed over, not merely annotated.
    assert order.assigned_role is CrewRole.VWSC_SECRETARY

    order, second = await work_orders.escalate(order, reason="still open", now=late)
    assert second.level == 2
    assert second.to_role is CrewRole.BLOCK_ENGINEER


async def test_an_escalation_records_who_it_came_from(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    _, order = await drive_to_assigned(repository, work_orders)
    _, escalation = await work_orders.escalate(order, reason="no response")

    assert escalation.from_role is CrewRole.VALVE_OPERATOR
    assert escalation.to_role is CrewRole.VWSC_SECRETARY


async def test_reassignment_releases_the_previous_crew(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """Two people each believing they own the job is worse than neither."""
    _, order = await drive_to_assigned(repository, work_orders)
    await work_orders.assign(order, role=CrewRole.LINEMAN, person="Dinesh")

    active = await repository.list_assignments(
        work_order_id=order.id, active_only=True
    )
    assert len(active) == 1
    assert active[0].assignee_role is CrewRole.LINEMAN
    assert len(await repository.list_assignments(work_order_id=order.id)) == 2


# -- who may close ----------------------------------------------------------
async def test_a_field_message_saying_fixed_does_not_close_anything(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """The rule the whole product rests on, at the API's front door."""
    _, order = await drive_to_assigned(repository, work_orders)
    order = await work_orders.acknowledge(order, by="Ramesh")
    order = await work_orders.start_repair(order, by="Ramesh")

    order = await work_orders.record_field_update(
        order, message="Fixed", sender="Ramesh"
    )

    assert order.status is WorkOrderStatus.RESTORATION_DETECTED
    assert order.closed_at is None
    entry = repository.decisions[-1]
    assert entry.decision["closes_work_order"] is False


async def test_a_field_message_before_the_repair_started_still_makes_sense(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """Reporting a fix straight after being assigned still passes IN_REPAIR."""
    _, order = await drive_to_assigned(repository, work_orders)

    order = await work_orders.record_field_update(
        order, message="done", sender="Ramesh"
    )

    assert order.status is WorkOrderStatus.RESTORATION_DETECTED
    assert order.repair_started_at is not None


async def test_an_ordinary_field_message_changes_no_state(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    _, order = await drive_to_assigned(repository, work_orders)
    order = await work_orders.acknowledge(order, by="Ramesh")

    updated = await work_orders.record_field_update(
        order, message="on my way, need a clamp", sender="Ramesh"
    )

    assert updated.status is order.status
    assert repository.decisions[-1].decision["claims_restoration"] is False


async def test_the_state_machine_refuses_an_illegal_jump(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    _, order = await drive_to_assigned(repository, work_orders)

    with pytest.raises(InvalidTransition):
        await repository.update_work_order(
            order.id, status=WorkOrderStatus.CLOSED.value
        )


async def test_reopening_increments_the_counter(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    _, order = await drive_to_assigned(repository, work_orders)
    order = await work_orders.acknowledge(order, by="Ramesh")
    order = await work_orders.start_repair(order, by="Ramesh")
    order = await work_orders.begin_verification(order)

    order = await work_orders.reopen(order, reason="water still out")

    assert order.status is WorkOrderStatus.REOPENED
    assert order.reopen_count == 1


# -- the ledger -------------------------------------------------------------
async def test_every_state_change_lands_in_the_ledger(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    """A state change nobody can explain later is worse than no state change."""
    _, order = await drive_to_assigned(repository, work_orders)

    changes = [d.state_change for d in repository.decisions if d.state_change]
    assert "DETECTED -> TRIAGING" in changes
    assert "TRIAGING -> CLASSIFIED" in changes
    assert "CLASSIFIED -> ASSESSED" in changes
    assert "ASSESSED -> ASSIGNED" in changes


async def test_the_ledger_records_who_acted_not_just_what_happened(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    _, order = await drive_to_assigned(repository, work_orders)
    await work_orders.acknowledge(order, by="Ramesh")

    actors = {entry.actor for entry in repository.decisions}
    assert "AGENT" in actors
    assert "Ramesh" in actors
    agent_entries = [e for e in repository.decisions if e.actor == "AGENT"]
    assert all(entry.agent_role for entry in agent_entries)


async def test_the_ledger_carries_the_evidence_for_a_diagnosis(
    repository: InMemoryRepository, work_orders: WorkOrderService
) -> None:
    _, order = await drive_to_assigned(repository, work_orders)

    classified = next(
        e for e in repository.decisions if e.state_change == "TRIAGING -> CLASSIFIED"
    )
    assert classified.confidence is not None
    assert classified.decision["fault_type"] == FaultType.VALVE_CLOSURE.value
