# Data Model

## Main tables

```text
service_areas
assets
asset_connections
sensors
sensor_readings
anomalies
fault_events
work_orders
assignments
escalations
vwsc_accounts
asset_health
notifications
decision_ledger
```

## Relationships

```text
service_areas
    ├── assets ── asset_connections
    └── sensors ── sensor_readings

anomalies → fault_events → work_orders → assignments → escalations → verification → asset_health
```

## Important fields

### assets

```text
id
service_area_id
asset_code
asset_type
name
latitude
longitude
status
```

### sensors

```text
id
asset_id
sensor_type
unit
sampling_interval
status
last_seen_at
```

### sensor_readings

```text
sensor_id
timestamp
value
quality_flag
```

### fault_events

```text
id
service_area_id
asset_id
fault_type
confidence
detected_at
severity_score
evidence
status
```

### work_orders

```text
id
fault_event_id
assigned_role
assigned_person
priority
sla_deadline
status
estimated_cost
actual_cost
created_at
```

### decision_ledger

```text
timestamp
actor
agent_role
input_snapshot
decision
evidence
tool_called
state_change
```
