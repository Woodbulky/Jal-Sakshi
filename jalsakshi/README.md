# JAL-SAKSHI backend

Agentic rural-water operations layer. Telemetry in, accountable and
sensor-verified restoration out.

## Database

Supabase and only Supabase — no local database, no SQLite fallback. Schema and
seed are applied to the `Jal-Sakshi` project (`zzvldrkswtsbcmbbqbvf`, ap-south-1)
through the Supabase MCP server.

Applied migrations:

| Migration | Contents |
|---|---|
| `jal_sakshi_enums_and_network` | domain enums, `service_areas`, `assets`, `asset_connections`, `sensors` |
| `jal_sakshi_telemetry_and_detection` | `sensor_readings`, `fault_injections`, `anomalies`, `fault_events` |
| `jal_sakshi_work_orders_and_accountability` | `work_orders`, `assignments`, `escalations`, `vwsc_accounts`, `asset_health`, `notifications`, `decision_ledger` |
| `jal_sakshi_work_order_transition_guard` | trigger enforcing the work-order state machine |
| `seed_vitpur_demo_service_area` | the fictional Vitpur demo area |
| `restrict_trigger_function_execute` | revokes RPC access to the trigger functions |

Two guarantees are enforced in the database, not just in application code:

- `fault_injections` holds the simulator's ground truth. The classifier and the
  LLM must never read it.
- `work_orders.status` may only reach `CLOSED` from `VERIFYING`. A Telegram
  "Fixed" message cannot close anything; it starts verification.

RLS is enabled on every table with no policies, so only the service-role key
(server side) can read or write. That is deliberate — the browser never talks
to Postgres directly.

## Configuration

Copy `.env.example` to `.env` and fill in the Supabase values. The service-role
key is not retrievable over MCP: get it from
**Supabase Dashboard → Project Settings → API keys → `service_role`**.

Without it the app still boots, `/api/v1/health` reports `degraded`, and data
endpoints return 503 rather than failing silently.

## Run

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt      # Windows
.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --reload
```

Interactive docs at `/docs` (disabled when `APP_ENV=production`).

## Test

```bash
.venv/Scripts/python -m pytest
```

The suite runs fully offline against `InMemoryRepository`, loaded from the
Vitpur fixture in `app/seed/vitpur.py`, which mirrors the seed migration. No
credentials, no network.

## Endpoints so far

```text
GET /api/v1/health
GET /api/v1/service-areas
GET /api/v1/service-areas/{id}
GET /api/v1/service-areas/{id}/network        nodes + edges + sensors + latest values
GET /api/v1/assets/{asset_id}/telemetry       ?hours=24&limit=2000
GET /api/v1/sensors/{sensor_id}/readings      ?hours=24&limit=1000

GET  /api/v1/simulation/status
POST /api/v1/simulation/start | /pause | /tick
POST /api/v1/simulation/backfill              ?hours=48&step_minutes=5
POST /api/v1/simulation/inject                {"fault_type":..., "asset_id":"VLV-01"}
GET  /api/v1/simulation/injections            ?active_only=true
POST /api/v1/simulation/injections/{id}/clear "Simulate Repair"
POST /api/v1/simulation/injections/clear-all

GET  /api/v1/work-orders                      ?status=&open_only=&limit=
GET  /api/v1/work-orders/roster               Vitpur's crew, from app/seed/roster.py
GET  /api/v1/work-orders/{ref}                order + assignments + escalations + ledger
POST /api/v1/work-orders                      {"fault_event_id": ...}
POST /api/v1/work-orders/{ref}/assign | /approve | /acknowledge | /escalate
POST /api/v1/work-orders/{ref}/field-update   inbound Telegram; "Fixed" != closed
POST /api/v1/work-orders/{ref}/verify         the only route to CLOSED
POST /api/v1/work-orders/{ref}/reopen

POST /api/v1/agent/run                        one pass of the incident loop
GET  /api/v1/agent/decisions                  the decision ledger

GET  /api/v1/integrations/status              is messaging live, or recording?
GET  /api/v1/integrations/notifications       what the village was actually told
POST /api/v1/integrations/n8n/callback        inbound Telegram, via n8n
POST /api/v1/integrations/n8n/resend/{ref}    re-send a dispatch that never arrived

GET  /api/v1/events/stream                    Server-Sent Events
GET  /api/v1/events/recent                    ?limit= — the same events as a list
```

There is no endpoint that sets `status` directly and no `/close`. Every
transition is a named action that writes to the decision ledger, and `CLOSED` is
reachable only from `VERIFYING` — enforced by a Postgres trigger, by
`state_machine.py`, and by the absence of any tool or route that could do it.

Every `{id}` accepts either the UUID or the human code (`demo-vitpur`,
`VLV-01`, `SNS-PMP-01-FLW`), matching the examples in
`shared/API_CONTRACT.md`.

## Layout

```text
backend/app/
├── main.py                     app factory + lifespan
├── core/                       config, logging
├── schemas/                    wire models
├── services/
│   ├── repository.py           protocol the API depends on
│   ├── supabase_repository.py  production implementation
│   └── memory_repository.py    offline test double
├── seed/vitpur.py              demo fixture mirroring the seed migration
├── simulation/
│   ├── model.py                hydraulic model of the Vitpur network
│   ├── faults.py               how a fault deforms that model
│   └── engine.py               ticks the model and persists readings
├── analytics/                  sensor health, baseline, signatures, classifier
├── workorders/
│   ├── state_machine.py        the lifecycle; CLOSED only from VERIFYING
│   ├── policy.py               routing, priority, SLA, escalation ladder
│   ├── verification.py         sensor evidence -> PASSED/FAILED/UNVERIFIABLE
│   ├── memory.py               asset health, MTBF, repeat-failure advice
│   └── service.py              drives transitions and writes the ledger
├── agent/
│   ├── tools.py                the approved tool surface, and nothing else
│   ├── llm.py                  swappable reasoner; stub is the default
│   └── graph.py                LangGraph: observe -> ... -> remember
├── integrations/
│   ├── messages.py             the words a field actor reads, templated
│   ├── n8n.py                  signed outbound webhook; never raises
│   └── events.py               in-process bus behind the SSE stream
└── api/v1/                     health, service_areas, telemetry, detection,
                                incidents, work_orders, agent, simulation,
                                integrations, events
```

The API layer depends on the `Repository` protocol, never on Supabase directly.

## Vitpur

Fictional demo service area, 380 households, 7 assets, 6 topology edges,
17 sensors:

```text
SRC-01 → PMP-01 → OHT-01 ├→ VLV-01 → ZONE-A (212 households)
                         └→ VLV-02 → ZONE-B (168 households)
```

## Simulator

Sensor values are derived, not scripted. Demand follows a diurnal curve, the
pump is level-controlled, pressure falls out of static head minus friction, and
the tank level is integrated between steps. A fault changes a *physical* input
— a valve position, a leak rate, whether the pump is energised — and every
downstream sensor moves with it. That is what makes the telemetry diagnosable
instead of merely labelled.

Measured on the live network (Vitpur, mid-morning demand):

| | pump flow | pump kWh | run-hours | branch flow | tail bar | valve upstream | tank m | NTU |
|---|---|---|---|---|---|---|---|---|
| healthy | 42.3 | 0.234 | — | 23.8 | 1.42 | 1.45 | 3.49 | 1.14 |
| `VALVE_CLOSURE` | 20.0 | 0.191 | — | **0.9** | **0.01** | **1.52 ↑** | 3.51 | 1.08 |
| `PIPELINE_BURST` | **261.4** | 0.619 | — | 18.8 | **0.01** | — | 3.36 ↓ | **7.40** |
| `PUMP_FAILURE` | **0.0** | **0.138** | **counting** | 18.6 | 1.42 | — | 3.36 ↓ | 1.03 |
| `POWER_OUTAGE` | **0.0** | **0.000** | **frozen** | 18.7 | 1.42 | — | 3.36 ↓ | 1.09 |

Two details worth keeping:

- A closing valve makes its *upstream* pressure **rise**, because the friction
  loss disappears with the flow. Detection that only watches for falling
  pressure will miss it.
- `PUMP_FAILURE` and `POWER_OUTAGE` are identical in the flow channel. They
  separate only on energy and the run-hour meter: a failed pump is still
  energised and still counting; a power cut is not. The classifier has to use
  more than flow.

A fifth injection type, `SENSOR_FAULT`, flatlines one instrument while leaving
the network healthy. It exists so the sensor-health guardrail can be tested: no
crew should be dispatched for a fault only a broken sensor reports.

Timestamps are always real wall-clock time, so SLA deadlines and TTWR stay
honest. Only the hydraulic integration and the fault onset run accelerated
(`SIMULATION_TIME_SCALE`, default 30x), which is what lets a six-minute valve
closure develop in twelve seconds of a 90-second demo. Flow and pressure are
algebraic and respond immediately either way.

Before a demo, give detection a baseline:

```bash
curl -X POST 'localhost:8000/api/v1/simulation/backfill?hours=48&step_minutes=5'
curl -X POST 'localhost:8000/api/v1/simulation/start'
```

The backfill is deterministic and upserts on `(sensor_id, ts)`, so re-running it
rewrites the same history rather than duplicating it.

## The agent loop

`POST /api/v1/agent/run` advances one incident by one pass:

```text
observe -> diagnose -> assess -> route -> dispatch -> escalate -> verify -> remember
```

Deterministic logic stays deterministic. The LLM writes the field message and
nothing else: the fault class comes from `analytics/signatures.py`, the crew and
the SLA from `workorders/policy.py`, and closure from `workorders/verification.py`.
With `LLM_PROVIDER=none` the system loses phrasing and keeps every guarantee.

Four guardrails you can watch fire in the demo:

- a dead instrument raises a technician ticket, never a supply crew;
- pump work (₹18,000) exceeds the committee's ₹15,000 autonomous limit and the
  loop stops with `halted` set until a named human approves it;
- a Telegram "Fixed" while the valve is still shut reopens the order;
- if the sensors that would prove restoration are untrusted, the outcome is
  `UNVERIFIABLE` and a human is asked — never an automatic pass.

## Field messaging

JAL-SAKSHI never talks to Telegram. It POSTs one signed JSON document to an n8n
webhook and the workflow decides what that becomes — Telegram today, SMS or IVR
in a village where that works better, with no change here. An importable
reference workflow is in `deploy/n8n-workflow.json`.

Outbound goes out at the moments a person needs to act: dispatch, escalation,
approval needed, closed, reopened, unverifiable. The message text is composed in
`integrations/messages.py`, not by the model and not in the n8n editor — it
states the asset, the SLA and the work-order code, and those are facts about a
commitment. The LLM's narration replaces the action sentence and nothing around
it.

Messaging is subordinate to the water logic, and that is load-bearing:

- every message is recorded in `notifications` *before* it is attempted and
  settled after as `SENT`, `FAILED` or `SKIPPED`;
- with `N8N_WEBHOOK_URL` blank, messages are still composed and stored, so the
  console can show the village exactly what would have been sent;
- an n8n outage, a 500, or a bug in the notifier cannot stop a work order being
  opened, assigned, verified or closed. There is a test for each.

Inbound is `POST /integrations/n8n/callback`, and it is the only route by which
anything outside the system can move a work order. It needs
`INBOUND_CALLBACK_SECRET` (shared header or HMAC over the body) and refuses
everything when that is unset. Its body carries a message and no status, so
"Fixed" — or "CLOSED", or anything else a crew types — reaches
`RESTORATION_DETECTED` and starts sensor verification. Nothing more.

## Realtime

```bash
curl -N http://localhost:8000/api/v1/events/stream
```

Server-Sent Events: `work_order.opened`, `work_order.status` (every transition,
with `previous_status`), `work_order.sla_breached`, `work_order.escalated`,
`verification.result` (all four outcomes), `field.update`, `detection.run`,
`simulation.tick`. Reconnect with `Last-Event-ID` to be replayed from where you
dropped.

The bus is an in-process fan-out with a bounded buffer per client — not a
broker, because one process serving one village does not need one. A console
that stops reading loses its oldest events and is logged as having done so; it
never applies back-pressure to the agent dispatching a crew.

## Deploy

```bash
docker build -t jal-sakshi-api .
docker run -p 8000:8000 --env-file .env jal-sakshi-api
```

`render.yaml` is a Render blueprint for the same image; secrets are `sync:
false` and the two shared secrets are generated by Render. `APP_ENV=production`
turns off `/docs` and `LOG_FORMAT=json` gives structured logs with no request
bodies in them.

One worker, deliberately: the simulator and the realtime bus hold state in
memory, so a second worker would run the hydraulics twice and serve a console
half its events. Scale by service area, not by process.

Migrations and seed data are applied to Supabase through the Supabase MCP
server — there is no local database and no SQLite fallback. A fresh deployment
needs the schema and Vitpur seed applied to its project before
`/api/v1/health` will report anything but `degraded`.
