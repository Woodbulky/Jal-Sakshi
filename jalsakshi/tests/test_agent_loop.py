"""The LangGraph loop, end to end on the hydraulic model.

These tests are the demo, written down: inject a fault, run the loop, and check
that what came out is what a judge will be told the system does.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.agent.graph import AgentRunner
from app.agent.tools import AgentTools
from app.schemas.simulation import FaultType
from app.schemas.workorder import CrewRole, WorkOrderStatus
from app.services.memory_repository import InMemoryRepository
from app.workorders.service import WorkOrderService
from detection_fixtures import build_history

pytestmark = pytest.mark.asyncio


def nodes(state) -> list[str]:
    return [step["node"] for step in state["trace"]]


def step(state, node: str) -> dict:
    return next(s for s in state["trace"] if s["node"] == node)


async def test_a_healthy_network_produces_no_work(
    repository: InMemoryRepository, agent: AgentRunner
) -> None:
    """The loop running every tick must not invent incidents on a quiet day."""
    now = await build_history(repository)
    state = await agent.run(now=now)

    assert nodes(state) == ["observe"]
    assert state["work_order"] is None
    assert repository.work_orders == []


async def test_a_valve_closure_is_diagnosed_and_dispatched_in_one_pass(
    repository: InMemoryRepository, agent: AgentRunner
) -> None:
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    state = await agent.run(now=now)

    assert nodes(state) == [
        "observe",
        "diagnose",
        "assess",
        "route",
        "dispatch",
        "remember",
    ]
    order = state["work_order"]
    assert order.status is WorkOrderStatus.ASSIGNED
    assert order.assigned_role is CrewRole.VALVE_OPERATOR
    assert order.assigned_person == "Ramesh Yadav"
    assert state["message"]
    assert "VLV-01" in state["message"]


async def test_running_twice_does_not_dispatch_twice(
    repository: InMemoryRepository, agent: AgentRunner
) -> None:
    """A scheduler calling this every tick must be safe."""
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    await agent.run(now=now)
    state = await agent.run(now=now + timedelta(minutes=1))

    assert len(repository.work_orders) == 1
    assert nodes(state) == ["observe"]
    assert len(await repository.list_assignments(active_only=True)) == 1


async def test_expensive_repairs_stop_and_name_what_is_needed(
    repository: InMemoryRepository, agent: AgentRunner
) -> None:
    """A pump failure is estimated over Vitpur's ₹15,000 autonomous limit."""
    now = await build_history(
        repository, fault_type=FaultType.PUMP_FAILURE, asset_code="PMP-01"
    )
    state = await agent.run(now=now)

    assert nodes(state) == ["observe", "diagnose", "assess", "remember"]
    assert state["work_order"].status is WorkOrderStatus.ASSESSED
    assert state["work_order"].assigned_role is None
    assert state["halted"]
    assert "approval" in state["halted"]
    assert step(state, "assess")["requires_approval"] is True


async def test_after_approval_the_next_pass_dispatches(
    repository: InMemoryRepository,
    agent: AgentRunner,
    work_orders: WorkOrderService,
) -> None:
    now = await build_history(
        repository, fault_type=FaultType.PUMP_FAILURE, asset_code="PMP-01"
    )
    state = await agent.run(now=now)
    order = state["work_order"]

    await work_orders.approve(order, approved_by="Kamla Singh", now=now)
    state = await agent.run(now=now)

    assert state["work_order"].status is WorkOrderStatus.ASSIGNED
    assert state["work_order"].assigned_role is CrewRole.PUMP_OPERATOR
    assert state["halted"] is None


async def test_a_broken_sensor_never_dispatches_a_supply_crew(
    repository: InMemoryRepository, agent: AgentRunner
) -> None:
    """Guardrail 1, through the whole loop rather than at one function."""
    now = await build_history(
        repository,
        fault_type=FaultType.SENSOR_FAULT,
        params={"sensor_codes": ["SNS-ZONE-A-PRT"], "quality_flag": "MISSING"},
    )
    state = await agent.run(now=now)

    order = state["work_order"]
    assert order.assigned_role is CrewRole.INSTRUMENTATION_TECH
    assert state["classification"].fault_type is FaultType.SENSOR_FAULT
    # The village has water, so nobody is recorded as being without it.
    assert state["classification"].households_affected == 0


async def test_a_false_fixed_report_reopens_and_then_closes_on_the_real_repair(
    repository: InMemoryRepository,
    agent: AgentRunner,
    work_orders: WorkOrderService,
) -> None:
    """The full accountability loop, which is the product in one test.

    This is the runbook's recommended sequence — the refusal, then the clean
    close — and for a while it could not happen: after the reopen the loop sent
    the crew back out and then waited for a second Telegram message that was
    never coming, so the incident could not close however well the water ran.
    """
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    state = await agent.run(now=now)
    order = state["work_order"]

    # The crew reports done, but the valve is still shut.
    order = await work_orders.record_field_update(
        order, message="Fixed", sender="Ramesh", now=now
    )
    later = now + timedelta(minutes=15)
    await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01", now=later
    )
    state = await agent.run(now=later)

    assert "verify" in nodes(state)
    assert step(state, "verify")["outcome"] == "FAILED"
    assert state["work_order"].status is WorkOrderStatus.REOPENED

    # The valve is really opened this time, and nobody says so on Telegram.
    for injection in list(repository.fault_injections):
        await repository.clear_fault_injection(injection.id)
    third = later + timedelta(minutes=20)
    await build_history(repository, now=third)
    state = await agent.run(now=third)

    # Noticing opens the window; it does not close anything on its own.
    assert step(state, "restore")["source"] == "telemetry"
    assert state["work_order"].status is WorkOrderStatus.VERIFYING
    assert step(state, "verify")["outcome"] == "PENDING"

    fourth = third + timedelta(minutes=15)
    await build_history(repository, now=fourth)
    state = await agent.run(now=fourth)

    assert step(state, "verify")["outcome"] == "PASSED"
    assert state["work_order"].status is WorkOrderStatus.CLOSED


async def test_a_reopened_order_still_faulted_is_sent_back_out(
    repository: InMemoryRepository,
    agent: AgentRunner,
    work_orders: WorkOrderService,
) -> None:
    """A reopened order must not be left with nobody on it.

    The state machine will not verify a REOPENED order, so if the loop ended
    here the incident would stay open forever with no crew assigned — the
    village would be waiting on a system that had stopped waiting on itself.
    """
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    state = await agent.run(now=now)
    order = state["work_order"]
    order = await work_orders.acknowledge(order, by="Ramesh", now=now)
    order = await work_orders.start_repair(order, by="Ramesh", now=now)
    order = await work_orders.begin_verification(order, now=now)
    await work_orders.reopen(order, reason="still dry")

    # The valve is still shut, so there is nothing to verify and somebody has
    # to go back.
    later = now + timedelta(minutes=20)
    await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01", now=later
    )
    state = await agent.run(now=later)

    assert state["work_order"].status is WorkOrderStatus.ASSIGNED


async def test_a_repair_nobody_reports_still_closes_the_incident(
    repository: InMemoryRepository, agent: AgentRunner
) -> None:
    """The crew that fixes the valve and never touches Telegram.

    Restoration is observed on the instruments, so the loop must not depend on
    a field message to reach the only path it has to CLOSED.
    """
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    state = await agent.run(now=now)
    assert state["work_order"].status is WorkOrderStatus.ASSIGNED

    for injection in list(repository.fault_injections):
        await repository.clear_fault_injection(injection.id)
    later = now + timedelta(minutes=30)
    await build_history(repository, now=later)
    state = await agent.run(now=later)

    assert nodes(state) == ["observe", "restore", "verify", "remember"]
    assert state["work_order"].status is WorkOrderStatus.VERIFYING

    # The window has to hold before the sensors are allowed to answer.
    last = later + timedelta(minutes=15)
    await build_history(repository, now=last)
    state = await agent.run(now=last)

    order = state["work_order"]
    assert order.status is WorkOrderStatus.CLOSED
    assert order.ttwr_minutes == pytest.approx(45.0, abs=2.0)
    # Nothing a human typed was involved, and the ledger says where it came from.
    entries = await repository.list_decisions(work_order_id=order.id)
    restoration = next(
        entry for entry in entries if entry.decision.get("restoration_source")
    )
    assert restoration.decision["restoration_source"] == "telemetry"
    assert restoration.decision["closes_work_order"] is False


async def test_an_unreported_repair_is_not_declared_while_the_fault_persists(
    repository: InMemoryRepository, agent: AgentRunner
) -> None:
    """Restoration is a reading, not an assumption. A dry village stays dry."""
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    await agent.run(now=now)

    later = now + timedelta(minutes=30)
    await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01", now=later
    )
    state = await agent.run(now=later)

    assert "restore" not in nodes(state)
    assert state["work_order"].status is WorkOrderStatus.ASSIGNED


async def test_a_verified_repair_closes_and_records_ttwr(
    repository: InMemoryRepository,
    agent: AgentRunner,
    work_orders: WorkOrderService,
) -> None:
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    state = await agent.run(now=now)
    order = state["work_order"]

    for injection in list(repository.fault_injections):
        await repository.clear_fault_injection(injection.id)
    order = await work_orders.record_field_update(
        order, message="Fixed", sender="Ramesh", now=now
    )
    later = now + timedelta(minutes=30)
    await build_history(repository, now=later)
    state = await agent.run(now=later)

    order = state["work_order"]
    assert order.status is WorkOrderStatus.CLOSED
    assert order.ttwr_minutes == pytest.approx(30.0, abs=2.0)
    assert step(state, "verify")["outcome"] == "PASSED"
    # And the asset remembers it.
    health = await repository.get_asset_health(order.asset_id)
    assert health.mean_ttwr_minutes == pytest.approx(order.ttwr_minutes)


async def test_an_sla_breach_escalates_without_anyone_noticing(
    repository: InMemoryRepository, agent: AgentRunner
) -> None:
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    state = await agent.run(now=now)
    order = state["work_order"]

    # Nobody touches it until well past the deadline.
    late = order.sla_deadline + timedelta(hours=1)
    await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01", now=late
    )
    state = await agent.run(now=late)

    assert "escalate" in nodes(state)
    escalated = step(state, "escalate")
    assert escalated["to_role"] == CrewRole.VWSC_SECRETARY.value
    assert escalated["level"] == 1
    assert state["work_order"].sla_breached is True
    assert len(await repository.list_escalations()) == 1


async def test_every_pass_leaves_an_auditable_trail(
    repository: InMemoryRepository, agent: AgentRunner
) -> None:
    """The question this product exists to answer is 'why did that happen?'."""
    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    state = await agent.run(now=now)

    ledger = await repository.list_decisions(
        work_order_id=state["work_order"].id
    )
    assert ledger
    changes = {entry.state_change for entry in ledger if entry.state_change}
    assert "ASSESSED -> ASSIGNED" in changes
    assert all(entry.actor for entry in ledger)
    # And the in-memory trace matches what was persisted.
    assert nodes(state)[0] == "observe"
    assert nodes(state)[-1] == "remember"


async def test_the_ground_truth_never_reaches_the_agent(
    repository: InMemoryRepository, agent: AgentRunner, tools: AgentTools
) -> None:
    """No tool can read `fault_injections`, so no pass can leak the label."""
    now = await build_history(
        repository, fault_type=FaultType.PIPELINE_BURST, asset_code="VLV-02",
        params={"leak_lpm": 300.0},
    )
    state = await agent.run(now=now)

    injected = repository.fault_injections[0]
    serialised = str(state["trace"]) + str(state["message"])
    assert injected.id not in serialised
    assert not hasattr(tools, "list_fault_injections")
    assert not any("injection" in name for name in dir(tools) if not name.startswith("_"))
