# n8n + Telegram Contract

## Outbound

```text
FastAPI / JAL-SAKSHI
        ↓
n8n webhook
        ↓
Telegram bot
        ↓
Field actor
```

## Inbound

```text
Field actor
    ↓
Telegram
    ↓
n8n Telegram Trigger
    ↓
FastAPI callback
    ↓
Work-order update
```

## Outbound payload

```json
{
  "event": "WORK_ORDER_CREATED",
  "work_order_id": "WO-001",
  "service_area": "Vitpur",
  "asset_id": "VLV-07",
  "fault_type": "VALVE_CLOSURE",
  "assigned_to": "Ramesh",
  "chat_id": "4411",
  "sla_hours": 4,
  "households_affected": 212,
  "priority": "P2",
  "action": "Check and open valve V-07",
  "text": "JAL-SAKSHI WORK ORDER\n\nIssue: Valve Closure\n…",
  "callback_url": "https://<host>/api/v1/integrations/n8n/callback",
  "issued_at": "2026-08-13T05:31:00Z"
}
```

`text` is the finished Telegram message. The workflow sends it; it does not
compose it. Field prose about a commitment is written where it can be tested.

Events: `WORK_ORDER_CREATED`, `WORK_ORDER_ESCALATED`, `WORK_ORDER_CLOSED`,
`WORK_ORDER_REOPENED`, `APPROVAL_REQUIRED`, `VERIFICATION_UNVERIFIABLE`.

### Signing

The body is signed HMAC-SHA256 with `N8N_WEBHOOK_SECRET` over the exact bytes
sent, in `X-JalSakshi-Signature: sha256=<hex>`, with `X-JalSakshi-Event`
alongside it. n8n should reject anything that fails the check.

### When n8n is down

Delivery is not a precondition for anything. Every message is written to
`notifications` before it is attempted and settled afterwards as `SENT`,
`FAILED` or `SKIPPED` (no webhook configured). A work order is still opened,
assigned, verified and closed correctly with the webhook unreachable — the row
records that the village could not be told.

## Inbound payload

```json
{
  "event": "FIELD_UPDATE",
  "work_order_id": "WO-001",
  "sender": "telegram-user",
  "message": "Fixed",
  "chat_id": "4411",
  "external_message_id": "912"
}
```

`POST /api/v1/integrations/n8n/callback`, authenticated with
`INBOUND_CALLBACK_SECRET` — either as `X-JalSakshi-Callback-Secret` or as an
HMAC signature over the body. Unset, the route refuses everything.

A Telegram message saying "Fixed" must never directly close the work order. It
moves it to `RESTORATION_DETECTED`, which starts sensor verification. The
payload has no status field to carry a closure request in, and the response
restates `closed_work_order: false`.

An importable reference workflow is in `jalsakshi/deploy/n8n-workflow.json`.

## Example outbound message

```text
JAL-SAKSHI WORK ORDER

Issue: Valve Closure
Location: Vitpur Zone A
Asset: VLV-07
Affected households: 212
SLA: 4 hours

Action:
Check and open Valve V-07.

Work Order: WO-001
```
