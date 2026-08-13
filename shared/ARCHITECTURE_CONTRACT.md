# Architecture Contract

## Core runtime flow

```text
JJM/JJM-shaped data
      ↓
Water network + telemetry
      ↓
FastAPI ingestion
      ↓
Sensor-health check
      ↓
Anomaly detection
      ↓
Fault classification
      ↓
LangGraph agent
      ↓
Assess severity / budget / authority / roster
      ↓
Create work order
      ↓
n8n
      ↓
Telegram field communication
      ↓
Field response
      ↓
Telemetry verification
      ↓
CLOSE or REOPEN
      ↓
TTWR + asset health memory
```

## Technology decisions

| Layer | Choice |
|---|---|
| Frontend | Next.js + TypeScript |
| UI | Tailwind CSS + shadcn/ui |
| Animation | Framer Motion |
| Map | MapLibre GL |
| Backend | Python FastAPI |
| Agent orchestration | LangGraph |
| LLM | Provider-agnostic Claude/Gemini/GPT adapter |
| ML | LightGBM |
| Statistics | pandas + statsmodels |
| Database | Supabase PostgreSQL |
| GIS | PostGIS |
| Automation | n8n |
| Field demo communication | Telegram |
| Deployment | Vercel + Render |

## Agent control

The state machine owns:

```text
OBSERVE → DIAGNOSE → ASSESS → ROUTE → DISPATCH → ESCALATE → VERIFY → REMEMBER
```

The LLM is a controlled reasoning/language component. It must not execute arbitrary SQL, bypass approvals, fabricate evidence, or directly force a CLOSED state.

## Map

The map is rendered from structured geographic, asset, and topology data. Do not use an LLM-generated image as the source of truth.

```text
Geography + Assets + Topology + Sensors → MapLibre → Operations Console
```

## Verified closure

```text
Field says fixed
      ↓
Backend checks sensor evidence
      ├── Pass → CLOSED
      └── Fail → REOPENED / UNVERIFIABLE
```

## n8n

n8n is the integration/automation layer, not the core agent brain. Use it for Telegram notifications, inbound Telegram updates, scheduled SLA checks, webhook integrations, and message formatting.
