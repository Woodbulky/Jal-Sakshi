"""Wire schemas for the n8n / Telegram edge.

Every message that leaves the system and every message that comes back is a
row in `notifications`. That is not logging for its own sake: the claim this
product makes is that a village can see who was told what and when, and a
message that was attempted but never delivered is exactly the failure a
committee needs to be able to point at. So a send that fails is recorded
`FAILED` with its error rather than dropped.

The one rule the inbound half exists to preserve: `FieldUpdate` carries a
message, never a status. There is no field on `InboundCallback` that could
name `CLOSED`, so no amount of trust in the sender can turn a Telegram reply
into closure authority.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NotificationChannel(str, Enum):
    TELEGRAM = "TELEGRAM"
    #: The webhook itself, when the transport beyond it is unknown.
    N8N = "N8N"
    SMS = "SMS"
    VOICE = "VOICE"


class NotificationDirection(str, Enum):
    OUTBOUND = "OUTBOUND"
    INBOUND = "INBOUND"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    #: No webhook is configured. The message was composed and recorded but
    #: deliberately not delivered — distinct from a delivery that broke.
    SKIPPED = "SKIPPED"
    RECEIVED = "RECEIVED"


class NotificationEvent(str, Enum):
    """What happened, in the vocabulary the n8n workflow switches on."""

    WORK_ORDER_CREATED = "WORK_ORDER_CREATED"
    WORK_ORDER_ESCALATED = "WORK_ORDER_ESCALATED"
    WORK_ORDER_CLOSED = "WORK_ORDER_CLOSED"
    WORK_ORDER_REOPENED = "WORK_ORDER_REOPENED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    VERIFICATION_UNVERIFIABLE = "VERIFICATION_UNVERIFIABLE"
    #: Inbound.
    FIELD_UPDATE = "FIELD_UPDATE"


class Notification(BaseModel):
    """One message across the n8n edge, in either direction."""

    id: str | None = None
    work_order_id: str | None = None
    channel: NotificationChannel = NotificationChannel.TELEGRAM
    direction: NotificationDirection
    event: NotificationEvent
    recipient: str | None = None
    sender: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    status: NotificationStatus = NotificationStatus.PENDING
    external_message_id: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    sent_at: datetime | None = None


class OutboundPayload(BaseModel):
    """The body POSTed to the n8n webhook.

    Field names are `N8N_TELEGRAM_CONTRACT.md`'s and must stay that way: an
    n8n workflow is edited in a browser by someone who is not reading this
    repository. `text` is the pre-rendered Telegram message so the workflow
    never has to compose Hindi-English field prose out of enum values.
    """

    event: NotificationEvent
    work_order_id: str = Field(description="The human code, 'WO-001', not the UUID.")
    service_area: str | None = None
    asset_id: str | None = None
    fault_type: str | None = None
    assigned_to: str | None = None
    chat_id: str | None = None
    sla_hours: float | None = None
    households_affected: int | None = None
    priority: str | None = None
    action: str | None = None
    text: str = ""
    #: Where n8n sends the field actor's reply back to.
    callback_url: str | None = None
    issued_at: datetime | None = None


class FieldUpdate(BaseModel):
    """The inbound half. A message, and never a status."""

    event: NotificationEvent = NotificationEvent.FIELD_UPDATE
    work_order_id: str
    sender: str | None = None
    message: str
    chat_id: str | None = None
    external_message_id: str | None = None


__all__ = [
    "FieldUpdate",
    "Notification",
    "NotificationChannel",
    "NotificationDirection",
    "NotificationEvent",
    "NotificationStatus",
    "OutboundPayload",
]
