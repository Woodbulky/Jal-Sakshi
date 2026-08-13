# Claude Code Checklist

- [x] FastAPI health endpoint
- [x] Database migrations
- [x] Vitpur seed
- [x] Network API
- [x] Telemetry simulator
- [x] Four fault injectors
- [x] Sensor-failure guardrail
- [x] Anomaly detection
- [x] Fault classifier
- [x] UNKNOWN state
- [x] LangGraph
- [x] Agent tools
- [x] Work-order state machine
- [x] SLA tracking
- [x] Escalation
- [x] Verification
- [x] CLOSED only through verification
- [x] REOPENED / UNVERIFIABLE
- [x] Asset memory
- [x] TTWR
- [x] Decision ledger
- [x] Frontend/backend integration
- [x] n8n outbound
- [x] Telegram inbound
- [x] Realtime events
- [x] Tests
- [x] Docker build  (written; not built here — no Docker daemon on this machine)
- [x] `.env.example`

## Phase 1 notes

Supabase project `Jal-Sakshi` (`zzvldrkswtsbcmbbqbvf`, ap-south-1) holds all 14
tables plus `fault_injections` (simulator ground truth, hidden from the
classifier). A `before update` trigger on `work_orders` rejects any transition
outside the state machine, so `CLOSED` is reachable only from `VERIFYING`.

Backend lives in `jalsakshi/backend`; see `jalsakshi/README.md` to run it.
Tests are offline (`InMemoryRepository` + the Vitpur fixture in
`app/seed/vitpur.py`) and never touch a database.

## Phase 2 notes

The simulator is a hydraulic model, not a script: faults change a physical
input (valve position, leak rate, pump power) and the sensors follow. Signature
table is in `jalsakshi/README.md` — treat it as the contract the classifier is
written against.

Two signatures matter more than they look:

- a closing valve makes upstream pressure **rise**, not fall;
- `PUMP_FAILURE` and `POWER_OUTAGE` are indistinguishable on flow alone and
  separate only on energy and run-hours.

`SENSOR_FAULT` flatlines one instrument with the network healthy — that is the
fixture for the sensor-health guardrail.

Ground truth stays in `fault_injections` and is served only under
`/api/v1/simulation/*`. Verified that `/network`, `/telemetry` and `/readings`
carry no fault label. Nothing in the diagnosis path may call `/simulation/*`.

`LLM_PROVIDER=groq` (OpenAI-wire-compatible, so it goes through
`LLM_BASE_URL`); `LLM_API_KEY` is still blank, which falls back to the
deterministic stub.

## Phase 3 notes

Detection runs on physics, not on mocked scores: every pipeline test injects a
fault into the real hydraulic model, writes readings to the offline repository,
and hands the detector nothing but telemetry. 96 tests green.

Three properties are load-bearing and each has a test that fails without them:

- ground truth never reaches the classifier — checked on all four demo faults;
- a dead instrument produces `SENSOR_FAULT` with 0 households affected, never a
  dispatch;
- with the discriminating channels (pump energy + run-hours) dead, the answer is
  `UNKNOWN` below the 0.55 threshold rather than a coin flip between
  `PUMP_FAILURE` and `POWER_OUTAGE`.

Recovery moves a fault event to `RESTORING`, never to resolved — only
verification may close anything.

The LightGBM seam ships empty by design (rules are auditable and need no
training data). `LIGHTGBM_MODEL_PATH` unset, absent, or unreadable degrades to
rules alone; a loaded model blends at `LIGHTGBM_BLEND_WEIGHT` and stamps
`+lgbm:<model>@<weight>` onto `classifier_version`. The rules keep the veto: a
rule gated out by hydraulics stays out however confident the model is.

Fixed in this phase: `/api/v1/simulation/backfill` returned 422 because
`Request` was never imported, and `from __future__ import annotations` left the
annotation an unresolved string that FastAPI read as a query parameter.

## Phase 4 notes

The accountability half: work orders, dispatch, SLA, escalation, sensor-verified
closure, asset memory and the LangGraph loop. 186 tests green, all offline.

`CLOSED` is reachable only from `VERIFYING`, and that is enforced three times
over — the Postgres trigger, `state_machine.py`, and the absence of any
`close_work_order` tool or `/close` endpoint for a model to reach for.
`test_state_machine.py` asserts the Python table and the trigger agree edge for
edge; a probe against the live database confirmed the trigger rejects
`IN_REPAIR -> CLOSED` and accepts `VERIFYING -> CLOSED`.

Verification returns four first-class outcomes. `PASSED` closes and writes TTWR;
`FAILED` reopens; `PENDING` means the window has not elapsed; `UNVERIFIABLE`
means the instruments that would settle it are untrusted and a human must look.
A Telegram "Fixed" only ever reaches `RESTORATION_DETECTED`.

Deterministic logic stays deterministic. The LLM adapter narrates the field
message and nothing else — fault class, crew, priority, SLA and closure are all
decided by `signatures.py`, `policy.py` and `verification.py`. With
`LLM_PROVIDER=none` the system loses phrasing and keeps every guarantee, so the
stub is the tested default and a failing endpoint degrades to it.

Two bugs the tests caught, both now fixed with a regression test each:

- a `REOPENED` order on a pass where telemetry read clean was abandoned — the
  loop ended, and since the state machine will not verify a `REOPENED` order it
  would have sat open forever with no crew on it;
- re-assessing an already-approved order flipped `requires_approval` back on,
  which would have sent the committee back into a meeting for the same repair.

`vwsc_accounts` in code now mirrors the row seeded in Supabase (₹250,000
allocated, ₹15,000 autonomous limit) so the offline tests and the deployed demo
agree about where the approval boundary sits. Pump work is estimated at ₹18,000
and is therefore the one demo fault that stops for a human.

Vitpur's roster and spares are static demo config in `app/seed/roster.py`, not
tables — `DATA_MODEL.md` lists no crew table and a seven-person village does not
need a workforce system. The store deliberately has no 5HP starter, so a power
fault reports missing spares.

Still open for Phase 5: n8n outbound, Telegram inbound, realtime events, Docker.

## Phase 5 notes

The edges: n8n outbound, Telegram inbound, realtime events, Docker. 240 tests
green, all offline.

The design decision the whole phase turns on is that **messaging is subordinate
to the water logic**. `WorkOrderService` takes a notifier and an event bus as
optional collaborators and guards every call into them, so an n8n outage, a
500, a bug in the notifier or a console that disconnected cannot stop an
incident being opened, assigned, verified or closed. Each of those has a test
that drives a work order to `ASSIGNED` through the failure.

Messages are recorded before they are attempted and settled after as `SENT`,
`FAILED` or `SKIPPED`. `SKIPPED` is not an error state: with `N8N_WEBHOOK_URL`
blank the message is still composed and stored, so the console can show the
village exactly what a field actor would have received, and the demo runs
identically whether or not n8n is up.

The text is composed in `integrations/messages.py`, not in the n8n editor. An
n8n workflow is edited in a browser by someone who is not reading this
repository; handing it finished prose means a change to how Vitpur is addressed
is a code change with a test. The LLM's narration replaces the action sentence
and nothing around it — asset, SLA, priority and work-order code are stated
from the record.

Inbound is one route, `POST /integrations/n8n/callback`, and it is the only way
anything outside the system can move a work order. It requires
`INBOUND_CALLBACK_SECRET` as a shared header or as an HMAC over the body, and
with that unset it answers 503 to everything rather than falling back to open.
Closure is impossible by construction rather than by validation: the payload
has a `message` field and no status field, and the handler calls
`record_field_update`, whose ceiling is `RESTORATION_DETECTED`. There is a
parametrised test that sends "CLOSED", "close the work order" and
"status: CLOSED" and asserts the order does not close.

Realtime is SSE over an in-process bus — not a broker, because one process
serving one village does not need one. Two properties are tested: a console
that stops reading loses its oldest events instead of applying back-pressure to
the agent (bounded per-client queue, `dropped` counted), and a console that
reconnects with `Last-Event-ID` is replayed forward. Payloads are normalised to
JSON at `publish`, not at the transport, because a value that failed to encode
inside an open response would break a live stream mid-incident.

Two things fixed on the way through, both with consequences beyond this phase:

- `SettingsDep` resolved the process-wide `get_settings()` cache, so
  `create_app(settings)` was a lie for any route that read configuration —
  tests were answered from the developer's `.env`. It now reads
  `app.state.settings`. The test fixtures also pass `_env_file=None`, so a
  machine with `N8N_WEBHOOK_URL` set cannot change what the suite asserts;
- escalation called `assign` internally, which would have sent a fresh dispatch
  message on top of the escalation notice. `assign(notify=False)` suppresses it;
  the escalation message names who holds the order now.

Verified live against the Supabase project and a real socket: `verify` on a
work order whose instruments had gone stale returned `UNVERIFIABLE` and the
`VERIFICATION_UNVERIFIABLE` message was recorded; `curl -N .../events/stream`
received the `verification.result` frame with its six checks; an unauthenticated
callback got 401 and an authenticated "Fixed" moved `WO-001` to
`RESTORATION_DETECTED` with `closed_work_order: false`; `verify` then answered
`PENDING` because the 20-minute window had not elapsed. Against a webhook sink
that recomputes the HMAC, the dispatch payload arrived with a valid signature
and the returned Telegram `message_id` was stored on the notification.

Deployment is a single-worker Dockerfile plus `render.yaml`. One worker is
deliberate: the simulator and the realtime bus hold state in memory, so a
second worker would run the hydraulics twice and serve a console half its
events. Scale by service area, not by process.

## Integration notes (build-order step 6)

The console now runs on the API. Every screen reads Supabase through FastAPI;
the only mock left is a small offline fallback in `lib/mock-data.ts` that shows
when the backend cannot be reached, and every screen says which it is showing.

Four layers, and pages touch only the last two:

- `types/backend.ts` mirrors the pydantic schemas exactly (UPPER_SNAKE, UUIDs);
- `lib/api/{client,endpoints}.ts` is one function per route, no transformation;
- `lib/adapters.ts` is the *only* place that converts wire shapes into the
  labels, short refs and IST clock times the console renders;
- `hooks/*` poll and expose view models.

Two endpoints were added because the console needed data with no route to it,
both documented in `shared/API_CONTRACT.md` first:

- `GET /dashboard/summary` — the header tiles in one request instead of six.
  `water_health_score` is a stated penalty sum, not a model output, so it can
  be explained on stage. It falls with untrusted instruments too: a console
  that cannot see the network must not report a healthy one.
- `GET /assets/{ref}/health` and `GET /asset-health` — the asset-memory table
  had no read path at all.

Things the integration deliberately did *not* do:

- no `close` button anywhere. The verification screen calls `POST /verify` and
  renders whichever of the four outcomes comes back, `PENDING` included;
- the demo console shows the injection table and the agent's diagnosis side by
  side, from separate endpoints. Agreement between the two panels is the whole
  claim, and it is only worth something because the classifier cannot read the
  left-hand one;
- `SEVERITY_LABELS`, `WORK_ORDER`, `VERIFICATION_CHECKS`, `ESCALATION_ENTRIES`,
  `VLV07_HEALTH` and the telemetry bands were deleted from the frontend rather
  than kept beside the live data. The seed has seven assets (`VLV-01`,
  `PMP-01`, `OHT-01`, `ZONE-A`…), not the `VLV-07`/`DP-A1` network the mock
  described, and two contradictory sources of truth is worse than one stale
  fallback.

Verified end to end against the live Supabase project: backfill 48 h → inject
`VALVE_CLOSURE` at `VLV-01` → tick → detect → `POST /agent/run` opened `WO-001`
and assigned it; `field-update "Fixed"` moved it to `VERIFYING`; `verify`
returned `PENDING` with six checks because the 20-minute window had not
elapsed — which is the correct answer and is what the console draws.

Frontend reads `NEXT_PUBLIC_API_URL` (`jalsakshi-frontend/.env.local`, default
`http://localhost:8000/api/v1`); the backend already allows
`http://localhost:3000` in `CORS_ORIGINS`. 193 backend tests green.
