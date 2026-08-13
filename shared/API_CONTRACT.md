# API Contract

## Service areas

```text
GET  /api/v1/service-areas
GET  /api/v1/service-areas/{service_area_id}
GET  /api/v1/service-areas/{id}/network
```

## Telemetry

```text
GET /api/v1/assets/{asset_id}/telemetry
GET /api/v1/sensors/{sensor_id}/readings
```

## Console summary

```text
GET /api/v1/dashboard/summary   ?hours=
```

One request behind the operations console's header tiles: open incidents by
severity, households affected per zone, open work orders and SLA breaches,
active and mean TTWR, reopen rate, sensor trust, VWSC budget, and a
`water_health_score` that is a stated penalty sum rather than a model output.
It reads `fault_events` and never `fault_injections`.

## Asset health

```text
GET /api/v1/assets/{asset_ref}/health   ?days=
GET /api/v1/asset-health                ?service_area_id=
```

What the system remembers about an asset across incidents — failure count,
MTBF, mean TTWR, and whether repeating the same repair is still the right
answer. The detail response carries the incidents and work orders that produced
the verdict.

## Incidents

```text
GET  /api/v1/incidents
GET  /api/v1/incidents/{incident_id}
POST /api/v1/incidents/{incident_id}/inject-fault
```

## Work orders

```text
GET  /api/v1/work-orders            ?status=&open_only=&service_area_id=&limit=
GET  /api/v1/work-orders/roster
GET  /api/v1/work-orders/{work_order_ref}
POST /api/v1/work-orders
POST /api/v1/work-orders/{work_order_ref}/assign
POST /api/v1/work-orders/{work_order_ref}/approve
POST /api/v1/work-orders/{work_order_ref}/acknowledge
POST /api/v1/work-orders/{work_order_ref}/escalate
POST /api/v1/work-orders/{work_order_ref}/field-update
```

`{work_order_ref}` accepts a UUID or a code (`WO-001`).

`GET /work-orders/{ref}` returns the order together with its assignments,
escalations and decision-ledger entries, so a detail view is one request.

There is deliberately **no** endpoint that sets `status` directly and **no**
`/close`. Every transition is a named action, and the only route to `CLOSED` is
a passing verification.

`POST /field-update` is the inbound half of the n8n/Telegram contract. A message
saying "Fixed" moves the order to `RESTORATION_DETECTED`, which starts sensor
verification. It cannot close anything.

## Verification

```text
POST /api/v1/work-orders/{work_order_ref}/verify
POST /api/v1/work-orders/{work_order_ref}/reopen
```

`verify` returns a `VerificationReport` with one of four outcomes:

```text
PASSED        every applicable check held -> the order is CLOSED, TTWR written
FAILED        telemetry disagrees          -> the order is REOPENED
PENDING       verification window not yet elapsed -> no state change
UNVERIFIABLE  the deciding instruments are untrusted -> a human must inspect
```

The report carries every individual check with its observed value and expected
band, so the console can show *why* an incident closed or did not.

## Agent

```text
POST /api/v1/agent/run
GET  /api/v1/agent/decisions   ?work_order_id=&fault_event_id=&limit=
```

`agent/run` advances the incident loop one pass and returns the node-by-node
trace, the classification, the work order, any verification report, the field
message that was written, and `halted` when the agent is waiting on a human
(for example, spend above the committee's autonomous limit). It is safe to call
on a schedule: an unchanged network produces no new incidents and no second
dispatch.

## Simulation

```text
POST /api/v1/simulation/start
POST /api/v1/simulation/pause
POST /api/v1/simulation/inject
```

Example injection:

```json
{
  "service_area_id": "demo-vitpur",
  "fault_type": "VALVE_CLOSURE",
  "asset_id": "VLV-07"
}
```

## n8n / Telegram

```text
GET  /api/v1/integrations/status
GET  /api/v1/integrations/notifications  ?work_order_ref=&direction=&limit=
POST /api/v1/integrations/n8n/callback
POST /api/v1/integrations/n8n/resend/{work_order_ref}
```

`callback` is the inbound half of `N8N_TELEGRAM_CONTRACT.md` and the only route
by which anything outside the system can move a work order. It requires
`INBOUND_CALLBACK_SECRET`, presented either as `X-JalSakshi-Callback-Secret` or
as an HMAC-SHA256 signature over the body in `X-JalSakshi-Signature`. With no
secret configured it answers 503 to everything — it does not fall back to being
open. Its body has a `message` field and no status field; the response restates
`closed_work_order: false` every time.

`notifications` is the record of what the village was actually told, failures
included (`SENT`, `FAILED`, `SKIPPED`, `RECEIVED`).

Outbound events: `WORK_ORDER_CREATED`, `WORK_ORDER_ESCALATED`,
`WORK_ORDER_CLOSED`, `WORK_ORDER_REOPENED`, `APPROVAL_REQUIRED`,
`VERIFICATION_UNVERIFIABLE`.

## Realtime

```text
GET /api/v1/events/stream    Server-Sent Events
GET /api/v1/events/recent    ?limit=   the same events as a list
```

Event types: `work_order.opened`, `work_order.status`,
`work_order.sla_breached`, `work_order.escalated`, `verification.result`,
`field.update`, `detection.run`, `simulation.tick`.

`work_order.status` fires on every transition and carries `previous_status`.
`verification.result` carries all four outcomes, `PENDING` included. Reconnect
with `Last-Event-ID` to be replayed from where the connection dropped; the last
`REALTIME_HISTORY` events are retained. A console that stops reading loses its
oldest events rather than applying back-pressure to the incident loop.

Polling remains supported and is still what the console ships with: incidents,
work orders and the summary every 8 s, telemetry every 5 s, the network every
10 s, sensor health every 30 s. `useApiResource` in the frontend is the single
place that owns that and exposes the same interface the stream fills, so moving
a screen onto push does not touch the page.

Breaking API changes must be documented here before frontend integration.
