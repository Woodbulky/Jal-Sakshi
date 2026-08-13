# JAL-SAKSHI — Full Loop Runbook

One incident from detection to closure. Roughly 12 minutes at the default
settings, 6 if you shorten the verification window first.

- Console: `https://jal-sakshi.vercel.app`
- API: `https://jal-sakshi-api.onrender.com/api/v1` (referred to below as `$API`)
- Telegram: the chat set in `DEMO_TELEGRAM_CHAT_ID`

Every step has a console action and a `curl` equivalent. Use the console when
presenting; use `curl` when rehearsing, because it shows you the state directly.

```bash
API=https://jal-sakshi-api.onrender.com/api/v1
```

---

## Before you present (once)

**Shorten the verification window.** It defaults to 20 minutes, which is dead
air in front of an audience. On Render → Environment:

```
VERIFICATION_WINDOW_MINUTES=3
```

Three minutes is long enough that one lucky sample cannot close an incident —
the property the window exists for — and short enough to watch. Save, let Render
redeploy, and confirm:

```bash
curl -s $API/health
```

**Wake the backend.** On Render's free plan the instance sleeps after 15 minutes
idle, and a sleeping instance is not ticking. Hit the health endpoint a minute
before you start.

---

## Step 0 — Reset to a clean board

```bash
curl -s -X POST $API/simulation/injections/clear-all
```

Console equivalent: **Demo Control → clear all faults.**

Leftover injections from rehearsal are the most common reason a demo behaves
strangely: the network is already faulted before you "inject" anything.

---

## Step 1 — Start the simulator

```bash
curl -s -X POST $API/simulation/start
```

Console: **Demo Control → start.**

Confirm it is actually ticking — this is the single most important check in the
whole runbook:

```bash
curl -s $API/simulation/status
```

Wait ~30 seconds and run it again. `readings_written` must be **increasing** and
`last_tick_at` must be recent. If `running` is false, nothing downstream works:
no telemetry, no detection, no verification, and every work order ends
`UNVERIFIABLE`.

**Say out loud:** seventeen sensors across a seven-asset network are now
reporting. The day-shape they follow was learned from history, not hard-coded.

---

## Step 2 — Inject a fault

```bash
curl -s -X POST $API/simulation/inject \
  -H "Content-Type: application/json" \
  -d '{"fault_type":"VALVE_CLOSURE","asset_id":"VLV-01"}'
```

Console: **Demo Control → inject → Valve Closure → VLV-01.**

`VLV-01` is the Zone A distribution valve, and Zone A serves **212 households** —
so the impact number the agent reports later is real, derived from the network
topology rather than invented.

**Say out loud:** nobody has told the system anything. A valve closed, and the
only trace is in the water.

---

## Step 3 — Watch detection notice

Give it 60–90 seconds (2–3 ticks), then:

```bash
curl -s "$API/detection/anomalies?limit=5"
```

Console: **Incidents** — an anomaly appears, then a classified fault with a
confidence score.

**Say out loud:** tail pressure collapsed while upstream pressure held. That
signature is a closed valve, not a burst — a burst drops both. The classifier
says so with a confidence, and below the threshold it is required to answer
UNKNOWN rather than guess.

---

## Step 4 — The agent decides

**With `AGENT_AUTORUN=true` (the default) there is nothing to do here.** The
loop advances itself every third simulator tick — roughly every 30 seconds —
so over the next minute or two you will watch it classify → assess impact →
open a work order → assign a crew member by skill → dispatch, one step at a
time, without touching anything.

Watch for the work order code (`WO-002` or later) — you need it in step 6.

**When you are presenting and want to control the pace**, set
`AGENT_AUTORUN=false` on Render and drive it yourself:

```bash
curl -s -X POST $API/agent/run | python -m json.tool | head -40
```

Console: **Agent & Comms → run.** Each pass advances the incident by one step,
so run it 3–4 times, pausing to read the trace. It is the same pass the timer
fires — manual mode is not a different code path.

**Say out loud:** every pass is written to an append-only decision ledger —
input, decision, evidence, tool called, state change. The LLM reasons; it never
executes SQL and never authorises a state transition on its own.

---

## Step 5 — The dispatch arrives in Telegram

No command. A message appears by itself:

```
JAL-SAKSHI WORK ORDER
Issue: Valve Closure
Location: Vitpur
Priority: P2
SLA: 4 hours
...
Work Order: WO-002
Assigned to: Ramesh Yadav
```

**Say out loud:** the crew member was chosen by skill match — a valve closure
goes to the valve operator. The village is told in the app they already have.

If nothing arrives within ~15 seconds:

```bash
curl -s "$API/integrations/notifications?limit=3"
```

`SKIPPED` = webhook URL missing. `FAILED` = n8n rejected or timed out; the error
field now names the reason. `SENT` with an `external_message_id` = Telegram
accepted it, so look at the chat id.

---

## Step 6 — Reply as the field crew

In Telegram, **reply to the dispatch** (long-press → Reply) and send `Fixed`.
Or send a plain message `WO-002 Fixed` — the code in the text works too.

A bare "done" with no work-order code is deliberately ignored: the system will
not guess which incident a crew member meant.

The bot answers: *"Received. Sensor verification has started…"*

```bash
curl -s $API/work-orders/WO-002
```

Status: `RESTORATION_DETECTED`.

**Say out loud:** the crew's word moved the work order forward. It did not close
it. Nothing a human types can close an incident in this system.

---

## Step 7 — Verification starts

Automatic: within ~30 seconds the status becomes `VERIFYING`. Console:
**Verification** page shows the window opening and which sensors must agree.
In manual mode, `curl -s -X POST $API/agent/run`.

---

## Step 8 — Choose the ending

### Ending A — the refusal (show this one)

Do nothing — literally nothing. The valve is still closed, so telemetry keeps
reading abnormal, and when the window expires the loop reaches its own verdict:

```bash
curl -s $API/work-orders/WO-002
```

The order **reopens** or reports `UNVERIFIABLE`, and the reopen message lands in
Telegram on its own.

**Say out loud:** a human said it was fixed. The water disagreed. The system
believed the water. That is the entire product.

### Ending B — the clean close

Clear the fault, which is the simulator's "the repair actually happened":

```bash
curl -s -X POST $API/simulation/injections/clear-all
```

Console: **Demo Control → clear.** Telemetry recovers over the next few ticks.
Wait out the window and check:

```bash
curl -s $API/work-orders/WO-002
```

Status: `CLOSED`, with `ttwr_minutes` — time to water restored, measured from
sensor evidence rather than from someone's report.

**This is the moment to point at.** Nobody pressed anything. A human reported a
repair, the sensors were asked to agree, and the incident closed on their
evidence.

**Best sequence if you have the time:** run Ending A, let it reopen, *then*
clear the fault and let it close. Three minutes, and it tells the whole story.

---

## Step 9 — The receipts

```bash
curl -s "$API/agent/decisions?limit=10" | python -m json.tool | head -60
```

Console: **Agent & Comms** — the decision ledger.

**Say out loud:** every decision is reconstructable months later. A village can
ask why a repair was ordered and get an answer with evidence attached.

---

## If something stalls

| Symptom | Cause | Fix |
|---|---|---|
| No anomaly after 2 minutes | Simulator not running | `curl $API/simulation/status` — `readings_written` must be climbing |
| Anomaly but no work order | Autorun is off, or the simulator stopped | Check `AGENT_AUTORUN`; or `POST /agent/run` 3–4 times |
| No Telegram message | n8n down, or the phone is asleep | Check `/integrations/notifications` for the status and error |
| Reply ignored | Not a reply, and no `WO-xxx` in the text | Send `WO-002 Fixed` |
| Verification never resolves | Simulator stopped mid-window | Restart it; the window needs live samples |
| Everything is slow | Render free instance woke from sleep | Hit `/health` a minute before presenting |

**The phone is the server.** n8n, and therefore every Telegram message, dies if
the phone loses power, network, or Termux. Plug it in and keep the screen awake.
