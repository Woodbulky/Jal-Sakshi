# JAL-SAKSHI — Deployment & Human-Only Tasks

This is the operator's guide. It answers three things:

1. What that n8n workflow is and what you do with it (including the two triggers
   and the red warning triangles in your screenshot).
2. How to deploy the backend on Render and the frontend on Vercel.
3. The list of things **only you can do** — accounts, secrets, and clicks that no
   agent can perform on your behalf.

Current state, verified:

| Piece | Where | Status |
|---|---|---|
| Database | Supabase project `Jal-Sakshi` (`zzvldrkswtsbcmbbqbvf`, ap-south-1) | **Done.** 15 tables, seeded (7 assets, 17 sensors, ~29.5k readings) |
| Backend | `jalsakshi/` — FastAPI + Dockerfile + `render.yaml` | Code ready, **not deployed** |
| Frontend | `jalsakshi-frontend/` — Next.js 16 | Code ready, **not deployed** |
| n8n workflow | `jalsakshi/deploy/n8n-workflow.json` | **Imported by you, not yet configured** |
| Telegram bot | — | **Not created.** Only you can do this |

---

## Part 0 — Read this ordering first

The three services reference each other, so there is no order in which every
value is known up front. Deploy in this sequence and do one short second pass:

```
1. Telegram bot        → gives you a bot token + your chat id
2. Render (backend)    → gives you  https://jal-sakshi-api.onrender.com
3. n8n workflow        → gives you  https://<n8n-host>/webhook/jal-sakshi
4. Vercel (frontend)   → gives you  https://<app>.vercel.app
5. Second pass: paste (3) into Render as N8N_WEBHOOK_URL
                paste (4) into Render as CORS_ORIGINS
                paste (2) into Vercel as NEXT_PUBLIC_API_URL
                paste (2) into n8n  as JAL_SAKSHI_API_URL
```

Everything in step 5 is a copy-paste of a URL you only learn after the thing is
live. Expect one redeploy of Render and one of Vercel after step 5. That is
normal, not a mistake.

---

## Part 1 — What the n8n workflow actually is

n8n is the messaging layer, and **nothing else**. It holds no water logic: it
does not decide who gets sent out, what the SLA is, or whether an incident may
close. All of that lives in FastAPI. n8n only carries text to a human and carries
the human's reply back. If n8n is down the system still works — every message is
written to the `notifications` table with status `SKIPPED`, and the console shows
exactly what the field crew *would* have received.

### The two triggers in your screenshot

They are two independent flows in one workflow. That is by design, not a mistake.

**Top row — outbound (webhook trigger, the lightning bolt on the left):**

```
JAL-SAKSHI webhook → Verify signature → Send to field actor → Return message id
```

The backend POSTs a signed work order to the n8n webhook URL. The Code node
recomputes the HMAC-SHA256 signature and throws if it does not match, so only
your deployment can make this workflow send Telegram messages. The Telegram node
then sends `$json.text` — the message is **already fully written** by the
backend; n8n does not compose it. The last node returns the Telegram
`message_id` to the backend so the notification row can be settled as `SENT`.

**Bottom row — inbound (Telegram trigger):**

```
Field actor replies → Build field update → Tell JAL-SAKSHI → Acknowledge the reply
```

When a crew member replies in Telegram, the Code node extracts the work-order
code (`WO-001`) from the message they replied to, POSTs a `FIELD_UPDATE` to
`/api/v1/integrations/n8n/callback` with the callback secret in a header, and
then sends an acknowledgement back into the chat. If the reply claims the repair
is done, the acknowledgement says sensor verification has started — because the
backend, not the crew, decides whether the incident closes.

### Why the three red ⚠ triangles

They are on `Send to field actor`, `Field actor replies`, and `Acknowledge the
reply` — the three Telegram nodes. The exported JSON has
`"credentials": { "telegramApi": { "id": "REPLACE_ME" } }`, which is a
placeholder. The warning means *"no Telegram credential selected"*. It clears the
moment you create the credential in n8n and pick it in each of the three nodes.
Nothing is broken.

---

## Part 2 — Telegram bot (only you can do this)

1. In Telegram, message **@BotFather** → `/newbot` → give it a name and a
   username ending in `bot`. Copy the token it gives you
   (`8123456789:AAH...`). Treat it like a password.
2. Open a chat with your new bot and send it any message (`hi`). A bot cannot
   message you first.
3. Get your numeric chat id: message **@userinfobot**, or open
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and read
   `message.chat.id`. It looks like `1234567890`.
4. For the demo, create a Telegram **group**, add your bot to it, and use the
   group's chat id (negative, like `-1001234567890`) so the judges can watch the
   conversation happen live. Optional but it demos far better than a DM.

Keep the token and chat id somewhere handy — you need both below.

---

## Part 3 — Deploy the backend on Render

The repo already contains `jalsakshi/Dockerfile` and `jalsakshi/render.yaml`, so
Render needs almost no manual configuration.

### 3a. Push to GitHub first

Render deploys from a Git repo. This folder is not a git repository yet.

```powershell
cd C:\hacking\Jal-sakshi\JAL-SAKSHI_Agent_Handoff
git init
git add .
git commit -m "JAL-SAKSHI: backend, frontend, n8n workflow"
gh repo create jal-sakshi --private --source=. --push
```

**Before committing, confirm `jalsakshi/.env` is ignored** — it holds your
Supabase service-role key. `jalsakshi/.gitignore` already covers it; run
`git status` and make sure `.env` is not in the list. If it is, stop and fix the
ignore file before you commit.

### 3b. Create the service

1. render.com → **New → Blueprint** → connect the repo.
2. Render reads `jalsakshi/render.yaml` and proposes a service called
   `jal-sakshi-api`. If Blueprint does not find it, use **New → Web Service**
   instead with **Root Directory** `jalsakshi`, **Runtime** Docker.
3. Render will prompt for every `sync: false` secret. Fill in:

| Key | Value |
|---|---|
| `SUPABASE_URL` | `https://zzvldrkswtsbcmbbqbvf.supabase.co` |
| `SUPABASE_ANON_KEY` | from Supabase → Project Settings → API |
| `SUPABASE_SERVICE_ROLE_KEY` | same page, the **service_role** key |
| `CORS_ORIGINS` | leave `http://localhost:3000` for now, fix in Part 5 |
| `PUBLIC_BASE_URL` | `https://jal-sakshi-api.onrender.com` (your service URL) |
| `LLM_API_KEY` | your Groq key from console.groq.com (blank = deterministic stub, still demos fine) |
| `N8N_WEBHOOK_URL` | `https://n8n.vaastusolutions.in/webhook/jal-sakshi` |
| `N8N_WEBHOOK_SECRET` | the shared signing secret — same string as in `jalsakshi/.env` |
| `INBOUND_CALLBACK_SECRET` | the shared callback secret — same string as in `jalsakshi/.env` |

   Both secrets are `sync: false`, so Render prompts for them and stores them
   without them ever entering this repository. They are **shared with n8n** —
   paste the identical strings there (Part 5d) or every signature check fails.
   Read the current values from `jalsakshi/.env`, which is gitignored.

4. Deploy. Health check is `/api/v1/health`; Render marks the service live when
   it returns 200.

### Render notes worth knowing

- `render.yaml` sets `plan: starter` (paid, ~$7/mo). The **free** plan sleeps
  after 15 minutes of no traffic — and this backend runs the hydraulic simulator
  in-process, so a sleeping instance stops generating telemetry and your demo
  goes flat. If you use free, hit the URL a minute before you present.
- `numInstances: 1` is deliberate. The simulator and the SSE event bus hold state
  in memory; a second instance would run the simulation twice. Do not scale it.
- Region is `singapore` in the blueprint while Supabase is `ap-south-1` (Mumbai).
  Fine for a demo; change to a closer region if you care about latency.

---

## Part 4 — Deploy the frontend on Vercel

1. vercel.com → **Add New → Project** → import the same GitHub repo.
2. **Root Directory: `jalsakshi-frontend`** — this is the one setting people get
   wrong. Vercel autodetects Next.js after that; leave build and output alone.
3. Environment Variables → add:

   | Key | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | `https://jal-sakshi-api.onrender.com/api/v1` |

   Note the `/api/v1` suffix — it is part of the value, matching `.env.local`.
   `NEXT_PUBLIC_*` is baked in at build time, so **changing it later requires a
   redeploy**, not just a restart.
4. Deploy. Copy the resulting `https://<something>.vercel.app` URL.

---

## Part 5 — Import and configure the n8n workflow

### 5a. Where to run n8n

Pick one:

- **n8n Cloud** (easiest, free trial) — hosted, public HTTPS out of the box.
- **Self-hosted** (`npx n8n` or Docker) — free, but the Telegram trigger needs a
  **public HTTPS URL** to receive updates. On localhost you must run
  `n8n start --tunnel` or put it behind ngrok/Cloudflare Tunnel, and set
  `WEBHOOK_URL` to that public address. Without this the bottom flow will never
  fire.

### 5b. Import

n8n → **Workflows → Import from File** → choose
`jalsakshi/deploy/n8n-workflow.json`. You get exactly the canvas in your
screenshot.

### 5c. Create the Telegram credential (clears the ⚠ triangles)

Credentials → **New → Telegram API** → paste your BotFather token → save as
"JAL-SAKSHI bot". Then open each of the three Telegram nodes and select that
credential from the dropdown. All three warnings disappear.

### 5d. Set the four values the workflow expects

The nodes reference `$env.*`:

| Name | Value |
|---|---|
| `JAL_SAKSHI_WEBHOOK_SECRET` | same string as `N8N_WEBHOOK_SECRET` in `jalsakshi/.env` |
| `JAL_SAKSHI_CALLBACK_SECRET` | same string as `INBOUND_CALLBACK_SECRET` in `jalsakshi/.env` |
| `JAL_SAKSHI_API_URL` | `https://jal-sakshi-api.onrender.com/api/v1` |
| `JAL_SAKSHI_DEFAULT_CHAT_ID` | your Telegram chat or group id |

**The two settings the Code nodes need on a self-hosted n8n.** Both are off by
default and each produces a confusing one-line failure:

| Server env var | Set it to | Without it |
|---|---|---|
| `NODE_FUNCTION_ALLOW_BUILTIN` | `crypto` | `Verify signature` dies with *Module 'crypto' is disallowed* |
| `N8N_BLOCK_ENV_ACCESS_IN_NODE` | `false` | `$env.JAL_SAKSHI_WEBHOOK_SECRET` reads as undefined and every request is rejected |

Set both, restart n8n, then re-run the failed execution. These are *server*
variables (docker-compose `environment:` or the systemd unit), not workflow
variables — n8n reads them at boot.

**Important gotcha:** `$env` access inside Code nodes is **blocked on n8n Cloud**
(and on self-hosted installs unless you set
`N8N_BLOCK_ENV_ACCESS_IN_NODE=false`). Your options:

- *Self-hosted:* set the four as real environment variables plus
  `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`. Cleanest.
- *n8n Cloud:* replace each `$env.X` with the literal value by editing the two
  Code nodes and the HTTP Request node. Ugly but it works in five minutes.
  (n8n *Variables* / `$vars.X` is a paid-plan feature if you have it.)

### 5e. Activate, and copy the webhook URL

Toggle the workflow **Active**. Open the `JAL-SAKSHI webhook` node and copy the
**Production** URL — `https://<n8n-host>/webhook/jal-sakshi`. The *Test* URL
(`/webhook-test/...`) only fires while you have the editor open, so do not use it
in Render.

### 5f. The chat-id problem you will hit

`backend/app/seed/roster.py` ships placeholder chat ids —
`"demo-valve-operator"`, `"demo-pump-operator"`, and so on. Telegram rejects
those, and the workflow's fallback to `JAL_SAKSHI_DEFAULT_CHAT_ID` **does not
kick in**, because it only applies when `chat_id` is empty and a placeholder
string is not empty.

Set **`DEMO_TELEGRAM_CHAT_ID`** to one real chat id, in `jalsakshi/.env`
locally and in Render's environment for the deployed backend. Every outbound
message is then delivered to that one chat while the payload still says it is
addressed to Ramesh or Kamla, so the routing logic stays visible in the demo.
Blank keeps the roster's own ids, which is what a real deployment wants.

Prefer a **group** over your own private chat. A bot cannot open a conversation
with someone who has not started it first, so a judge given a link to this
deployment would otherwise see the console and the API but never the Telegram
half. Put the bot in a group, set the id to the group's (negative), and hand out
the invite link: anyone who joins watches dispatch, field reply, and closure
happen live. The workflow already expects this — its `Build field update` node
drops group chatter that names no work order.

**A basic group's id changes without warning.** Adding or removing members —
including re-adding the bot — can promote it to a *supergroup*, and Telegram
rewrites the id from the short `-533…` form to the long `-100…` form when it
does. Every send then fails, and it fails invisibly: n8n answers 200 even when
its Telegram node errored, so the notification row still reads `SENT`. The only
tell is a missing `external_message_id`.

If dispatches stop arriving while the console looks healthy, ask Telegram
directly:

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{"chat_id":<CURRENT_ID>,"text":"probe"}'
```

A migrated group answers `group chat was upgraded to a supergroup chat` and
hands you the replacement in `parameters.migrate_to_chat_id`. Put that in
`DEMO_TELEGRAM_CHAT_ID` and the loop resumes. Creating the group as a
supergroup up front — or simply not changing its membership once the demo is
configured — avoids the whole problem.

Two consequences worth stating out loud when you present:

- Telegram's default bot privacy mode only forwards **replies to the bot's own
  messages** (and commands) out of a group. That is the path the workflow
  parses, so it works — but a field update has to be sent as a *reply* to the
  dispatch. Disable privacy in BotFather (`/setprivacy`) if you want bare
  messages to work too.
- Everyone in the group can act on a work order. Fine for a demo; say so, so it
  does not read as an access-control gap.

---

## Part 6 — The second pass (the copy-paste round)

Now that every URL exists:

1. **Render → Environment:**
   - `N8N_WEBHOOK_URL` = `https://<n8n-host>/webhook/jal-sakshi`
   - `CORS_ORIGINS` = `https://<your-app>.vercel.app` (no trailing slash; add
     `,http://localhost:3000` if you also demo locally)
   - `PUBLIC_BASE_URL` = your Render URL, if you have not set it
   - Save → Render redeploys.
2. **Vercel:** confirm `NEXT_PUBLIC_API_URL` points at the live Render URL →
   **Redeploy** (env changes need a rebuild).
3. **n8n:** confirm `JAL_SAKSHI_API_URL` is the live Render URL.

---

## Part 7 — Smoke test, in order

```powershell
# 1. Backend alive
curl https://jal-sakshi-api.onrender.com/api/v1/health

# 2. Data is really coming from Supabase
curl https://jal-sakshi-api.onrender.com/api/v1/dashboard/summary
```

3. Open the Vercel URL. The console should load and the live event stream should
   tick. If the page loads but every panel is empty, it is almost always
   `CORS_ORIGINS` — check the browser console for a CORS error.
4. Trigger a fault via the simulation controls (or the demo script in
   `shared/DEMO_SCRIPT.md`). Within a tick or two a work order should be created
   and **a Telegram message should arrive in your chat**.
5. **Reply to that Telegram message** (use Telegram's reply, not a fresh
   message — the Code node reads the work-order code out of the quoted text).
   Say `Fixed`. You should get the acknowledgement about sensor verification, and
   the console should show the work order move into verification.

If step 4 produces no Telegram message, check the `notifications` table: a row
with status `SKIPPED` means `N8N_WEBHOOK_URL` is still blank; `FAILED` means n8n
rejected it — nearly always a `N8N_WEBHOOK_SECRET` mismatch between Render and
n8n.

---

## Part 8 — Things only you can do

No agent can do any of these; they all need your accounts or your identity.

**Accounts to create / log into**
- [ ] GitHub — repo for Render and Vercel to deploy from
- [ ] Render account
- [ ] Vercel account
- [ ] n8n Cloud account (or self-host + a public HTTPS tunnel)
- [ ] Telegram + @BotFather bot
- [ ] Groq account for `LLM_API_KEY` (optional — blank falls back to the
      deterministic stub, which still demos)

**Secrets to fetch and paste**
- [ ] Supabase `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY`
      (Supabase → Project Settings → API)
- [ ] Telegram bot token from BotFather
- [ ] Your Telegram chat / group id
- [ ] Groq API key (optional)
- [ ] Paste the same `N8N_WEBHOOK_SECRET` / `INBOUND_CALLBACK_SECRET` into
      **both** Render and n8n (values live in the gitignored `jalsakshi/.env`)

**Clicks nobody else can make**
- [ ] Push the repo to GitHub and grant Render + Vercel access to it
- [ ] Set Vercel **Root Directory** to `jalsakshi-frontend`
- [ ] Choose the Render plan (starter vs free — see the sleeping caveat)
- [ ] Select the Telegram credential in all three Telegram nodes
- [ ] Toggle the n8n workflow **Active** and copy its Production webhook URL
- [ ] Send your bot a first message so it is allowed to message you back

**What is already done for you**
- Supabase schema and Vitpur seed data — applied and verified
- Dockerfile, `render.yaml`, health check, single-worker config
- The n8n workflow JSON, signing, and both callback contracts
- Backend and frontend code, and the test suite under `jalsakshi/tests/`

---

## Appendix — Local run, for practising the demo

```powershell
# Backend
cd C:\hacking\Jal-sakshi\JAL-SAKSHI_Agent_Handoff\jalsakshi
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH="backend"
uvicorn app.main:app --reload --port 8000

# Frontend (second terminal)
cd C:\hacking\Jal-sakshi\JAL-SAKSHI_Agent_Handoff\jalsakshi-frontend
npm run dev
```

Your local `jalsakshi/.env` is now complete: Supabase, the Groq key, the n8n
webhook URL (`https://n8n.vaastusolutions.in/webhook/jal-sakshi`) and both
shared secrets. So a local run will **really send Telegram messages** once the
n8n workflow is active and configured with the matching secrets.

Inbound replies are the half that will not work locally: n8n has to POST back to
`JAL_SAKSHI_API_URL`, and your laptop's `localhost:8000` is not reachable from
the internet. Either point n8n at the deployed Render URL, or expose your local
backend with a tunnel (ngrok / Cloudflare Tunnel) and set `JAL_SAKSHI_API_URL`
and `PUBLIC_BASE_URL` to that address.
