"""Outbound half of the n8n / Telegram contract.

JAL-SAKSHI does not talk to Telegram. It POSTs a signed JSON document to one
n8n webhook, and the workflow behind it decides which chat that becomes. That
seam is the point: the village can move to SMS, to IVR, to WhatsApp, without a
line of this repository changing.

Three properties this module is written to hold:

1. **A send never breaks an incident.** Every failure path returns a recorded
   `Notification`; none raises. A work order that could not be announced is
   still a work order, and the row says so.
2. **Every attempt is evidence.** The notification row is written *before* the
   request goes out and updated after, so a crash mid-send leaves `PENDING`
   rather than nothing.
3. **The receiver can tell it is us.** The body is signed HMAC-SHA256 with
   `N8N_WEBHOOK_SECRET` over the exact bytes sent, so n8n can reject anything
   that is not from this deployment.

With no webhook configured the notifier still composes and records the message
as `SKIPPED`. The demo therefore shows the full Telegram text in the console
whether or not n8n is up, and nothing about the water logic changes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

from app.core.config import Settings
from app.integrations import messages
from app.schemas.notification import (
    Notification,
    NotificationChannel,
    NotificationDirection,
    NotificationEvent,
    NotificationStatus,
    OutboundPayload,
)
from app.schemas.simulation import FaultType
from app.schemas.workorder import WorkOrder
from app.services.repository import Repository

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-JalSakshi-Signature"
EVENT_HEADER = "X-JalSakshi-Event"


def sign(body: bytes, secret: str) -> str:
    """`sha256=<hex>`, over the exact bytes on the wire."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _describe(error: Exception) -> str:
    """A failure reason that is never empty.

    `httpx.ReadTimeout` and its siblings stringify to `''`, so recording
    `str(error)` left the row saying only FAILED — the one case where an
    explanation is most wanted, and the one case there was none. The class name
    is not prose, but "ReadTimeout" tells an operator to look at the network
    rather than at the signature.
    """
    text = str(error).strip()
    name = type(error).__name__
    return (f"{name}: {text}" if text else name)[:500]


def verify_signature(body: bytes, secret: str, presented: str | None) -> bool:
    """Constant-time check used by the inbound callback."""
    if not secret:
        return False
    if not presented:
        return False
    return hmac.compare_digest(sign(body, secret), presented.strip())


class Notifier(Protocol):
    """What `WorkOrderService` is allowed to assume about the outside world."""

    async def notify(
        self,
        event: NotificationEvent,
        order: WorkOrder,
        **context: Any,
    ) -> Notification | None: ...


class N8nNotifier:
    def __init__(
        self,
        repository: Repository,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._settings.n8n_webhook_url)

    async def notify(
        self,
        event: NotificationEvent,
        order: WorkOrder,
        *,
        fault_type: FaultType | None = None,
        asset_code: str | None = None,
        service_area: str | None = None,
        households_affected: int | None = None,
        recipient: str | None = None,
        chat_id: str | None = None,
        action: str | None = None,
        reason: str | None = None,
        ttwr_minutes: float | None = None,
        now: datetime | None = None,
    ) -> Notification | None:
        """Compose, record, and try to deliver. Never raises."""
        now = now or datetime.now(timezone.utc)
        try:
            payload = await self._build(
                event,
                order,
                fault_type=fault_type,
                asset_code=asset_code,
                service_area=service_area,
                households_affected=households_affected,
                recipient=recipient,
                chat_id=chat_id,
                action=action,
                reason=reason,
                ttwr_minutes=ttwr_minutes,
                now=now,
            )
            record = await self._repository.create_notification(
                Notification(
                    work_order_id=order.id or None,
                    channel=NotificationChannel.TELEGRAM,
                    direction=NotificationDirection.OUTBOUND,
                    event=event,
                    recipient=recipient or chat_id,
                    payload=payload.model_dump(mode="json", exclude_none=True),
                    status=NotificationStatus.PENDING,
                    created_at=now,
                )
            )
        except Exception:  # noqa: BLE001 -- recording must not break the incident
            logger.exception("could not record outbound notification for %s", event)
            return None

        if not self.configured:
            logger.info(
                "n8n webhook not configured; %s for %s composed but not sent",
                event.value,
                order.wo_code,
            )
            return await self._settle(
                record, status=NotificationStatus.SKIPPED, error="N8N_WEBHOOK_URL unset"
            )

        return await self._send(record, payload)

    # -- internals ---------------------------------------------------------
    async def _build(
        self,
        event: NotificationEvent,
        order: WorkOrder,
        *,
        fault_type: FaultType | None,
        asset_code: str | None,
        service_area: str | None,
        households_affected: int | None,
        recipient: str | None,
        chat_id: str | None,
        action: str | None,
        reason: str | None,
        ttwr_minutes: float | None,
        now: datetime,
    ) -> OutboundPayload:
        asset_code = asset_code or await self._asset_code(order)
        service_area = service_area or await self._service_area_name(order)
        text = messages.compose(
            event,
            order,
            fault_type=fault_type,
            asset_code=asset_code,
            service_area=service_area,
            households_affected=households_affected,
            assigned_to=recipient,
            action=action,
            reason=reason,
            ttwr_minutes=ttwr_minutes,
        )
        return OutboundPayload(
            event=event,
            # The human code, because this is what a person will quote back on
            # Telegram and what the inbound callback resolves.
            work_order_id=order.wo_code,
            service_area=service_area,
            asset_id=asset_code,
            fault_type=fault_type.value if fault_type else None,
            assigned_to=recipient or order.assigned_person,
            # The recipient's *name* stays the roster's, because the message is
            # still addressed to Ramesh; only the delivery target is redirected.
            chat_id=self._settings.demo_telegram_chat_id or chat_id,
            sla_hours=order.sla_hours,
            households_affected=households_affected,
            priority=order.priority.value,
            action=action or order.action_summary,
            text=text,
            callback_url=self._callback_url(),
            issued_at=now,
        )

    async def _send(
        self, record: Notification, payload: OutboundPayload
    ) -> Notification:
        body = json.dumps(
            payload.model_dump(mode="json", exclude_none=True),
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            EVENT_HEADER: payload.event.value,
        }
        if self._settings.n8n_webhook_secret:
            headers[SIGNATURE_HEADER] = sign(body, self._settings.n8n_webhook_secret)

        try:
            response = await self._post(body, headers)
        except Exception as error:  # noqa: BLE001 -- the network is not our caller
            detail = _describe(error)
            logger.warning(
                "n8n webhook failed for %s: %s", payload.work_order_id, detail
            )
            return await self._settle(
                record, status=NotificationStatus.FAILED, error=detail
            )

        if response.status_code >= 400:
            return await self._settle(
                record,
                status=NotificationStatus.FAILED,
                error=f"n8n returned {response.status_code}: {response.text[:200]}",
            )
        return await self._settle(
            record,
            status=NotificationStatus.SENT,
            external_message_id=_external_id(response),
        )

    async def _post(self, body: bytes, headers: dict[str, str]) -> httpx.Response:
        url = self._settings.n8n_webhook_url
        timeout = self._settings.n8n_timeout_seconds
        if self._client is not None:
            return await self._client.post(url, content=body, headers=headers)
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.post(url, content=body, headers=headers)

    async def _settle(
        self,
        record: Notification,
        *,
        status: NotificationStatus,
        error: str | None = None,
        external_message_id: str | None = None,
    ) -> Notification:
        # The enum, not its value: the in-memory repository copies fields
        # straight onto the model, and PostgREST is handed `.value` anyway.
        fields: dict[str, Any] = {"status": status}
        if status is NotificationStatus.SENT:
            fields["sent_at"] = datetime.now(timezone.utc)
        if error:
            fields["error"] = error
        if external_message_id:
            fields["external_message_id"] = external_message_id
        try:
            updated = await self._repository.update_notification(
                record.id or "", **fields
            )
        except Exception:  # noqa: BLE001
            logger.exception("could not update notification %s", record.id)
            return record
        return updated or record

    async def _asset_code(self, order: WorkOrder) -> str | None:
        if not order.asset_id:
            return None
        try:
            asset = await self._repository.get_asset(order.asset_id)
        except Exception:  # noqa: BLE001
            return None
        return asset.asset_code if asset else None

    async def _service_area_name(self, order: WorkOrder) -> str | None:
        if not order.service_area_id:
            return None
        try:
            area = await self._repository.get_service_area(order.service_area_id)
        except Exception:  # noqa: BLE001
            return None
        return area.name if area else None

    def _callback_url(self) -> str | None:
        base = self._settings.public_base_url.rstrip("/")
        if not base:
            return None
        return f"{base}{self._settings.api_prefix}/integrations/n8n/callback"


def _external_id(response: httpx.Response) -> str | None:
    """Telegram's message id, when the workflow bothers to return it."""
    try:
        data = response.json()
    except Exception:  # noqa: BLE001 -- n8n often answers with a bare "OK"
        return None
    if not isinstance(data, dict):
        return None
    for key in ("message_id", "messageId", "external_message_id"):
        value = data.get(key)
        if value is not None:
            return str(value)
    result = data.get("result")
    if isinstance(result, dict) and result.get("message_id") is not None:
        return str(result["message_id"])
    return None


__all__ = [
    "EVENT_HEADER",
    "N8nNotifier",
    "Notifier",
    "SIGNATURE_HEADER",
    "sign",
    "verify_signature",
]
