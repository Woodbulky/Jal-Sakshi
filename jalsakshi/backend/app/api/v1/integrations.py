"""Inbound half of the n8n / Telegram contract, and what was sent.

One route can change a work order from outside the system, and this is it. It
is written to be boring in exactly the ways that matter:

* it authenticates. `INBOUND_CALLBACK_SECRET` must match, by shared header or
  by HMAC over the body. Unset, the route refuses everything — an open
  endpoint that can move a work order is not something to fall back to;
* it cannot close anything. The body has a `message` field and no status
  field, and it calls `record_field_update`, which at its most generous
  reaches `RESTORATION_DETECTED`. "Fixed" starts sensor verification. The
  sensors decide.

`GET /integrations/notifications` is the console's record of what the village
was actually told, including messages that failed to send.
"""

from __future__ import annotations

import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.api.deps import NotifierDep, RepositoryDep, SettingsDep, WorkOrderDep
from app.integrations.n8n import SIGNATURE_HEADER, verify_signature
from app.schemas.notification import (
    FieldUpdate,
    Notification,
    NotificationChannel,
    NotificationDirection,
    NotificationEvent,
    NotificationStatus,
)
from app.schemas.workorder import WorkOrder, WorkOrderStatus
from app.workorders.state_machine import InvalidTransition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])

SECRET_HEADER = "X-JalSakshi-Callback-Secret"


class CallbackAccepted(BaseModel):
    """What n8n gets back. Deliberately states what did *not* happen."""

    accepted: bool = True
    work_order: WorkOrder
    status: WorkOrderStatus
    claims_restoration: bool
    #: Always false. Restated on every response so the workflow author can see
    #: that a field reply is an input to verification, not closure.
    closed_work_order: bool = False
    detail: str


class IntegrationStatus(BaseModel):
    outbound_configured: bool
    inbound_configured: bool
    webhook_host: str | None = None
    callback_url: str | None = None


def _authenticate(request: Request, body: bytes, secret: str) -> None:
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="INBOUND_CALLBACK_SECRET is not set; inbound callbacks are "
            "refused rather than accepted unauthenticated.",
        )
    presented = request.headers.get(SECRET_HEADER)
    if presented and hmac.compare_digest(presented.strip(), secret):
        return
    if verify_signature(body, secret, request.headers.get(SIGNATURE_HEADER)):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="callback rejected: bad or missing shared secret",
    )


@router.get("/status", response_model=IntegrationStatus)
async def integration_status(settings: SettingsDep) -> IntegrationStatus:
    """Whether messaging is live, so the console can say so out loud."""
    host = None
    if settings.n8n_webhook_url:
        # Host only. The webhook path is a credential of sorts.
        parts = settings.n8n_webhook_url.split("/")
        host = parts[2] if len(parts) > 2 else None
    base = settings.public_base_url.rstrip("/")
    return IntegrationStatus(
        outbound_configured=bool(settings.n8n_webhook_url),
        inbound_configured=bool(settings.inbound_callback_secret),
        webhook_host=host,
        callback_url=(
            f"{base}{settings.api_prefix}/integrations/n8n/callback" if base else None
        ),
    )


@router.get("/notifications", response_model=list[Notification])
async def list_notifications(
    repository: RepositoryDep,
    work_order_ref: str | None = None,
    direction: NotificationDirection | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Notification]:
    """Every message across the edge, failures included."""
    work_order_id = None
    if work_order_ref:
        order = await repository.get_work_order(work_order_ref)
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no work order '{work_order_ref}'",
            )
        work_order_id = order.id
    return await repository.list_notifications(
        work_order_id=work_order_id, direction=direction, limit=limit
    )


@router.post("/n8n/callback", response_model=CallbackAccepted)
async def n8n_callback(
    request: Request,
    payload: FieldUpdate,
    settings: SettingsDep,
    repository: RepositoryDep,
    service: WorkOrderDep,
) -> CallbackAccepted:
    """A field actor replied on Telegram; n8n relays it here."""
    body = await request.body()
    _authenticate(request, body, settings.inbound_callback_secret)

    order = await repository.get_work_order(payload.work_order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no work order '{payload.work_order_id}'",
        )

    # Recorded before it is acted on: a message that crashed the handler still
    # has to be visible to whoever asks why nothing happened.
    await repository.create_notification(
        Notification(
            work_order_id=order.id,
            channel=NotificationChannel.TELEGRAM,
            direction=NotificationDirection.INBOUND,
            event=NotificationEvent.FIELD_UPDATE,
            sender=payload.sender,
            recipient=payload.chat_id,
            payload=payload.model_dump(mode="json"),
            status=NotificationStatus.RECEIVED,
            external_message_id=payload.external_message_id,
            created_at=datetime.now(timezone.utc),
        )
    )

    before = order.status
    try:
        updated = await service.record_field_update(
            order, message=payload.message, sender=payload.sender
        )
    except InvalidTransition as error:
        # The order has moved on — already closed, or awaiting a human. Say so
        # with a 409 rather than pretending the message was applied.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error

    claims_restoration = updated.status is not before and (
        updated.status is WorkOrderStatus.RESTORATION_DETECTED
    )
    detail = (
        "restoration reported; sensor verification has started and will decide "
        "whether this work order closes"
        if claims_restoration
        else "message recorded against the work order; no state change"
    )
    return CallbackAccepted(
        work_order=updated,
        status=updated.status,
        claims_restoration=claims_restoration,
        detail=detail,
    )


@router.post("/n8n/resend/{work_order_ref}", response_model=Notification | None)
async def resend_dispatch(
    work_order_ref: str,
    repository: RepositoryDep,
    notifier: NotifierDep,
) -> Notification | None:
    """Re-send the dispatch message for an order a crew says never arrived.

    A resend, not a re-dispatch: nothing about the work order changes, and the
    new attempt is recorded as its own notification row.
    """
    order = await repository.get_work_order(work_order_ref)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no work order '{work_order_ref}'",
        )
    context: dict[str, object] = {}
    if order.fault_event_id:
        event = await repository.get_fault_event(order.fault_event_id)
        if event is not None:
            context = {
                "fault_type": event.fault_type,
                "households_affected": event.households_affected,
            }
    return await notifier.notify(
        NotificationEvent.WORK_ORDER_CREATED,
        order,
        recipient=order.assigned_person,
        **context,
    )
