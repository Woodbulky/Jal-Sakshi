# 90-Second Demo Script

## 0:00 Normal

Dashboard shows service area, healthy network, water-health score, and no critical incidents.

## 0:10 Inject

Judge selects:

```text
INJECT FAULT → VALVE CLOSURE
```

## 0:15 Detect

Flow drops, upstream pressure rises, tail pressure drops.

## 0:22 Diagnose

Agent displays:

```text
Sensor health: PASS
Fault: VALVE_CLOSURE
Confidence: 0.91
```

## 0:35 Route

Agent checks affected households, vulnerability, VWSC balance, roster, and estimated cost. Creates a work order and starts the SLA.

## 0:45 Telegram

n8n sends the work order to Telegram.

## 0:55 Escalate

Simulate no acknowledgement. Agent escalates and n8n sends the escalation message.

## 1:05 Repair

Judge clicks `Simulate Repair`.

## 1:15 Verify

Flow returns, but UI says:

```text
RESTORATION DETECTED
Do not close yet.
Waiting for sensor verification...
```

Then:

```text
VERIFIED RESTORATION
TTWR: 03:42:00
```

## Final

Asset memory shows the repeated-failure history and a design-defect review recommendation.
