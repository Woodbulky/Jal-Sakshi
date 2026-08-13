"""Work-order API.

Follows `API_CONTRACT.md`. Two things are deliberately absent:

* there is no endpoint that sets `status` to an arbitrary value — every
  transition goes through a named action so the ledger records *why*;
* there is no endpoint that closes a work order. `POST /verify` reads the
  sensors and closes it only if they agree. That is the entire product.

`POST /field-update` is what n8n calls when a field actor replies on Telegram.
It accepts "Fixed" and starts verification; it cannot close anything.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import RepositoryDep, WorkOrderDep
from app.schemas.simulation import FaultType
from app.schemas.workorder import (
    Assignment,
    CrewRole,
    DecisionEntry,
    Escalation,
    VerificationReport,
    WorkOrder,
    WorkOrderStatus,
)
from app.seed import roster
from app.workorders.service import WorkOrderError
from app.workorders.state_machine import InvalidTransition

router = APIRouter(prefix="/work-orders", tags=["work-orders"])


class CreateWorkOrderRequest(BaseModel):
    fault_event_id: str
    asset_code: str | None = None


class AssignRequest(BaseModel):
    role: CrewRole | None = Field(
        default=None, description="Defaults to the role the fault class implies."
    )
    person: str | None = None
    telegram_chat_id: str | None = None
    phone: str | None = None
    fault_type: FaultType = FaultType.UNKNOWN


class EscalateRequest(BaseModel):
    reason: str = "escalated by an operator"


class ApproveRequest(BaseModel):
    approved_by: str = Field(min_length=1, description="A named human, not a role.")


class FieldUpdateRequest(BaseModel):
    """The inbound half of the n8n/Telegram contract."""

    message: str
    sender: str | None = None


class VerifyRequest(BaseModel):
    fault_type: FaultType = FaultType.UNKNOWN
    detected_at: datetime | None = None


class WorkOrderDetail(BaseModel):
    """A work order with everything the console shows beside it."""

    work_order: WorkOrder
    assignments: list[Assignment] = Field(default_factory=list)
    escalations: list[Escalation] = Field(default_factory=list)
    decisions: list[DecisionEntry] = Field(default_factory=list)


def _not_found(ref: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"no work order '{ref}'"
    )


def _bad_request(error: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


async def _require(repository: RepositoryDep, ref: str) -> WorkOrder:
    order = await repository.get_work_order(ref)
    if order is None:
        raise _not_found(ref)
    return order


@router.get("", response_model=list[WorkOrder])
async def list_work_orders(
    repository: RepositoryDep,
    service_area_id: str | None = None,
    status_filter: WorkOrderStatus | None = Query(default=None, alias="status"),
    open_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[WorkOrder]:
    return await repository.list_work_orders(
        service_area_id=service_area_id,
        status=status_filter,
        open_only=open_only,
        limit=limit,
    )


@router.get("/roster", response_model=list[dict])
async def get_roster() -> list[dict]:
    """Who the village can send. Static demo data, not a database table."""
    return [member.model_dump(mode="json") for member in roster.ROSTER]


@router.get("/{work_order_ref}", response_model=WorkOrderDetail)
async def get_work_order(
    work_order_ref: str, repository: RepositoryDep
) -> WorkOrderDetail:
    order = await _require(repository, work_order_ref)
    return WorkOrderDetail(
        work_order=order,
        assignments=await repository.list_assignments(work_order_id=order.id),
        escalations=await repository.list_escalations(work_order_id=order.id),
        decisions=await repository.list_decisions(work_order_id=order.id),
    )


@router.post("", response_model=WorkOrder, status_code=status.HTTP_201_CREATED)
async def create_work_order(
    payload: CreateWorkOrderRequest,
    repository: RepositoryDep,
    service: WorkOrderDep,
) -> WorkOrder:
    event = await repository.get_fault_event(payload.fault_event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no fault event '{payload.fault_event_id}'",
        )
    try:
        return await service.open_for_fault(event, asset_code=payload.asset_code)
    except (WorkOrderError, InvalidTransition) as error:
        raise _bad_request(error) from error


@router.post("/{work_order_ref}/assign", response_model=WorkOrder)
async def assign_work_order(
    work_order_ref: str,
    payload: AssignRequest,
    repository: RepositoryDep,
    service: WorkOrderDep,
) -> WorkOrder:
    order = await _require(repository, work_order_ref)
    member = roster.crew_for_role(payload.role) if payload.role else None
    try:
        updated, _ = await service.assign(
            order,
            role=payload.role,
            person=payload.person or (member.name if member else None),
            telegram_chat_id=payload.telegram_chat_id
            or (member.telegram_chat_id if member else None),
            phone=payload.phone or (member.phone if member else None),
            fault_type=payload.fault_type,
        )
    except (WorkOrderError, InvalidTransition) as error:
        raise _bad_request(error) from error
    return updated


@router.post("/{work_order_ref}/approve", response_model=WorkOrder)
async def approve_work_order(
    work_order_ref: str,
    payload: ApproveRequest,
    repository: RepositoryDep,
    service: WorkOrderDep,
) -> WorkOrder:
    """A named human takes responsibility for spend beyond the agent's limit."""
    order = await _require(repository, work_order_ref)
    try:
        return await service.approve(order, approved_by=payload.approved_by)
    except WorkOrderError as error:
        raise _bad_request(error) from error


@router.post("/{work_order_ref}/escalate", response_model=WorkOrder)
async def escalate_work_order(
    work_order_ref: str,
    payload: EscalateRequest,
    repository: RepositoryDep,
    service: WorkOrderDep,
) -> WorkOrder:
    order = await _require(repository, work_order_ref)
    try:
        updated, _ = await service.escalate(order, reason=payload.reason)
    except (WorkOrderError, InvalidTransition) as error:
        raise _bad_request(error) from error
    return updated


@router.post("/{work_order_ref}/acknowledge", response_model=WorkOrder)
async def acknowledge_work_order(
    work_order_ref: str,
    repository: RepositoryDep,
    service: WorkOrderDep,
    by: str | None = None,
) -> WorkOrder:
    order = await _require(repository, work_order_ref)
    try:
        return await service.acknowledge(order, by=by)
    except InvalidTransition as error:
        raise _bad_request(error) from error


@router.post("/{work_order_ref}/field-update", response_model=WorkOrder)
async def field_update(
    work_order_ref: str,
    payload: FieldUpdateRequest,
    repository: RepositoryDep,
    service: WorkOrderDep,
) -> WorkOrder:
    """Inbound from Telegram via n8n.

    A message saying "Fixed" moves the order to RESTORATION_DETECTED, which
    starts sensor verification. It never reaches CLOSED from here.
    """
    order = await _require(repository, work_order_ref)
    try:
        return await service.record_field_update(
            order, message=payload.message, sender=payload.sender
        )
    except InvalidTransition as error:
        raise _bad_request(error) from error


@router.post("/{work_order_ref}/verify", response_model=VerificationReport)
async def verify_work_order(
    work_order_ref: str,
    payload: VerifyRequest,
    repository: RepositoryDep,
    service: WorkOrderDep,
) -> VerificationReport:
    """Read the sensors. The only path to CLOSED in the system."""
    order = await _require(repository, work_order_ref)
    try:
        _, report = await service.verify(
            order, fault_type=payload.fault_type, detected_at=payload.detected_at
        )
    except (WorkOrderError, InvalidTransition) as error:
        raise _bad_request(error) from error
    return report


@router.post("/{work_order_ref}/reopen", response_model=WorkOrder)
async def reopen_work_order(
    work_order_ref: str,
    repository: RepositoryDep,
    service: WorkOrderDep,
    reason: str = "reopened by an operator",
) -> WorkOrder:
    """Send a closed or verifying order back out. Increments `reopen_count`."""
    order = await _require(repository, work_order_ref)
    try:
        return await service.reopen(order, reason=reason, actor="OPERATOR")
    except InvalidTransition as error:
        raise _bad_request(error) from error
