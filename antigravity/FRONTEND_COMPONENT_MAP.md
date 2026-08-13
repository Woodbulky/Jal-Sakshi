# Frontend Component Map

```text
frontend/
├── app/
│   ├── page.tsx
│   ├── service-area/
│   ├── dashboard/
│   └── incidents/
├── components/
│   ├── layout/
│   ├── map/
│   │   ├── WaterNetworkMap.tsx
│   │   ├── AssetMarker.tsx
│   │   ├── NetworkEdge.tsx
│   │   └── MapLegend.tsx
│   ├── telemetry/
│   │   ├── TelemetryCard.tsx
│   │   ├── FlowChart.tsx
│   │   ├── PressureChart.tsx
│   │   └── LevelChart.tsx
│   ├── incidents/
│   │   ├── IncidentCard.tsx
│   │   ├── IncidentDrawer.tsx
│   │   ├── WorkOrderPanel.tsx
│   │   └── EscalationTimeline.tsx
│   ├── agent/
│   │   ├── AgentActivityPanel.tsx
│   │   ├── AgentEventItem.tsx
│   │   └── AgentStatus.tsx
│   ├── verification/
│   │   ├── VerificationState.tsx
│   │   └── TTWRCard.tsx
│   ├── demo/
│   │   └── FaultInjectionPanel.tsx
│   └── ui/
├── hooks/
├── lib/
└── types/
```

Antigravity owns these frontend areas. It should consume the API contract instead of inventing backend behavior.
