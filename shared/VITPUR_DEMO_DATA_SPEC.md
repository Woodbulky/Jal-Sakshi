# Vitpur Demo Data Specification

Vitpur is a fictional demonstration service area only.

## Suggested topology

```text
SRC-01
   ↓
PMP-01
   ↓
OHT-01
   ├────────→ VLV-01 → ZONE-A
   └────────→ VLV-02 → ZONE-B
```

## Assets

- SRC-01: source
- PMP-01: pump
- OHT-01: overhead tank
- VLV-01: valve
- VLV-02: valve
- ZONE-A: distribution zone
- ZONE-B: distribution zone

## Simulated telemetry

```text
flow
upstream_pressure
tail_pressure
oht_level
pump_energy
pump_run_hours
chlorine
turbidity
pH
```

## Faults

```text
VALVE_CLOSURE
PIPELINE_BURST
PUMP_FAILURE
POWER_OUTAGE
```

The simulator knows the injected fault. The classifier must see only the resulting telemetry and asset context.
