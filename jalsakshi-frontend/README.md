# JAL-SAKSHI operations console

Next.js front end for the agentic rural-water operations layer. Every screen
reads the FastAPI backend in `../jalsakshi`; nothing here talks to Supabase
directly, and nothing here decides anything the backend decides.

## Run

```bash
npm install
npm run dev            # http://localhost:3000
```

The backend must be running:

```bash
cd ../jalsakshi
.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000
```

`NEXT_PUBLIC_API_URL` (`.env.local`) points at it, defaulting to
`http://localhost:8000/api/v1`. The backend allows `http://localhost:3000` in
`CORS_ORIGINS` out of the box.

With the backend down the console keeps rendering from a small offline
fallback in `lib/mock-data.ts` and says so — a red badge in the topbar, "demo
data" on the map. It never silently presents stale numbers as live ones.

## How data reaches a page

Four layers. A page only ever sees the last two.

| Layer | File | Job |
|---|---|---|
| Wire types | `types/backend.ts` | Mirrors the pydantic schemas exactly: `UPPER_SNAKE` enums, UUIDs, UTC timestamps |
| Transport | `lib/api/client.ts`, `lib/api/endpoints.ts` | One function per route in `shared/API_CONTRACT.md`. No transformation |
| Adapters | `lib/adapters.ts` | The only place wire shapes become labels, short refs (`INC-995876E0`) and IST clock times |
| Hooks | `hooks/*` | Poll, merge, and hand pages a view model |

`types/api.ts` holds the view-model shapes the components render. If a page
imports from `types/backend.ts`, something has been wired in the wrong place.

## Polling

The realtime channel in the API contract is not built yet, so the console
polls: incidents, work orders and the summary every 8 s, telemetry every 5 s,
the network every 10 s, sensor health every 30 s. All of it goes through
`hooks/useApiResource.ts`, which exposes the same interface a WebSocket push
would fill — swapping transports should not touch a single page.

SLA countdowns tick locally every second (`hooks/useNow.ts`) against the
`sla_deadline` the backend sends, so the number on screen moves without
hammering the API and cannot drift from the server's opinion.

## Things that are deliberate

- **There is no close button.** The verification screen calls `POST /verify`
  and renders whichever of `PASSED` / `FAILED` / `PENDING` / `UNVERIFIABLE`
  comes back. Closure is the backend's call, on sensor evidence.
- **The demo console shows ground truth and diagnosis separately.** The
  injection table comes from `/simulation/*`; the incident list comes from
  `/incidents`. They agree only because the classifier cannot read the former.
- **The agent activity feed is read, not written.** It renders the decision
  ledger and the anomaly table. Nothing on screen is narrated at page load.
