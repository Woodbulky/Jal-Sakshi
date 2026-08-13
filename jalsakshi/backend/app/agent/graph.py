"""LangGraph orchestration: observe, diagnose, assess, route, dispatch,
escalate, verify, remember.

LangGraph is used here for control, not for autonomy. The graph is a fixed set
of nodes with explicit edges; there is no node that lets a model decide what to
do next. Each node calls deterministic services and records what happened, and
the only place a model is consulted at all is `dispatch`, to phrase the message
a human will read.

Why a graph and not a function: the loop has to be re-enterable. A real
incident is not one pass — it is detect now, dispatch in a minute, escalate in
four hours, verify tomorrow morning. Every run starts at `observe`, works out
where the incident already stands, and does the next right thing.

    observe ─┬─ nothing wrong ──────────────────────────────► END
             ├─ awaiting verification ─► verify ──► remember ► END
             └─ new or unhandled fault ► diagnose ► assess ─┬► remember (needs
                                                            │   approval)
                                                            └► route ► dispatch
                                                                     ├► escalate
                                                                     └► remember
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.llm import Reasoner, StubReasoner
from app.agent.tools import AgentTools
from app.schemas.detection import Classification, DetectionRun, FaultEvent
from app.schemas.simulation import FaultType
from app.schemas.workorder import (
    VerificationReport,
    WorkOrder,
    WorkOrderStatus,
)
from app.workorders import policy
from app.workorders.service import WorkOrderError, WorkOrderService

logger = logging.getLogger(__name__)

#: Statuses that mean "the field has reported in; the sensors get a say now".
_AWAITING_VERIFICATION = frozenset(
    {WorkOrderStatus.RESTORATION_DETECTED, WorkOrderStatus.VERIFYING}
)
#: Statuses where the order is already someone's problem and the agent should
#: only be watching the clock.
_IN_FLIGHT = frozenset(
    {
        WorkOrderStatus.ASSIGNED,
        WorkOrderStatus.ACKNOWLEDGED,
        WorkOrderStatus.IN_REPAIR,
    }
)
#: Statuses where nobody currently holds the order and somebody must, whether
#: or not this pass sees fresh anomalies.
_NEEDS_REDISPATCH = frozenset({WorkOrderStatus.REOPENED})


class AgentState(TypedDict, total=False):
    """What one pass of the loop carries.

    Deliberately concrete types rather than a free-form scratchpad: a state a
    model can write arbitrary keys into is a state nobody can audit.
    """

    now: datetime
    service_area_id: str

    detection: DetectionRun | None
    classification: Classification | None
    fault_event: FaultEvent | None
    work_order: WorkOrder | None
    verification: VerificationReport | None

    #: What the agent did this pass, in order, for the console and the tests.
    trace: list[dict[str, Any]]
    #: Set when a node deliberately stops the pass.
    halted: str | None
    message: str | None


class AgentRunner:
    """Builds and runs the graph. One instance per service area is fine."""

    def __init__(
        self,
        tools: AgentTools,
        work_orders: WorkOrderService,
        *,
        reasoner: Reasoner | None = None,
    ) -> None:
        self._tools = tools
        self._work_orders = work_orders
        self._reasoner = reasoner or StubReasoner()
        self._graph = self._build()

    # -- graph -------------------------------------------------------------
    def _build(self):
        graph = StateGraph(AgentState)
        graph.add_node("observe", self._observe)
        graph.add_node("diagnose", self._diagnose)
        graph.add_node("assess", self._assess)
        graph.add_node("route", self._route)
        graph.add_node("dispatch", self._dispatch)
        graph.add_node("escalate", self._escalate)
        graph.add_node("verify", self._verify)
        graph.add_node("remember", self._remember)

        graph.add_edge(START, "observe")
        graph.add_conditional_edges(
            "observe",
            self._after_observe,
            {
                "diagnose": "diagnose",
                "verify": "verify",
                "escalate": "escalate",
                "end": END,
            },
        )
        graph.add_edge("diagnose", "assess")
        graph.add_conditional_edges(
            "assess",
            self._after_assess,
            {"route": "route", "remember": "remember"},
        )
        graph.add_edge("route", "dispatch")
        graph.add_conditional_edges(
            "dispatch",
            self._after_dispatch,
            {"escalate": "escalate", "remember": "remember"},
        )
        graph.add_edge("escalate", "remember")
        graph.add_edge("verify", "remember")
        graph.add_edge("remember", END)
        return graph.compile()

    async def run(self, *, now: datetime | None = None) -> AgentState:
        state: AgentState = {
            "now": now or datetime.now(timezone.utc),
            "service_area_id": self._tools.service_area_id,
            "trace": [],
            "halted": None,
        }
        return await self._graph.ainvoke(state)

    # -- nodes -------------------------------------------------------------
    async def _observe(self, state: AgentState) -> AgentState:
        """Look at the network and at what is already in flight.

        Detection persists here — this is the one place in the loop that is
        allowed to open a fault event, because it is the only place looking at
        telemetry rather than at its own earlier conclusions.
        """
        now = state["now"]
        run = await self._tools.run_detection(now=now)
        open_orders = await self._tools.list_open_work_orders(limit=20)
        # An order the field has reported on takes precedence: somebody is
        # standing at the asset waiting to be told whether they can leave.
        awaiting = [o for o in open_orders if o.status in _AWAITING_VERIFICATION]
        current = awaiting[0] if awaiting else (open_orders[0] if open_orders else None)

        # The SLA clock runs whether or not anything else happens this pass.
        if current is not None:
            current = await self._work_orders.check_sla(current, now=now)

        return {
            **state,
            "detection": run,
            "classification": run.classification,
            "fault_event": run.fault_event,
            "work_order": current,
            "trace": [
                *state["trace"],
                _step(
                    "observe",
                    anomalies=len(run.anomalies),
                    untrusted_sensors=run.untrusted_sensors,
                    fault_type=run.classification.fault_type.value
                    if run.classification
                    else None,
                    open_work_orders=len(open_orders),
                ),
            ],
        }

    def _after_observe(self, state: AgentState) -> str:
        order = state.get("work_order")
        if order is not None and order.status in _AWAITING_VERIFICATION:
            return "verify"
        if order is not None and order.sla_breached and order.status in _IN_FLIGHT:
            return "escalate"
        if order is not None and order.status in _IN_FLIGHT:
            # Someone already has it and the clock has not run out. Nothing
            # useful to add by re-diagnosing the same fault.
            return "end"
        if order is not None and order.status in _NEEDS_REDISPATCH:
            # A verification that failed sends the crew back out. This has to
            # run even when telemetry now reads clean: the state machine will
            # not verify a REOPENED order, so an order left here on a quiet
            # pass would sit open forever with nobody assigned to it.
            return "diagnose"
        if state.get("classification") is None or state.get("fault_event") is None:
            return "end"
        return "diagnose"

    async def _diagnose(self, state: AgentState) -> AgentState:
        """Attach a work order to the incident and record the diagnosis."""
        now = state["now"]
        event = state.get("fault_event")
        classification = state.get("classification")
        order = state.get("work_order")

        if classification is None:
            # Re-dispatching a reopened order on a pass where telemetry reads
            # clean. The original diagnosis still stands -- the fault was real,
            # the repair was not confirmed -- so reuse it rather than inventing
            # a new one from an empty window.
            classification = await self._recover_classification(order)

        asset_code = classification.asset_code if classification else None
        if event is not None and (order is None or order.fault_event_id != event.id):
            order = await self._work_orders.open_for_fault(
                event, classification=classification, asset_code=asset_code, now=now
            )

        if order.status is WorkOrderStatus.DETECTED:
            order = await self._work_orders.triage(order)
        if (
            order.status in (WorkOrderStatus.TRIAGING, WorkOrderStatus.REOPENED)
            and classification is not None
        ):
            order = await self._work_orders.classify(order, classification)

        return {
            **state,
            "work_order": order,
            "classification": classification,
            "trace": [
                *state["trace"],
                _step(
                    "diagnose",
                    work_order=order.wo_code,
                    fault_type=classification.fault_type.value
                    if classification
                    else None,
                    confidence=round(classification.confidence, 3)
                    if classification
                    else None,
                    asset=asset_code,
                    status=order.status.value,
                    reused_diagnosis=state.get("classification") is None,
                ),
            ],
        }

    async def _recover_classification(
        self, order: WorkOrder | None
    ) -> Classification | None:
        """Rebuild the diagnosis a work order was opened on, from its event."""
        if order is None or not order.fault_event_id:
            return None
        event = await self._tools.get_fault_event(order.fault_event_id)
        if event is None:
            return None
        asset = None
        if event.asset_id:
            try:
                asset = await self._tools.get_asset(event.asset_id)
            except Exception:  # noqa: BLE001 -- a missing asset is not fatal here
                asset = None
        return Classification(
            fault_type=event.fault_type,
            confidence=event.confidence,
            asset_id=event.asset_id,
            asset_code=asset.asset_code if asset else None,
            severity_score=event.severity_score,
            households_affected=event.households_affected,
            classifier_version=event.classifier_version or "recovered",
            summary=f"Reusing the diagnosis {order.wo_code} was opened on.",
            evidence=event.evidence,
        )

    async def _assess(self, state: AgentState) -> AgentState:
        """Price it, and find out whether the agent may commit that alone."""
        now = state["now"]
        order = state["work_order"]
        classification = state["classification"]
        fault_type = (
            classification.fault_type if classification else FaultType.UNKNOWN
        )

        cost = policy.estimated_cost_for(fault_type)
        budget = await self._tools.check_budget(cost)
        spares = self._tools.check_spares(fault_type)

        if order.status in (WorkOrderStatus.CLASSIFIED, WorkOrderStatus.REOPENED):
            order = await self._work_orders.assess(order, estimated_cost=cost, now=now)

        return {
            **state,
            "work_order": order,
            "trace": [
                *state["trace"],
                _step(
                    "assess",
                    work_order=order.wo_code,
                    estimated_cost=cost,
                    requires_approval=order.requires_approval,
                    budget_reason=budget.get("reason"),
                    spares_ready=spares["ready"],
                    missing_spares=spares["missing"],
                ),
            ],
        }

    def _after_assess(self, state: AgentState) -> str:
        order = state["work_order"]
        if order.requires_approval and not order.approved_by:
            return "remember"
        return "route"

    async def _route(self, state: AgentState) -> AgentState:
        """Decide who goes. Roles, from the fault class — never from a model."""
        classification = state["classification"]
        fault_type = (
            classification.fault_type if classification else FaultType.UNKNOWN
        )
        role = policy.role_for(fault_type)
        member = self._tools.find_crew(fault_type)
        health = await self._tools.get_asset_health(classification.asset_code) if (
            classification and classification.asset_code
        ) else None

        return {
            **state,
            "trace": [
                *state["trace"],
                _step(
                    "route",
                    role=role.value,
                    crew=member.name if member else None,
                    repeat_failure=bool(health and health.recurring_failure),
                    recommendation=health.recommendation if health else None,
                ),
            ],
        }

    async def _dispatch(self, state: AgentState) -> AgentState:
        """Commit the work order to a crew, and write the message they get."""
        now = state["now"]
        order = state["work_order"]
        classification = state["classification"]
        fault_type = (
            classification.fault_type if classification else FaultType.UNKNOWN
        )

        message = await self._reasoner.narrate(
            {
                "fault_type": fault_type.value,
                "asset_code": classification.asset_code if classification else None,
                "households_affected": classification.households_affected
                if classification
                else 0,
                "action_summary": order.action_summary,
                "sla_hours": order.sla_hours,
                "sensor_health_blocked": bool(
                    classification and classification.sensor_health_blocked
                ),
            }
        )

        try:
            order = await self._tools.assign_work_order(
                order.id, fault_type=fault_type, message=message, now=now
            )
            dispatched = True
            error = None
        except WorkOrderError as err:
            # Refused for a reason worth surfacing (unapproved spend), not a
            # crash. The order stays where it is and a human is asked.
            dispatched = False
            error = str(err)

        return {
            **state,
            "work_order": order,
            "message": message,
            "trace": [
                *state["trace"],
                _step(
                    "dispatch",
                    work_order=order.wo_code,
                    dispatched=dispatched,
                    assigned_role=order.assigned_role.value
                    if order.assigned_role
                    else None,
                    assigned_person=order.assigned_person,
                    message=message,
                    error=error,
                    reasoner=self._reasoner.name,
                ),
            ],
        }

    def _after_dispatch(self, state: AgentState) -> str:
        order = state["work_order"]
        return "escalate" if order.sla_breached else "remember"

    async def _escalate(self, state: AgentState) -> AgentState:
        now = state["now"]
        order = state["work_order"]
        reason = (
            f"SLA of {order.sla_hours:.0f}h passed with the work order in "
            f"{order.status.value}"
            if order.sla_breached
            else "escalated by the operations loop"
        )
        order, escalation = await self._work_orders.escalate(
            order, reason=reason, now=now
        )
        return {
            **state,
            "work_order": order,
            "trace": [
                *state["trace"],
                _step(
                    "escalate",
                    work_order=order.wo_code,
                    level=escalation.level,
                    to_role=escalation.to_role.value,
                    reason=reason,
                    sla_breach_minutes=escalation.sla_breach_minutes,
                ),
            ],
        }

    async def _verify(self, state: AgentState) -> AgentState:
        """The sensors get the last word."""
        now = state["now"]
        order = state["work_order"]
        event = state.get("fault_event")
        fault_type = FaultType.UNKNOWN
        detected_at = None
        if order.fault_event_id:
            stored = await self._tools.get_fault_event(order.fault_event_id)
            if stored is not None:
                fault_type = stored.fault_type
                detected_at = stored.detected_at
        elif event is not None:
            fault_type, detected_at = event.fault_type, event.detected_at

        order, report = await self._work_orders.verify(
            order, fault_type=fault_type, detected_at=detected_at, now=now
        )
        return {
            **state,
            "work_order": order,
            "verification": report,
            "trace": [
                *state["trace"],
                _step(
                    "verify",
                    work_order=order.wo_code,
                    outcome=report.outcome.value,
                    status=order.status.value,
                    ttwr_minutes=report.ttwr_minutes,
                    summary=report.summary,
                    untrusted_sensors=report.untrusted_sensors,
                ),
            ],
        }

    async def _remember(self, state: AgentState) -> AgentState:
        """Close the pass: what was learned, and what a human still owes.

        Asset memory is written by `WorkOrderService` at the moments it can be
        trusted (a confirmed failure, a verified restoration). This node reads
        it back so the pass ends with the long-run picture attached, and stops
        with an explicit reason when one is owed.
        """
        order = state.get("work_order")
        halted = state.get("halted")
        health = None
        if order is not None and order.asset_id:
            health = await self._tools.get_asset_health_by_id(order.asset_id)

        if order is not None and order.requires_approval and not order.approved_by:
            halted = (
                f"{order.wo_code} needs human approval for "
                f"₹{order.estimated_cost:,.0f} before a crew is committed"
            )
        elif (
            order is not None
            and order.status is WorkOrderStatus.UNVERIFIABLE
        ):
            halted = (
                f"{order.wo_code} cannot be verified from telemetry; "
                "a human must inspect"
            )

        return {
            **state,
            "halted": halted,
            "trace": [
                *state["trace"],
                _step(
                    "remember",
                    work_order=order.wo_code if order else None,
                    status=order.status.value if order else None,
                    failure_count=health.failure_count if health else None,
                    health_score=health.health_score if health else None,
                    recurring_failure=bool(health and health.recurring_failure),
                    recommendation=health.recommendation if health else None,
                    halted=halted,
                ),
            ],
        }


def _step(node: str, **fields: Any) -> dict[str, Any]:
    """One trace line. `None` fields are dropped to keep the log readable."""
    return {"node": node, **{k: v for k, v in fields.items() if v is not None}}


__all__ = ["AgentRunner", "AgentState"]
