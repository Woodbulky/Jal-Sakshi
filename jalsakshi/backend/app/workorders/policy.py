"""Routing, priority, SLA and escalation policy.

All of it is deterministic. The LLM may write the *wording* of a work order; it
may not decide who gets sent, how long they have, or when a breach is called.
Those are the numbers a village committee will be held to, so they live in a
table that can be read, argued with, and changed without retraining anything.

Priority is a function of how many households are dark and how severe the fault
is — not of how confident the classifier feels.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.schemas.simulation import FaultType
from app.schemas.workorder import CrewRole, WorkOrderPriority

#: Who is competent to act on each fault class.
ROLE_FOR_FAULT: dict[FaultType, CrewRole] = {
    FaultType.PUMP_FAILURE: CrewRole.PUMP_OPERATOR,
    FaultType.POWER_OUTAGE: CrewRole.ELECTRICIAN,
    FaultType.PIPELINE_BURST: CrewRole.LINEMAN,
    FaultType.VALVE_CLOSURE: CrewRole.VALVE_OPERATOR,
    FaultType.SOURCE_DEPLETION: CrewRole.VWSC_SECRETARY,
    FaultType.SENSOR_FAULT: CrewRole.INSTRUMENTATION_TECH,
    FaultType.THEFT_OR_UNAUTHORISED_TAPPING: CrewRole.VWSC_SECRETARY,
    # An unnamed fault needs a human to look, not a crew with a spare part.
    FaultType.UNKNOWN: CrewRole.VWSC_SECRETARY,
}

#: Hours to restore, by priority. P1 is "the village has no water tonight".
SLA_HOURS: dict[WorkOrderPriority, float] = {
    WorkOrderPriority.P1: 4.0,
    WorkOrderPriority.P2: 8.0,
    WorkOrderPriority.P3: 24.0,
    WorkOrderPriority.P4: 72.0,
}

#: Who a breach is raised to. Level 1 is the committee, level 2 the block.
ESCALATION_LADDER: tuple[CrewRole, ...] = (
    CrewRole.VWSC_SECRETARY,
    CrewRole.BLOCK_ENGINEER,
)

#: A fault that only a broken instrument reports never costs a village its
#: water, so it never outranks a real outage however loud the anomaly is.
_NON_SUPPLY_FAULTS = frozenset({FaultType.SENSOR_FAULT})

#: Typical repair cost by fault class, in rupees. Used for the approval
#: boundary before a crew is committed, not for accounting.
ESTIMATED_COST: dict[FaultType, float] = {
    # Pump work — rewinding or replacing a 5HP submersible with its starter —
    # is the one routine fault that lands above the committee's ₹15,000
    # autonomous limit, which is why it is the fault that asks for a human.
    FaultType.PUMP_FAILURE: 18000.0,
    FaultType.POWER_OUTAGE: 1500.0,
    FaultType.PIPELINE_BURST: 8000.0,
    FaultType.VALVE_CLOSURE: 500.0,
    FaultType.SOURCE_DEPLETION: 25000.0,
    FaultType.SENSOR_FAULT: 3000.0,
    FaultType.THEFT_OR_UNAUTHORISED_TAPPING: 2000.0,
    FaultType.UNKNOWN: 1000.0,
}


#: Households without water at which an incident becomes a P1. Set below the
#: size of a single village on purpose: a source- or pump-side fault takes out
#: the whole of Vitpur's 380 households, and "the entire village is dry" is the
#: definition of a P1 — a threshold above it would rank that as routine.
P1_HOUSEHOLDS = 300
P2_HOUSEHOLDS = 150


def priority_for(
    fault_type: FaultType,
    *,
    households_affected: int,
    severity_score: float = 0.0,
) -> WorkOrderPriority:
    """How urgent this is, in households rather than in model confidence."""
    if fault_type in _NON_SUPPLY_FAULTS:
        # Fix the instrument, but never ahead of a supply outage.
        return WorkOrderPriority.P3
    if households_affected >= P1_HOUSEHOLDS or severity_score >= 0.85:
        return WorkOrderPriority.P1
    if households_affected >= P2_HOUSEHOLDS or severity_score >= 0.6:
        return WorkOrderPriority.P2
    if households_affected > 0:
        return WorkOrderPriority.P3
    return WorkOrderPriority.P4


def sla_hours_for(priority: WorkOrderPriority) -> float:
    return SLA_HOURS[priority]


def sla_deadline(created_at: datetime, priority: WorkOrderPriority) -> datetime:
    return created_at + timedelta(hours=SLA_HOURS[priority])


def role_for(fault_type: FaultType) -> CrewRole:
    return ROLE_FOR_FAULT.get(fault_type, CrewRole.VWSC_SECRETARY)


def escalation_target(level: int) -> CrewRole:
    """Level 1 -> committee, level 2 and beyond -> block engineer."""
    index = min(max(level, 1), len(ESCALATION_LADDER)) - 1
    return ESCALATION_LADDER[index]


def estimated_cost_for(fault_type: FaultType) -> float:
    return ESTIMATED_COST.get(fault_type, ESTIMATED_COST[FaultType.UNKNOWN])


@dataclass(frozen=True)
class SlaState:
    """Where a work order stands against its clock, at one instant."""

    deadline: datetime | None
    breached: bool
    #: Negative until the deadline, positive after it.
    minutes_past_deadline: float | None
    minutes_remaining: float | None

    @property
    def breach_minutes(self) -> float | None:
        """Minutes past the deadline, or None if not breached."""
        if not self.breached or self.minutes_past_deadline is None:
            return None
        return self.minutes_past_deadline


def evaluate_sla(deadline: datetime | None, now: datetime) -> SlaState:
    if deadline is None:
        return SlaState(None, False, None, None)
    delta_minutes = (now - deadline).total_seconds() / 60.0
    return SlaState(
        deadline=deadline,
        breached=delta_minutes > 0,
        minutes_past_deadline=delta_minutes,
        minutes_remaining=-delta_minutes,
    )


def action_summary_for(fault_type: FaultType, asset_code: str | None) -> str:
    """The instruction a field actor reads on Telegram.

    Deliberately imperative and specific to the asset: "check the valve" is not
    an action, "open Valve VLV-01" is.
    """
    asset = asset_code or "the affected asset"
    match fault_type:
        case FaultType.VALVE_CLOSURE:
            return f"Inspect and open valve {asset}."
        case FaultType.PIPELINE_BURST:
            return (
                f"Locate and isolate the burst on the line at {asset}, "
                "then repair and recharge."
            )
        case FaultType.PUMP_FAILURE:
            return f"Inspect pump {asset}: motor, starter and non-return valve."
        case FaultType.POWER_OUTAGE:
            return (
                f"Check the supply feeding {asset} — mains, starter and phase "
                "availability — and raise with the discom if the feeder is out."
            )
        case FaultType.SOURCE_DEPLETION:
            return (
                f"Inspect the source at {asset} and plan alternate supply with "
                "the committee."
            )
        case FaultType.SENSOR_FAULT:
            return (
                f"Service the instrument on {asset}. The network is supplying "
                "normally — do not operate the network on this reading."
            )
        case FaultType.THEFT_OR_UNAUTHORISED_TAPPING:
            return f"Survey the line at {asset} for unauthorised connections."
        case _:
            return (
                f"Inspect {asset} and report findings. The fault could not be "
                "classified with confidence."
            )


__all__ = [
    "ESCALATION_LADDER",
    "ESTIMATED_COST",
    "ROLE_FOR_FAULT",
    "SLA_HOURS",
    "SlaState",
    "action_summary_for",
    "escalation_target",
    "estimated_cost_for",
    "evaluate_sla",
    "priority_for",
    "role_for",
    "sla_deadline",
    "sla_hours_for",
]
