# Claude Code Task Plan

## 1. Bootstrap

Create backend, simulation, supabase, n8n contracts, and docs. Add configuration, logging, tests, and `/health`.

## 2. Database

Implement service areas, assets, topology, sensors, readings, anomalies, faults, work orders, assignments, escalations, asset health, notifications, and decision ledger.

## 3. Network APIs

Implement service-area and network endpoints returning nodes, edges, sensors, and current state.

## 4. Telemetry simulator

Generate normal patterns for flow, pressure, level, energy, run-hours, chlorine, turbidity, and pH.

## 5. Fault injection

Implement valve closure, pipeline burst, pump failure, and power outage without exposing the selected label to the classifier.

## 6. Analytics

Implement sensor-health checks, baseline/residual/z-score anomaly detection, signature rules, and a LightGBM adapter.

## 7. Agent

Build LangGraph nodes: observe, diagnose, assess, route, dispatch, escalate, verify, remember.

## 8. Tools

Implement sensor window, asset metadata, roster, budget, spares, create/assign/escalate, verify/reopen, asset health, approval, and decision-ledger tools.

## 9. Work-order states

```text
DETECTED
TRIAGING
CLASSIFIED
ASSESSED
ASSIGNED
ACKNOWLEDGED
IN_REPAIR
RESTORATION_DETECTED
VERIFYING
CLOSED
REOPENED
UNVERIFIABLE
```

## 10. n8n/Telegram

Create outbound webhook payloads and inbound callback handling. Keep credentials in environment variables.

## 11. Realtime

Expose sensor, agent, incident, work-order, escalation, and verification updates by WebSocket or SSE.

## 12. Testing

Test all four demo faults, sensor failure, UNKNOWN, budget limits, SLA breaches, repeat failures, verification pass/fail, invalid transitions, and Telegram callbacks.

## 13. Deployment

Prepare Dockerfile, Render configuration, environment reference, migration instructions, and production-safe logging.
