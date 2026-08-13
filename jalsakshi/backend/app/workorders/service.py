"""The work-order lifecycle, driven.

Everything that changes a work order goes through here, for one reason: every
state change must land in the decision ledger with the evidence that caused it.
A method that mutated an order without writing a ledger line would leave a hole
in the account a village committee is entitled to read.

The rules this service exists to enforce, in the order they bite:

1. A crew is never dispatched on a fault that only a broken instrument reports.
2. Spend above the committee's autonomous limit needs a named human first.
3. A missed SLA escalates by itself; nobody has to notice.
4. A field message is an input. `CLOSED` comes only from a passing
   `VerificationReport`, and only out of `VERIFYING`.
5. A verification that cannot be trusted produces `UNVERIFIABLE`, not a pass.

Telling people is a side effect, never a precondition. The notifier and the
realtime bus are optional collaborators and every call into them is guarded:
if n8n is down or no console is connected, the water logic is unchanged and the
notification row records what could not be delivered.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.analytics.pipeline import STATUS_RESOLVED
from app.schemas.detection import Classification, FaultEvent
from app.schemas.notification import NotificationEvent
from app.schemas.simulation import FaultType
from app.schemas.workorder import (
    Assignment,
    CrewRole,
    DecisionEntry,
    Escalation,
    VerificationOutcome,
    VerificationReport,
    WorkOrder,
    WorkOrderPriority,
    WorkOrderStatus,
)
from app.services.repository import Repository
from app.workorders import policy
from app.workorders.memory import AssetMemoryService
from app.workorders.state_machine import assert_transition

logger = logging.getLogger(__name__)

AGENT_ACTOR = "AGENT"
AGENT_ROLE = "jal-sakshi-orchestrator"

#: Field phrases that mean "I am done". They start verification. They do not
#: close anything -- see rule 4 in the module docstring.
_DONE_PHRASES = ("fixed", "done", "repaired", "complete", "restored", "ho gaya")


class WorkOrderError(RuntimeError):
    """A refusal a caller can show a human: no budget, no such order, etc."""


class WorkOrderService:
    def __init__(
        self,
        repository: Repository,
        *,
        verification=None,
        memory: AssetMemoryService | None = None,
        notifier=None,
        events=None,
    ) -> None:
        self._repository = repository
        self._verification = verification
        self._memory = memory or AssetMemoryService(repository)
        self._notifier = notifier
        self._events = events

    # -- opening -----------------------------------------------------------
    async def open_for_fault(
        self,
        event: FaultEvent,
        *,
        classification: Classification | None = None,
        asset_code: str | None = None,
        now: datetime | None = None,
    ) -> WorkOrder:
        """Turn a classified incident into a commitment, or refuse to.

        Guardrail 1 lives here: a `SENSOR_FAULT`, or a classification where
        every anomalous channel came from an untrusted instrument, produces an
        instrument ticket for the technician -- never a supply repair that
        sends a crew into the field for water that is already flowing.
        """
        now = now or datetime.now(timezone.utc)
        existing = await self._repository.list_work_orders(
            fault_event_id=event.id, open_only=True, limit=1
        )
        if existing:
            return existing[0]

        fault_type = event.fault_type
        households = event.households_affected
        sensor_blocked = bool(classification and classification.sensor_health_blocked)
        if sensor_blocked:
            # The network is fine; an instrument is not. Do not let a broken
            # sensor's severity buy a P1 crew.
            households = 0

        priority = policy.priority_for(
            fault_type,
            households_affected=households,
            severity_score=event.severity_score,
        )
        code = await self._repository.next_work_order_code()
        order = await self._repository.create_work_order(
            WorkOrder(
                id="",
                wo_code=code,
                service_area_id=event.service_area_id,
                fault_event_id=event.id,
                asset_id=event.asset_id,
                status=WorkOrderStatus.DETECTED,
                priority=priority,
                sla_hours=policy.sla_hours_for(priority),
                sla_deadline=policy.sla_deadline(now, priority),
                action_summary=policy.action_summary_for(fault_type, asset_code),
                estimated_cost=policy.estimated_cost_for(fault_type),
                created_at=now,
            )
        )
        await self._ledger(
            order,
            state_change=f"-> {WorkOrderStatus.DETECTED.value}",
            decision={
                "opened": order.wo_code,
                "priority": priority.value,
                "fault_type": fault_type.value,
                "households_affected": households,
                "sensor_health_blocked": sensor_blocked,
            },
            evidence=event.evidence,
            confidence=event.confidence,
            fault_event_id=event.id,
            notes=(
                "instrument fault: ticket raised against the sensor, no supply "
                "crew dispatched"
                if sensor_blocked or fault_type is FaultType.SENSOR_FAULT
                else None
            ),
        )
        if event.asset_id:
            await self._memory.record_failure(
                event.asset_id,
                fault_type=fault_type,
                detected_at=event.detected_at,
                work_order_id=order.id,
            )
        await self._publish(
            "work_order.opened",
            work_order_id=order.id,
            wo_code=order.wo_code,
            service_area_id=order.service_area_id,
            asset_id=order.asset_id,
            fault_event_id=event.id,
            fault_type=fault_type.value,
            priority=priority.value,
            households_affected=households,
            sla_hours=order.sla_hours,
            status=order.status.value,
        )
        return order

    async def triage(self, order: WorkOrder, *, note: str | None = None) -> WorkOrder:
        return await self._transition(
            order, WorkOrderStatus.TRIAGING, decision={"triaged": True}, notes=note
        )

    async def classify(
        self, order: WorkOrder, classification: Classification
    ) -> WorkOrder:
        updated = await self._transition(
            order,
            WorkOrderStatus.CLASSIFIED,
            decision={
                "fault_type": classification.fault_type.value,
                "confidence": classification.confidence,
                "summary": classification.summary,
            },
            evidence=classification.evidence,
            confidence=classification.confidence,
        )
        return updated

    # -- assessment and authority ------------------------------------------
    async def assess(
        self,
        order: WorkOrder,
        *,
        estimated_cost: float | None = None,
        now: datetime | None = None,
    ) -> WorkOrder:
        """Price the repair and decide whether the agent may commit it alone.

        Guardrail 3 of the agent contract. Over the limit, or over what is left
        in the budget, the order is flagged `requires_approval` and stops at
        ASSESSED until a named human approves it.
        """
        now = now or datetime.now(timezone.utc)
        cost = estimated_cost if estimated_cost is not None else order.estimated_cost
        account = await self._repository.get_vwsc_account(order.service_area_id)

        limit = account.autonomous_approval_limit if account else 0.0
        remaining = account.budget_remaining if account else 0.0
        over_limit = cost is not None and cost > limit
        over_budget = account is not None and cost is not None and cost > remaining
        # An approval already given stands. Re-assessing a reopened order must
        # not quietly demand the committee approve the same repair twice.
        needs_approval = bool(over_limit or over_budget) and not order.approved_by

        updated = await self._transition(
            order,
            WorkOrderStatus.ASSESSED,
            fields={
                "estimated_cost": cost,
                "requires_approval": needs_approval,
            },
            decision={
                "estimated_cost": cost,
                "autonomous_limit": limit,
                "budget_remaining": remaining,
                "requires_approval": needs_approval,
                "already_approved_by": order.approved_by,
                "reason": _approval_reason(over_limit, over_budget),
            },
            now=now,
        )
        if needs_approval:
            # The committee is asked before anyone is sent, not after. This is
            # the one message that goes out while nothing is happening.
            await self._notify(
                NotificationEvent.APPROVAL_REQUIRED,
                updated,
                recipient=account.escalation_contact if account else None,
                reason=_approval_reason(over_limit, over_budget),
                now=now,
                **await self._incident_context(updated),
            )
        return updated

    async def approve(
        self, order: WorkOrder, *, approved_by: str, now: datetime | None = None
    ) -> WorkOrder:
        """A named human takes responsibility for the spend."""
        now = now or datetime.now(timezone.utc)
        if not approved_by.strip():
            raise WorkOrderError("approval requires a named approver")
        updated = await self._update(
            order, approved_by=approved_by, approved_at=now, requires_approval=False
        )
        await self._ledger(
            updated,
            actor=approved_by,
            state_change=None,
            decision={"approved": True, "estimated_cost": order.estimated_cost},
            notes=f"spend approved by {approved_by}",
            now=now,
        )
        return updated

    # -- dispatch ----------------------------------------------------------
    async def assign(
        self,
        order: WorkOrder,
        *,
        role: CrewRole | None = None,
        person: str | None = None,
        telegram_chat_id: str | None = None,
        phone: str | None = None,
        fault_type: FaultType = FaultType.UNKNOWN,
        message: str | None = None,
        notify: bool = True,
        now: datetime | None = None,
    ) -> tuple[WorkOrder, Assignment]:
        """Commit the order to a crew and tell them.

        `message` is the narrated instruction from the agent's dispatch node,
        when there is one. It replaces the templated action sentence and
        nothing else — the asset, the SLA and the work-order code are stated
        from the record either way.
        """
        now = now or datetime.now(timezone.utc)
        if order.requires_approval and not order.approved_by:
            raise WorkOrderError(
                f"{order.wo_code} needs human approval for "
                f"₹{order.estimated_cost:,.0f} before a crew can be committed"
            )
        role = role or policy.role_for(fault_type)

        # Reassignment: release whoever held it, so the ledger shows a handover
        # rather than two people each believing they own the job.
        for previous in await self._repository.list_assignments(
            work_order_id=order.id, active_only=True
        ):
            await self._repository.update_assignment(
                previous.id, released_at=now, status="RELEASED"
            )

        updated = await self._transition(
            order,
            WorkOrderStatus.ASSIGNED,
            fields={"assigned_role": role, "assigned_person": person},
            decision={
                "assigned_role": role.value,
                "assigned_person": person,
                "sla_deadline": order.sla_deadline.isoformat()
                if order.sla_deadline
                else None,
            },
            now=now,
        )
        assignment = await self._repository.create_assignment(
            Assignment(
                id="",
                work_order_id=order.id,
                assignee_role=role,
                assignee_name=person,
                telegram_chat_id=telegram_chat_id,
                phone=phone,
                assigned_at=now,
            )
        )
        if notify:
            context = await self._incident_context(updated)
            if fault_type is not FaultType.UNKNOWN:
                context["fault_type"] = fault_type
            await self._notify(
                NotificationEvent.WORK_ORDER_CREATED,
                updated,
                recipient=person or role.value,
                chat_id=telegram_chat_id,
                action=message,
                now=now,
                **context,
            )
        return updated, assignment

    async def acknowledge(
        self, order: WorkOrder, *, by: str | None = None, now: datetime | None = None
    ) -> WorkOrder:
        now = now or datetime.now(timezone.utc)
        updated = await self._transition(
            order,
            WorkOrderStatus.ACKNOWLEDGED,
            fields={"acknowledged_at": now},
            decision={"acknowledged_by": by or order.assigned_person},
            actor=by or "FIELD",
            now=now,
        )
        for assignment in await self._repository.list_assignments(
            work_order_id=order.id, active_only=True
        ):
            await self._repository.update_assignment(
                assignment.id, acknowledged_at=now, status="ACKNOWLEDGED"
            )
        return updated

    async def start_repair(
        self, order: WorkOrder, *, by: str | None = None, now: datetime | None = None
    ) -> WorkOrder:
        now = now or datetime.now(timezone.utc)
        return await self._transition(
            order,
            WorkOrderStatus.IN_REPAIR,
            fields={"repair_started_at": now},
            decision={"repair_started_by": by or order.assigned_person},
            actor=by or "FIELD",
            now=now,
        )

    # -- field reports -----------------------------------------------------
    async def record_field_update(
        self,
        order: WorkOrder,
        *,
        message: str,
        sender: str | None = None,
        now: datetime | None = None,
    ) -> WorkOrder:
        """A message from the field. Never closure authority.

        "Fixed" moves the order to RESTORATION_DETECTED, which starts sensor
        verification. If the sensors disagree, the order reopens and the crew
        goes back out -- which is the entire point.
        """
        now = now or datetime.now(timezone.utc)
        claims_done = any(phrase in message.lower() for phrase in _DONE_PHRASES)
        await self._publish(
            "field.update",
            work_order_id=order.id,
            wo_code=order.wo_code,
            sender=sender,
            message=message,
            claims_restoration=claims_done,
            closes_work_order=False,
        )

        if not claims_done:
            await self._ledger(
                order,
                actor=sender or "FIELD",
                state_change=None,
                decision={"field_message": message, "claims_restoration": False},
                notes="field update recorded; no state change",
                now=now,
            )
            return order

        # Someone reporting a fix before they ever acknowledged the job still
        # has to pass through ACKNOWLEDGED and IN_REPAIR, so the ledger keeps a
        # coherent story and the state machine is never asked to skip an edge.
        if order.status is WorkOrderStatus.ASSIGNED:
            order = await self.acknowledge(order, by=sender, now=now)
        if order.status is WorkOrderStatus.ACKNOWLEDGED:
            order = await self.start_repair(order, by=sender, now=now)

        updated = await self._transition(
            order,
            WorkOrderStatus.RESTORATION_DETECTED,
            fields={"restoration_detected_at": now},
            decision={
                "field_message": message,
                "claims_restoration": True,
                "closes_work_order": False,
            },
            actor=sender or "FIELD",
            notes=(
                "field actor reports the repair is done; this starts sensor "
                "verification and does not close the work order"
            ),
            now=now,
        )
        return updated

    # -- verification ------------------------------------------------------
    async def begin_verification(
        self, order: WorkOrder, *, now: datetime | None = None
    ) -> WorkOrder:
        now = now or datetime.now(timezone.utc)
        return await self._transition(
            order,
            WorkOrderStatus.VERIFYING,
            fields={"verification_started_at": now},
            decision={"verification_started": True},
            now=now,
        )

    async def verify(
        self,
        order: WorkOrder,
        *,
        fault_type: FaultType = FaultType.UNKNOWN,
        detected_at: datetime | None = None,
        now: datetime | None = None,
    ) -> tuple[WorkOrder, VerificationReport]:
        """Read the sensors and act on what they say.

        This is the only path to CLOSED in the system.
        """
        if self._verification is None:
            raise WorkOrderError("no verification service is configured")
        now = now or datetime.now(timezone.utc)

        if order.status is not WorkOrderStatus.VERIFYING:
            order = await self.begin_verification(order, now=now)

        # Time to water restored is measured from detection, and the work order
        # already knows when its incident was detected. A caller that omits it
        # — the console's verify button does — should still get the number,
        # because a closure with no TTWR is a closure nobody can be held to.
        if detected_at is None:
            detected_at = await self._detected_at(order)

        report = await self._verification.verify(
            order, fault_type=fault_type, detected_at=detected_at, now=now
        )
        return await self.apply_verification(report, order, now=now), report

    async def _resolve_incident(
        self, order: WorkOrder, report: VerificationReport, *, now: datetime
    ) -> None:
        """Close the incident behind a closed work order.

        `analytics/pipeline.py` states the rule: detection may move a fault
        event to RESTORING, and only verification may resolve it. Nothing was
        doing the resolving, so an incident whose repair had been confirmed by
        sensors stayed open forever and the village's incident count only ever
        climbed. Failures here are logged, never raised: the work order is
        already closed on evidence, and bookkeeping must not undo that.
        """
        if not order.fault_event_id:
            return
        try:
            await self._repository.update_fault_event(
                order.fault_event_id,
                status=STATUS_RESOLVED,
                resolved_at=now,
                ttwr_minutes=report.ttwr_minutes,
            )
        except Exception:  # noqa: BLE001 -- the closure stands regardless
            logger.exception(
                "could not resolve fault event %s for %s",
                order.fault_event_id,
                order.wo_code,
            )

    async def _detected_at(self, order: WorkOrder) -> datetime | None:
        """When the incident was detected, not when the ticket was written.

        The fault event is the truth: an operator may open a work order minutes
        after the network went wrong, and TTWR measured from the ticket would
        quietly flatter the system. Falls back to the work order's own creation
        time when there is no linked event.
        """
        if order.fault_event_id:
            try:
                event = await self._repository.get_fault_event(order.fault_event_id)
            except Exception:  # noqa: BLE001 -- a missing event must not block closure
                event = None
            if event is not None and event.detected_at is not None:
                return event.detected_at
        return order.created_at

    async def apply_verification(
        self,
        report: VerificationReport,
        order: WorkOrder,
        *,
        now: datetime | None = None,
    ) -> WorkOrder:
        now = now or datetime.now(timezone.utc)
        evidence = {
            "checks": [check.model_dump() for check in report.checks],
            "untrusted_sensors": report.untrusted_sensors,
        }
        result = report.model_dump(mode="json")
        await self._publish(
            "verification.result",
            work_order_id=order.id,
            wo_code=order.wo_code,
            outcome=report.outcome.value,
            summary=report.summary,
            ttwr_minutes=report.ttwr_minutes,
            untrusted_sensors=report.untrusted_sensors,
            checks=[check.model_dump(mode="json") for check in report.checks],
        )

        match report.outcome:
            case VerificationOutcome.PASSED:
                updated = await self._transition(
                    order,
                    WorkOrderStatus.CLOSED,
                    fields={
                        "closed_at": now,
                        "verification_result": result,
                        "ttwr_minutes": report.ttwr_minutes,
                    },
                    decision={
                        "outcome": report.outcome.value,
                        "ttwr_minutes": report.ttwr_minutes,
                        "summary": report.summary,
                    },
                    evidence=evidence,
                    notes="closed on sensor evidence",
                    now=now,
                )
                if updated.asset_id and report.ttwr_minutes is not None:
                    await self._memory.record_restoration(
                        updated.asset_id,
                        ttwr_minutes=report.ttwr_minutes,
                        restored_at=now,
                        work_order_id=updated.id,
                    )
                await self._resolve_escalations(updated, now=now)
                await self._resolve_incident(updated, report, now=now)
                await self._notify(
                    NotificationEvent.WORK_ORDER_CLOSED,
                    updated,
                    recipient=updated.assigned_person,
                    ttwr_minutes=report.ttwr_minutes,
                    now=now,
                    **await self._incident_context(updated),
                )
                return updated

            case VerificationOutcome.FAILED:
                updated = await self._transition(
                    order,
                    WorkOrderStatus.REOPENED,
                    fields={"verification_result": result},
                    decision={
                        "outcome": report.outcome.value,
                        "summary": report.summary,
                    },
                    evidence=evidence,
                    notes=(
                        "telemetry does not confirm restoration; the work order "
                        "reopens rather than closing on the field report"
                    ),
                    now=now,
                )
                # The crew is told the sensors disagreed. Being sent back is
                # the whole difference between this and a ticketing system.
                await self._notify(
                    NotificationEvent.WORK_ORDER_REOPENED,
                    updated,
                    recipient=updated.assigned_person,
                    reason=report.summary,
                    now=now,
                    **await self._incident_context(updated),
                )
                return updated

            case VerificationOutcome.UNVERIFIABLE:
                updated = await self._transition(
                    order,
                    WorkOrderStatus.UNVERIFIABLE,
                    fields={"verification_result": result},
                    decision={
                        "outcome": report.outcome.value,
                        "summary": report.summary,
                    },
                    evidence=evidence,
                    notes="instruments cannot confirm restoration; needs a human",
                    now=now,
                )
                await self._notify(
                    NotificationEvent.VERIFICATION_UNVERIFIABLE,
                    updated,
                    recipient=updated.assigned_person,
                    reason=report.summary,
                    now=now,
                    **await self._incident_context(updated),
                )
                return updated

            case _:  # PENDING
                await self._ledger(
                    order,
                    state_change=None,
                    decision={
                        "outcome": report.outcome.value,
                        "summary": report.summary,
                    },
                    evidence=evidence,
                    notes="verification window not yet satisfied",
                    now=now,
                )
                return order

    async def reopen(
        self,
        order: WorkOrder,
        *,
        reason: str,
        actor: str = AGENT_ACTOR,
        now: datetime | None = None,
    ) -> WorkOrder:
        """Send an order back out. `reopen_count` increments on the write.

        Legal from VERIFYING and from CLOSED — a village whose water fails
        again an hour after closure needs the same incident reopened, not a
        fresh one that loses the history.
        """
        return await self._transition(
            order,
            WorkOrderStatus.REOPENED,
            decision={"reopened": True, "reason": reason},
            actor=actor,
            notes=reason,
            now=now,
        )

    # -- SLA and escalation ------------------------------------------------
    async def check_sla(
        self, order: WorkOrder, *, now: datetime | None = None
    ) -> WorkOrder:
        """Mark a breach. Escalation is a separate, deliberate act."""
        now = now or datetime.now(timezone.utc)
        if not order.is_open or order.sla_deadline is None:
            return order
        state = policy.evaluate_sla(order.sla_deadline, now)
        if not state.breached or order.sla_breached:
            return order
        updated = await self._update(order, sla_breached=True)
        await self._ledger(
            updated,
            state_change=None,
            decision={
                "sla_breached": True,
                "minutes_past_deadline": round(state.minutes_past_deadline or 0.0, 1),
                "priority": order.priority.value,
            },
            notes=f"{order.wo_code} passed its {order.sla_hours:.0f}h SLA",
            now=now,
        )
        await self._publish(
            "work_order.sla_breached",
            work_order_id=updated.id,
            wo_code=updated.wo_code,
            priority=updated.priority.value,
            minutes_past_deadline=round(state.minutes_past_deadline or 0.0, 1),
            status=updated.status.value,
        )
        return updated

    async def escalate(
        self,
        order: WorkOrder,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> tuple[WorkOrder, Escalation]:
        """Raise the order to the next authority, and hand it over."""
        now = now or datetime.now(timezone.utc)
        previous = await self._repository.list_escalations(work_order_id=order.id)
        level = len(previous) + 1
        target = policy.escalation_target(level)
        state = policy.evaluate_sla(order.sla_deadline, now)

        escalation = await self._repository.create_escalation(
            Escalation(
                id="",
                work_order_id=order.id,
                level=level,
                from_role=order.assigned_role,
                to_role=target,
                reason=reason,
                triggered_at=now,
                sla_breach_minutes=state.breach_minutes,
            )
        )
        await self._ledger(
            order,
            state_change=None,
            decision={
                "escalated_to": target.value,
                "level": level,
                "reason": reason,
                "sla_breach_minutes": state.breach_minutes,
            },
            notes=f"{order.wo_code} escalated to {target.value}",
            now=now,
        )

        # An escalated order is handed to the new role, unless it has already
        # moved past the point where a handover means anything.
        updated = order
        if order.status in (
            WorkOrderStatus.ASSIGNED,
            WorkOrderStatus.ACKNOWLEDGED,
            WorkOrderStatus.ASSESSED,
        ):
            # One message, not two: the escalation notice says who holds it
            # now, so the handover does not also send a fresh dispatch.
            updated, _ = await self.assign(order, role=target, notify=False, now=now)
        await self._notify(
            NotificationEvent.WORK_ORDER_ESCALATED,
            updated,
            recipient=updated.assigned_person or target.value,
            reason=reason,
            now=now,
            **await self._incident_context(updated),
        )
        await self._publish(
            "work_order.escalated",
            work_order_id=updated.id,
            wo_code=updated.wo_code,
            level=level,
            to_role=target.value,
            reason=reason,
            sla_breach_minutes=state.breach_minutes,
        )
        return updated, escalation

    async def _resolve_escalations(self, order: WorkOrder, *, now: datetime) -> None:
        """Closing the order settles anything that was raised over it."""
        for escalation in await self._repository.list_escalations(
            work_order_id=order.id, unresolved_only=True
        ):
            await self._repository.update_escalation(escalation.id, resolved_at=now)

    # -- telling people ----------------------------------------------------
    async def _notify(
        self, event: NotificationEvent, order: WorkOrder, **context: Any
    ) -> None:
        """Hand a message to the n8n edge. Failure here is not failure."""
        if self._notifier is None:
            return
        try:
            await self._notifier.notify(event, order, **context)
        except Exception:  # noqa: BLE001 -- an outage must not stall an incident
            logger.exception("notification %s failed for %s", event, order.wo_code)

    async def _publish(self, type: str, **data: Any) -> None:
        if self._events is None:
            return
        try:
            await self._events.publish(type, **data)
        except Exception:  # noqa: BLE001
            logger.exception("could not publish realtime event %s", type)

    async def _incident_context(self, order: WorkOrder) -> dict[str, Any]:
        """The facts a field message states, read from the incident itself.

        Households and fault class live on the fault event, not on the work
        order, and a dispatch message that guessed them would be a dispatch
        message that lied.
        """
        context: dict[str, Any] = {}
        if not order.fault_event_id:
            return context
        try:
            event = await self._repository.get_fault_event(order.fault_event_id)
        except Exception:  # noqa: BLE001
            return context
        if event is None:
            return context
        context["fault_type"] = event.fault_type
        context["households_affected"] = event.households_affected
        return context

    # -- plumbing ----------------------------------------------------------
    async def _transition(
        self,
        order: WorkOrder,
        status: WorkOrderStatus,
        *,
        fields: dict[str, Any] | None = None,
        decision: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        actor: str = AGENT_ACTOR,
        confidence: float | None = None,
        notes: str | None = None,
        now: datetime | None = None,
    ) -> WorkOrder:
        assert_transition(order.status, status, order.wo_code)
        updated = await self._update(order, status=status, **(fields or {}))
        await self._ledger(
            updated,
            actor=actor,
            state_change=f"{order.status.value} -> {status.value}",
            decision=decision,
            evidence=evidence,
            confidence=confidence,
            notes=notes,
            now=now,
        )
        # One realtime event per state change, from the single place every
        # state change goes through. A console never has to poll to learn that
        # an incident moved.
        await self._publish(
            "work_order.status",
            work_order_id=updated.id,
            wo_code=updated.wo_code,
            service_area_id=updated.service_area_id,
            asset_id=updated.asset_id,
            fault_event_id=updated.fault_event_id,
            previous_status=order.status.value,
            status=status.value,
            priority=updated.priority.value,
            assigned_role=updated.assigned_role.value
            if updated.assigned_role
            else None,
            assigned_person=updated.assigned_person,
            sla_breached=updated.sla_breached,
            actor=actor,
            notes=notes,
        )
        return updated

    async def _update(self, order: WorkOrder, **fields: Any) -> WorkOrder:
        updated = await self._repository.update_work_order(order.id, **fields)
        if updated is None:
            raise WorkOrderError(f"work order {order.wo_code} disappeared mid-update")
        return updated

    async def _ledger(
        self,
        order: WorkOrder,
        *,
        state_change: str | None,
        decision: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        actor: str = AGENT_ACTOR,
        confidence: float | None = None,
        notes: str | None = None,
        fault_event_id: str | None = None,
        tool_called: str | None = None,
        now: datetime | None = None,
    ) -> DecisionEntry:
        return await self._repository.record_decision(
            DecisionEntry(
                ts=now or datetime.now(timezone.utc),
                actor=actor,
                agent_role=AGENT_ROLE if actor == AGENT_ACTOR else None,
                work_order_id=order.id,
                fault_event_id=fault_event_id or order.fault_event_id,
                input_snapshot={
                    "wo_code": order.wo_code,
                    "status": order.status.value,
                    "priority": order.priority.value,
                    "assigned_role": order.assigned_role.value
                    if order.assigned_role
                    else None,
                },
                decision=decision or {},
                evidence=evidence or {},
                tool_called=tool_called,
                state_change=state_change,
                confidence=confidence,
                notes=notes,
            )
        )


def _approval_reason(over_limit: bool, over_budget: bool) -> str | None:
    if over_budget:
        return "estimate exceeds the remaining budget"
    if over_limit:
        return "estimate exceeds the autonomous approval limit"
    return None


__all__ = ["AGENT_ACTOR", "AGENT_ROLE", "WorkOrderError", "WorkOrderService"]
