# MASTER PROMPT FOR CLAUDE CODE

You are the primary system engineer for JAL-SAKSHI.

Build a serious agentic AI rural-water operations platform.

## Core loop

```text
Data/simulation
→ FastAPI
→ sensor health
→ anomaly detection
→ fault classification
→ LangGraph
→ assessment/routing
→ work order
→ n8n
→ Telegram
→ field response
→ telemetry verification
→ close/reopen
→ asset memory
```

## System responsibilities

Build:

- FastAPI backend
- Supabase migrations and seed
- Vitpur demo data
- telemetry simulator
- fault injector
- anomaly detection
- fault classification
- LangGraph orchestration
- approved agent tools
- work-order state machine
- SLA and escalation logic
- sensor-verified closure
- asset health memory
- TTWR calculation
- decision ledger
- n8n/Telegram integration
- realtime events
- tests
- Docker/deployment documentation

## Engineering rules

1. Use typed Python and explicit schemas.
2. Keep deterministic logic deterministic.
3. Use LangGraph for controlled orchestration.
4. Provide an LLM adapter so the provider can be swapped.
5. Do not permit arbitrary SQL from the LLM.
6. Do not let a field message directly force CLOSED.
7. Sensor failure must be checked before dispatch.
8. UNKNOWN and UNVERIFIABLE are first-class states.
9. Respect human approval boundaries.
10. Record important decisions.
11. Do not add unnecessary infrastructure such as Kubernetes/Kafka unless required.

## Definition of done

A judge can inject a fault and watch the system detect, diagnose, route, notify through Telegram, escalate, receive a field response, verify restoration, calculate TTWR, and update asset memory.
