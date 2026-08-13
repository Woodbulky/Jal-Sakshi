"""The agent's approved tool surface.

This module is the boundary. The agent can do exactly what is in this file and
nothing else — there is no SQL tool, no shell, no "run this query". Every
method is typed, scoped to one service area, and returns a schema the rest of
the system already understands.

Two rules are structural rather than advisory:

* **No tool reads `fault_injections`.** That table is the simulator's ground
  truth. A diagnosis tool that could read it would not be a diagnosis tool.
* **No tool closes a work order.** `verify_restoration` returns evidence;
  acting on it belongs to `WorkOrderService`, which will only close out of
  `VERIFYING`. There is deliberately no `close_work_order` here for a model to
  reach for.

Tools that change something write to the decision ledger through
`WorkOrderService`, so the account of what the agent did is a side effect of
doing it rather than something the agent has to remember to record.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.analytics.pipeline import DetectionService
from app.schemas.detection import SensorHealth
from app.schemas.network import Asset, SensorReading
from app.schemas.simulation import FaultType
from app.schemas.workorder import (
    AssetHealth,
    CrewMember,
    CrewRole,
    DecisionEntry,
    SparePart,
    VerificationReport,
    VwscAccount,
    WorkOrder,
)
from app.seed import roster
from app.services.repository import Repository
from app.workorders import policy
from app.workorders.service import WorkOrderService

logger = logging.getLogger(__name__)


class ToolError(RuntimeError):
    """A refusal the agent is expected to handle, not a crash."""


class AgentTools:
    """Everything the orchestrator is allowed to do, and nothing more."""

    def __init__(
        self,
        repository: Repository,
        detection: DetectionService,
        work_orders: WorkOrderService,
        *,
        service_area_id: str = "",
    ) -> None:
        self._repository = repository
        self._detection = detection
        self._work_orders = work_orders
        self._service_area_id = service_area_id

    @property
    def service_area_id(self) -> str:
        return self._service_area_id or self._detection.service_area_id

    async def resolve_service_area_id(self) -> str:
        """The id, loading the topology first if nothing has needed it yet.

        `service_area_id` reads empty until `DetectionService.load()` has run,
        and a tool that silently scoped a budget or a work-order list to an
        empty service area would return "nothing" rather than fail.
        """
        if not self.service_area_id:
            await self._detection.load()
        return self.service_area_id

    # -- observation -------------------------------------------------------
    async def run_detection(self, *, now: datetime | None = None, persist: bool = True):
        """One detection pass. The agent's only route to a fresh diagnosis."""
        return await self._detection.run(now=now, persist=persist)

    async def get_fault_event(self, fault_event_id: str):
        return await self._repository.get_fault_event(fault_event_id)

    async def list_open_work_orders(self, *, limit: int = 20) -> list[WorkOrder]:
        return await self._repository.list_work_orders(
            service_area_id=await self.resolve_service_area_id(),
            open_only=True,
            limit=limit,
        )

    async def get_sensor_window(
        self,
        sensor_ref: str,
        *,
        minutes: float = 60.0,
        now: datetime | None = None,
    ) -> list[SensorReading]:
        """Recent readings for one instrument. The agent's only raw data path."""
        sensor = await self._repository.get_sensor(sensor_ref)
        if sensor is None:
            raise ToolError(f"no sensor '{sensor_ref}'")
        now = now or datetime.now(timezone.utc)
        return await self._repository.list_readings(
            [sensor.id], start=now - timedelta(minutes=minutes), end=now
        )

    async def get_sensor_health(
        self, *, now: datetime | None = None
    ) -> list[SensorHealth]:
        """Guardrail 1: what may be believed, checked before anything is done."""
        return await self._detection.sensor_health(now=now)

    async def get_asset(self, asset_ref: str) -> Asset:
        asset = await self._repository.get_asset(
            asset_ref, await self.resolve_service_area_id()
        )
        if asset is None:
            raise ToolError(f"no asset '{asset_ref}' in this service area")
        return asset

    async def get_asset_health(self, asset_ref: str) -> AssetHealth | None:
        """What this asset has done before. Feeds the repeat-failure warning."""
        asset = await self.get_asset(asset_ref)
        return await self._repository.get_asset_health(asset.id)

    async def get_asset_health_by_id(self, asset_id: str) -> AssetHealth | None:
        """Same, when the id is already in hand and no lookup is needed."""
        return await self._repository.get_asset_health(asset_id)

    # -- resources ---------------------------------------------------------
    def get_roster(self, *, role: CrewRole | None = None) -> list[CrewMember]:
        members = [m for m in roster.ROSTER if m.available]
        if role is not None:
            members = [m for m in members if m.role is role]
        return members

    def find_crew(self, fault_type: FaultType) -> CrewMember | None:
        """Who to send for this fault, by role rather than by name."""
        return roster.crew_for_role(policy.role_for(fault_type))

    async def get_budget(self) -> VwscAccount | None:
        return await self._repository.get_vwsc_account(
            await self.resolve_service_area_id()
        )

    async def check_budget(self, amount: float) -> dict[str, Any]:
        """Whether the agent may commit this spend on its own authority.

        Returns a verdict rather than a boolean so the reason survives into the
        ledger: "over the limit" and "over what is left" are different problems
        with different fixes.
        """
        account = await self.get_budget()
        if account is None:
            return {
                "allowed": False,
                "requires_approval": True,
                "reason": "no VWSC account is configured for this service area",
            }
        over_limit = amount > account.autonomous_approval_limit
        over_budget = amount > account.budget_remaining
        return {
            "allowed": not (over_limit or over_budget),
            "requires_approval": over_limit or over_budget,
            "amount": amount,
            "autonomous_limit": account.autonomous_approval_limit,
            "budget_remaining": account.budget_remaining,
            "reason": (
                "estimate exceeds the remaining budget"
                if over_budget
                else "estimate exceeds the autonomous approval limit"
                if over_limit
                else None
            ),
        }

    def check_spares(self, fault_type: FaultType) -> dict[str, Any]:
        """Whether the store holds what this repair usually needs."""
        wanted = roster.PARTS_FOR_FAULT.get(fault_type, ())
        available: list[SparePart] = []
        missing: list[str] = []
        for code in wanted:
            part = roster.spare(code)
            if part is not None and part.quantity > 0:
                available.append(part)
            else:
                missing.append(code)
        return {
            "fault_type": fault_type.value,
            "required": list(wanted),
            "available": [part.model_dump() for part in available],
            "missing": missing,
            "ready": not missing,
            "note": (
                "procurement needed before the repair can complete"
                if missing
                else None
            ),
        }

    # -- action ------------------------------------------------------------
    async def create_work_order(self, fault_event_id: str, **kwargs: Any) -> WorkOrder:
        event = await self._repository.get_fault_event(fault_event_id)
        if event is None:
            raise ToolError(f"no fault event '{fault_event_id}'")
        return await self._work_orders.open_for_fault(event, **kwargs)

    async def assign_work_order(
        self,
        work_order_ref: str,
        *,
        fault_type: FaultType = FaultType.UNKNOWN,
        role: CrewRole | None = None,
        message: str | None = None,
        now: datetime | None = None,
    ) -> WorkOrder:
        """Dispatch to the roster entry for the role this fault needs.

        `message` is the narrated instruction, which becomes the action line of
        the Telegram message. It is phrasing only — the role, the SLA and the
        priority in that message come from the record, not from the model.
        """
        order = await self._require_order(work_order_ref)
        role = role or policy.role_for(fault_type)
        member = roster.crew_for_role(role)
        updated, _ = await self._work_orders.assign(
            order,
            role=role,
            person=member.name if member else None,
            telegram_chat_id=member.telegram_chat_id if member else None,
            phone=member.phone if member else None,
            fault_type=fault_type,
            message=message,
            now=now,
        )
        return updated

    async def escalate_work_order(
        self, work_order_ref: str, *, reason: str, now: datetime | None = None
    ) -> WorkOrder:
        order = await self._require_order(work_order_ref)
        updated, _ = await self._work_orders.escalate(order, reason=reason, now=now)
        return updated

    async def request_approval(
        self, work_order_ref: str, *, reason: str
    ) -> dict[str, Any]:
        """Hand a spending decision to a human. The agent stops here.

        There is no `grant_approval` on this class on purpose: approving spend
        is not something the agent may do to itself.
        """
        order = await self._require_order(work_order_ref)
        account = await self.get_budget()
        return {
            "work_order": order.wo_code,
            "estimated_cost": order.estimated_cost,
            "reason": reason,
            "approver": account.escalation_contact if account else None,
            "awaiting_human": True,
        }

    async def verify_restoration(
        self,
        work_order_ref: str,
        *,
        fault_type: FaultType = FaultType.UNKNOWN,
        detected_at: datetime | None = None,
        now: datetime | None = None,
    ) -> VerificationReport:
        """Read the sensors and report. Does not itself close anything."""
        order = await self._require_order(work_order_ref)
        _, report = await self._work_orders.verify(
            order, fault_type=fault_type, detected_at=detected_at, now=now
        )
        return report

    # -- accountability ----------------------------------------------------
    async def record_decision(
        self,
        *,
        decision: dict[str, Any],
        work_order_ref: str | None = None,
        fault_event_id: str | None = None,
        evidence: dict[str, Any] | None = None,
        notes: str | None = None,
        tool_called: str | None = None,
        confidence: float | None = None,
        now: datetime | None = None,
    ) -> DecisionEntry:
        """For reasoning worth keeping that no state change would capture."""
        order = (
            await self._repository.get_work_order(work_order_ref)
            if work_order_ref
            else None
        )
        from app.workorders.service import AGENT_ACTOR, AGENT_ROLE  # noqa: PLC0415

        return await self._repository.record_decision(
            DecisionEntry(
                ts=now or datetime.now(timezone.utc),
                actor=AGENT_ACTOR,
                agent_role=AGENT_ROLE,
                work_order_id=order.id if order else None,
                fault_event_id=fault_event_id
                or (order.fault_event_id if order else None),
                decision=decision,
                evidence=evidence or {},
                tool_called=tool_called,
                confidence=confidence,
                notes=notes,
            )
        )

    async def get_decisions(
        self, *, work_order_ref: str | None = None, limit: int = 50
    ) -> list[DecisionEntry]:
        order = (
            await self._repository.get_work_order(work_order_ref)
            if work_order_ref
            else None
        )
        return await self._repository.list_decisions(
            work_order_id=order.id if order else None, limit=limit
        )

    # -- internals ---------------------------------------------------------
    async def _require_order(self, ref: str) -> WorkOrder:
        order = await self._repository.get_work_order(ref)
        if order is None:
            raise ToolError(f"no work order '{ref}'")
        return order


#: The allowlist, named. Anything not here is not a tool the agent has.
TOOL_NAMES: tuple[str, ...] = (
    "get_sensor_window",
    "get_sensor_health",
    "get_asset",
    "get_asset_health",
    "get_roster",
    "find_crew",
    "get_budget",
    "check_budget",
    "check_spares",
    "create_work_order",
    "assign_work_order",
    "escalate_work_order",
    "request_approval",
    "verify_restoration",
    "record_decision",
    "get_decisions",
)

__all__ = ["TOOL_NAMES", "AgentTools", "ToolError"]
