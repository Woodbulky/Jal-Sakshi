# MASTER PROMPT FOR ANTIGRAVITY

You are the frontend/product engineer for JAL-SAKSHI.

Build a realistic operations command center, not a chatbot dashboard.

## Visual direction

Avoid purple and generic AI gradients. Prefer deep blue, restrained cyan/water accents, neutral surfaces, amber warning, red critical, green verified, strong typography, subtle animation, and realistic maps.

## Screens

1. Landing page
2. Service-area selection
3. Operations dashboard
4. Incident detail
5. Agent activity
6. Work-order detail
7. Verification state
8. Asset health
9. Demo fault injection

## Dashboard

Show:

```text
Service area
Network map
Water health
Active incidents
Sensor summaries
Agent activity
Work-order state
SLA countdown
Escalation timeline
TTWR
```

## Map

Use MapLibre and render backend-provided assets, connections, telemetry, and status. The frontend must not become the source of truth for topology.

## Critical verification interaction

Make this transition visually strong:

```text
RESTORATION DETECTED
Do not close yet.
Waiting for sensor verification...
```

followed by:

```text
✓ VERIFIED RESTORATION
TTWR: 03:42:00
```

## Demo controls

Expose `INJECT FAULT` controls calling the backend API for:

- valve closure
- pipeline burst
- pump failure
- power outage

## Agent timeline

Animate events such as:

```text
Sensor anomaly detected
Sensor integrity confirmed
Analyzing pressure/flow signature
Classification complete
Checking VWSC balance
Selecting Jal Mitra
Work order created
Telegram notification sent
SLA running
Escalated
Restoration detected
Awaiting verification
Verified closure
```
