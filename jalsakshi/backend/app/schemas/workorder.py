"""Wire schemas for the accountability half of the system.

A `FaultEvent` is a claim about the network. A `WorkOrder` is a commitment to do
something about it, and everything here exists to keep that commitment
auditable: who was asked, by when, on whose authority, and what evidence closed
it.

Two rules from the agent contract are encoded in the types themselves rather
than left to callers:

* `CLOSED` is reachable only from `VERIFYING` (see `state_machine.py`), so a
  field message saying "fixed" can never be closure authority on its own;
* `UNVERIFIABLE` is a first-class outcome, not an error — when the instruments
  that would prove restoration cannot be trusted, saying so is the honest
  answer.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.simulation import FaultType


class WorkOrderStatus(str, Enum):
    """Mirrors the `work_order_status` enum in Postgres, in lifecycle order."""

    DETECTED = "DETECTED"
    TRIAGING = "TRIAGING"
    CLASSIFIED = "CLASSIFIED"
    ASSESSED = "ASSESSED"
    ASSIGNED = "ASSIGNED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_REPAIR = "IN_REPAIR"
    RESTORATION_DETECTED = "RESTORATION_DETECTED"
    VERIFYING = "VERIFYING"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    UNVERIFIABLE = "UNVERIFIABLE"


class WorkOrderPriority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class CrewRole(str, Enum):
    """Who Vitpur can actually send. Roles, not individuals, own the SLA."""

    PUMP_OPERATOR = "PUMP_OPERATOR"
    LINEMAN = "LINEMAN"
    ELECTRICIAN = "ELECTRICIAN"
    VALVE_OPERATOR = "VALVE_OPERATOR"
    INSTRUMENTATION_TECH = "INSTRUMENTATION_TECH"
    VWSC_SECRETARY = "VWSC_SECRETARY"
    BLOCK_ENGINEER = "BLOCK_ENGINEER"


class WorkOrder(BaseModel):
    """A commitment to restore water, with its clock and its authority."""

    id: str
    wo_code: str
    service_area_id: str
    fault_event_id: str | None = None
    asset_id: str | None = None
    status: WorkOrderStatus = WorkOrderStatus.DETECTED
    priority: WorkOrderPriority = WorkOrderPriority.P3

    assigned_role: CrewRole | None = None
    assigned_person: str | None = None
    action_summary: str | None = None

    sla_hours: float | None = None
    sla_deadline: datetime | None = None
    sla_breached: bool = False

    estimated_cost: float | None = None
    actual_cost: float | None = None
    #: True when the estimate exceeds the VWSC's autonomous approval limit.
    requires_approval: bool = False
    approved_by: str | None = None
    approved_at: datetime | None = None

    acknowledged_at: datetime | None = None
    repair_started_at: datetime | None = None
    restoration_detected_at: datetime | None = None
    verification_started_at: datetime | None = None
    closed_at: datetime | None = None

    reopen_count: int = 0
    verification_result: dict[str, Any] | None = None
    #: Time To Water Restored: detection -> verified restoration, in minutes.
    ttwr_minutes: float | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.status is not WorkOrderStatus.CLOSED

    @property
    def is_dispatched(self) -> bool:
        """Someone has been asked, so the SLA clock is meaningful."""
        return self.assigned_role is not None


class Assignment(BaseModel):
    """One dispatch of one work order to one role. Reassignment adds a row."""

    id: str
    work_order_id: str
    assignee_role: CrewRole
    assignee_name: str | None = None
    telegram_chat_id: str | None = None
    phone: str | None = None
    assigned_at: datetime
    acknowledged_at: datetime | None = None
    released_at: datetime | None = None
    status: str = "ASSIGNED"
    metadata: dict[str, Any] = Field(default_factory=dict)


class Escalation(BaseModel):
    """A commitment that was not met, raised to someone with more authority."""

    id: str
    work_order_id: str
    level: int = 1
    from_role: CrewRole | None = None
    to_role: CrewRole
    reason: str
    triggered_at: datetime
    resolved_at: datetime | None = None
    #: Minutes past the SLA deadline at the moment of escalation.
    sla_breach_minutes: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionEntry(BaseModel):
    """One line of the decision ledger.

    Written for every state change and every consequential tool call, so a
    village committee can ask "why did this happen?" and get an answer that
    does not depend on the model still being available.
    """

    id: str | None = None
    ts: datetime
    actor: str
    agent_role: str | None = None
    work_order_id: str | None = None
    fault_event_id: str | None = None
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    decision: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    tool_called: str | None = None
    state_change: str | None = None
    confidence: float | None = None
    notes: str | None = None


class AssetHealth(BaseModel):
    """What the system remembers about an asset across incidents."""

    id: str | None = None
    asset_id: str
    failure_count: int = 0
    last_failure_at: datetime | None = None
    last_repair_at: datetime | None = None
    #: Mean time between failures, hours. None until a second failure.
    mtbf_hours: float | None = None
    mean_ttwr_minutes: float | None = None
    #: 1.0 is healthy. Falls with failure count and with slow restoration.
    health_score: float = 1.0
    #: Repeated failure means the repair is not the fix; say so instead of
    #: writing the same ticket again.
    recurring_failure: bool = False
    recommendation: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime | None = None


class VwscAccount(BaseModel):
    """The village committee's money and the agent's spending authority."""

    id: str | None = None
    service_area_id: str
    fiscal_year: str
    budget_allocated: float = 0.0
    budget_spent: float = 0.0
    #: Above this, the agent must ask a human before committing spend.
    autonomous_approval_limit: float = 0.0
    escalation_contact: str | None = None
    updated_at: datetime | None = None

    @property
    def budget_remaining(self) -> float:
        return self.budget_allocated - self.budget_spent


class VerificationCheck(BaseModel):
    """One condition from the verification contract, and whether it held."""

    name: str
    passed: bool
    detail: str
    observed: float | None = None
    expected_low: float | None = None
    expected_high: float | None = None


class VerificationOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    #: The instruments that would settle it cannot be trusted.
    UNVERIFIABLE = "UNVERIFIABLE"
    #: Not enough time has elapsed since restoration to be sure.
    PENDING = "PENDING"


class VerificationReport(BaseModel):
    """Sensor evidence weighed against the verification conditions.

    This — not a human message — is what may move a work order to CLOSED.
    """

    work_order_id: str
    outcome: VerificationOutcome
    checked_at: datetime
    window_minutes: float
    checks: list[VerificationCheck] = Field(default_factory=list)
    untrusted_sensors: list[str] = Field(default_factory=list)
    summary: str = ""
    ttwr_minutes: float | None = None

    @property
    def may_close(self) -> bool:
        return self.outcome is VerificationOutcome.PASSED


class CrewMember(BaseModel):
    """A roster entry. Static demo data for Vitpur, not a database table."""

    name: str
    role: CrewRole
    phone: str | None = None
    telegram_chat_id: str | None = None
    available: bool = True
    #: Roles this person can escalate to, in order.
    skills: list[FaultType] = Field(default_factory=list)


class SparePart(BaseModel):
    """Stores on hand. A repair that needs a part the store lacks is slower."""

    part_code: str
    name: str
    quantity: int
    unit_cost: float


__all__ = [
    "Assignment",
    "AssetHealth",
    "CrewMember",
    "CrewRole",
    "DecisionEntry",
    "Escalation",
    "SparePart",
    "VerificationCheck",
    "VerificationOutcome",
    "VerificationReport",
    "VwscAccount",
    "WorkOrder",
    "WorkOrderPriority",
    "WorkOrderStatus",
]
