/* ============================================================
   JAL-SAKSHI — Backend wire types

   These mirror the FastAPI pydantic schemas exactly (UPPER_SNAKE enums,
   snake_case fields, UUID ids). They are what `lib/api` returns.

   The view-model types in `types/api.ts` are what the pages render.
   `lib/adapters.ts` is the only place allowed to convert between them.
   ============================================================ */

// ─── Network ─────────────────────────────────────────────────
export type BackendAssetType =
  | 'SOURCE' | 'PUMP' | 'TANK' | 'VALVE' | 'ZONE'
  | 'PIPELINE' | 'TREATMENT' | 'METER';

export type BackendAssetStatus =
  | 'OPERATIONAL' | 'DEGRADED' | 'FAILED' | 'UNDER_REPAIR' | 'DECOMMISSIONED';

export type BackendSensorType =
  | 'FLOW' | 'PRESSURE_UPSTREAM' | 'PRESSURE_TAIL' | 'LEVEL' | 'ENERGY'
  | 'RUN_HOURS' | 'CHLORINE' | 'TURBIDITY' | 'PH';

export type BackendSensorStatus =
  | 'ACTIVE' | 'DEGRADED' | 'FAILED' | 'OFFLINE' | 'MAINTENANCE';

export type QualityFlag =
  | 'GOOD' | 'SUSPECT' | 'STALE' | 'MISSING' | 'FLATLINE' | 'OUT_OF_RANGE';

export interface BackendServiceArea {
  id: string;
  code: string;
  name: string;
  district: string | null;
  state: string | null;
  population: number | null;
  households: number | null;
  latitude: number | null;
  longitude: number | null;
  is_demo: boolean;
  metadata: Record<string, unknown>;
}

export interface BackendAsset {
  id: string;
  service_area_id: string;
  asset_code: string;
  asset_type: BackendAssetType;
  name: string;
  latitude: number | null;
  longitude: number | null;
  status: BackendAssetStatus;
  households_served: number;
  commissioned_on: string | null;
  metadata: Record<string, unknown>;
}

export interface BackendAssetConnection {
  id: string;
  service_area_id: string;
  from_asset_id: string;
  to_asset_id: string;
  connection_type: string;
  diameter_mm: number | null;
  length_m: number | null;
}

export interface BackendSensorReading {
  sensor_id: string;
  ts: string;
  value: number | null;
  quality_flag: QualityFlag;
}

export interface BackendSensor {
  id: string;
  asset_id: string;
  sensor_code: string;
  sensor_type: BackendSensorType;
  unit: string;
  sampling_interval_seconds: number;
  status: BackendSensorStatus;
  last_seen_at: string | null;
  expected_min: number | null;
  expected_max: number | null;
}

export interface BackendSensorWithLatest extends BackendSensor {
  latest: BackendSensorReading | null;
}

export interface NetworkResponse {
  service_area: BackendServiceArea;
  nodes: BackendAsset[];
  edges: BackendAssetConnection[];
  sensors: BackendSensorWithLatest[];
  generated_at: string;
}

export interface AssetTelemetryResponse {
  asset: BackendAsset;
  sensors: BackendSensor[];
  readings: BackendSensorReading[];
  window_start: string | null;
  window_end: string | null;
}

// ─── Detection / incidents ───────────────────────────────────
export type BackendFaultType =
  | 'PUMP_FAILURE' | 'POWER_OUTAGE' | 'PIPELINE_BURST' | 'VALVE_CLOSURE'
  | 'SOURCE_DEPLETION' | 'SENSOR_FAULT' | 'THEFT_OR_UNAUTHORISED_TAPPING'
  | 'UNKNOWN';

export type SensorIssue =
  | 'STALE' | 'MISSING' | 'FLATLINE' | 'OUT_OF_RANGE' | 'NO_BASELINE';

export interface SensorHealth {
  sensor_id: string;
  sensor_code: string;
  asset_id: string;
  status: BackendSensorStatus;
  trusted: boolean;
  issues: SensorIssue[];
  last_value: number | null;
  last_seen_at: string | null;
  seconds_since_last_reading: number | null;
  quality_flag: QualityFlag;
  note: string | null;
}

export interface Anomaly {
  id: string | null;
  service_area_id: string;
  asset_id: string | null;
  sensor_id: string | null;
  sensor_code: string | null;
  detected_at: string;
  window_start: string | null;
  window_end: string | null;
  method: 'ROBUST_Z' | 'RANGE' | 'SENSOR_HEALTH';
  metric: string;
  observed_value: number | null;
  baseline_value: number | null;
  residual: number | null;
  z_score: number | null;
  severity: number;
  status: string;
  fault_event_id: string | null;
  details: Record<string, unknown>;
}

export interface ClassificationCandidate {
  fault_type: BackendFaultType;
  score: number;
  asset_code: string | null;
  matched: string[];
  missed: string[];
}

export interface Classification {
  fault_type: BackendFaultType;
  confidence: number;
  asset_id: string | null;
  asset_code: string | null;
  severity_score: number;
  households_affected: number;
  classifier_version: string;
  summary: string;
  evidence: Record<string, unknown>;
  candidates: ClassificationCandidate[];
  sensor_health_blocked: boolean;
}

export interface FaultEvent {
  id: string;
  service_area_id: string;
  asset_id: string | null;
  fault_type: BackendFaultType;
  confidence: number;
  detected_at: string;
  severity_score: number;
  households_affected: number;
  evidence: FaultEvidence;
  status: string;
  resolved_at: string | null;
  ttwr_minutes: number | null;
  classifier_version: string | null;
  created_at: string | null;
}

/** The classifier writes a free-form bag; these are the keys it always sets. */
export interface FaultEvidence {
  summary?: string;
  anomalies?: Array<{
    z?: number;
    method?: string;
    metric?: string;
    trusted?: boolean;
    baseline?: number;
    observed?: number;
    severity?: number;
    sensor_code?: string;
  }>;
  reasoning?: { candidates?: ClassificationCandidate[] };
  candidates?: ClassificationCandidate[];
  window_start?: string;
  window_end?: string;
  untrusted_sensors?: string[];
  sensor_health_blocked?: boolean;
  [key: string]: unknown;
}

export interface IncidentDetail extends FaultEvent {
  anomalies: Anomaly[];
}

export interface BaselineBand {
  sensor_id: string;
  sensor_code: string;
  ts: string;
  baseline: number | null;
  lower: number | null;
  upper: number | null;
  sample_count: number;
  weak: boolean;
}

export interface DetectionRun {
  service_area_id: string;
  service_area_code: string;
  ran_at: string;
  window_start: string;
  window_end: string;
  sensors_checked: number;
  untrusted_sensors: string[];
  sensor_health: SensorHealth[];
  anomalies: Anomaly[];
  classification: Classification | null;
  fault_event: FaultEvent | null;
  baseline_refreshed: boolean;
  note: string | null;
}

// ─── Work orders ─────────────────────────────────────────────
export type BackendWorkOrderStatus =
  | 'DETECTED' | 'TRIAGING' | 'CLASSIFIED' | 'ASSESSED' | 'ASSIGNED'
  | 'ACKNOWLEDGED' | 'IN_REPAIR' | 'RESTORATION_DETECTED' | 'VERIFYING'
  | 'CLOSED' | 'REOPENED' | 'UNVERIFIABLE';

export type WorkOrderPriority = 'P1' | 'P2' | 'P3' | 'P4';

export type CrewRole =
  | 'PUMP_OPERATOR' | 'LINEMAN' | 'ELECTRICIAN' | 'VALVE_OPERATOR'
  | 'INSTRUMENTATION_TECH' | 'VWSC_SECRETARY' | 'BLOCK_ENGINEER';

export interface BackendWorkOrder {
  id: string;
  wo_code: string;
  service_area_id: string;
  fault_event_id: string | null;
  asset_id: string | null;
  status: BackendWorkOrderStatus;
  priority: WorkOrderPriority;
  assigned_role: CrewRole | null;
  assigned_person: string | null;
  action_summary: string | null;
  sla_hours: number | null;
  sla_deadline: string | null;
  sla_breached: boolean;
  estimated_cost: number | null;
  actual_cost: number | null;
  requires_approval: boolean;
  approved_by: string | null;
  approved_at: string | null;
  acknowledged_at: string | null;
  repair_started_at: string | null;
  restoration_detected_at: string | null;
  verification_started_at: string | null;
  closed_at: string | null;
  reopen_count: number;
  verification_result: Record<string, unknown> | null;
  ttwr_minutes: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface Assignment {
  id: string;
  work_order_id: string;
  assignee_role: CrewRole;
  assignee_name: string | null;
  telegram_chat_id: string | null;
  phone: string | null;
  assigned_at: string;
  acknowledged_at: string | null;
  released_at: string | null;
  status: string;
  metadata: Record<string, unknown>;
}

export interface Escalation {
  id: string;
  work_order_id: string;
  level: number;
  from_role: CrewRole | null;
  to_role: CrewRole;
  reason: string;
  triggered_at: string;
  resolved_at: string | null;
  sla_breach_minutes: number | null;
  metadata: Record<string, unknown>;
}

export interface DecisionEntry {
  id: string | null;
  ts: string;
  actor: string;
  agent_role: string | null;
  work_order_id: string | null;
  fault_event_id: string | null;
  input_snapshot: Record<string, unknown>;
  decision: Record<string, unknown>;
  evidence: Record<string, unknown>;
  tool_called: string | null;
  state_change: string | null;
  confidence: number | null;
  notes: string | null;
}

export interface WorkOrderDetail {
  work_order: BackendWorkOrder;
  assignments: Assignment[];
  escalations: Escalation[];
  decisions: DecisionEntry[];
}

export interface CrewMember {
  name: string;
  role: CrewRole;
  phone: string | null;
  telegram_chat_id: string | null;
  available: boolean;
  skills: BackendFaultType[];
}

// ─── Asset health ────────────────────────────────────────────
export interface AssetHealthRecord {
  id: string | null;
  asset_id: string;
  failure_count: number;
  last_failure_at: string | null;
  last_repair_at: string | null;
  mtbf_hours: number | null;
  mean_ttwr_minutes: number | null;
  /** 1.0 is healthy. Falls with failure count and slow restoration. */
  health_score: number;
  recurring_failure: boolean;
  recommendation: string | null;
  history: Array<Record<string, unknown>>;
  updated_at: string | null;
}

export interface AssetHealthDetail {
  asset: BackendAsset;
  health: AssetHealthRecord | null;
  incidents: FaultEvent[];
  work_orders: BackendWorkOrder[];
}

// ─── Verification ────────────────────────────────────────────
export type VerificationOutcome = 'PASSED' | 'FAILED' | 'UNVERIFIABLE' | 'PENDING';

export interface BackendVerificationCheck {
  name: string;
  passed: boolean;
  detail: string;
  observed: number | null;
  expected_low: number | null;
  expected_high: number | null;
}

export interface VerificationReport {
  work_order_id: string;
  outcome: VerificationOutcome;
  checked_at: string;
  window_minutes: number;
  checks: BackendVerificationCheck[];
  untrusted_sensors: string[];
  summary: string;
  ttwr_minutes: number | null;
}

// ─── Agent ───────────────────────────────────────────────────
export interface AgentRunResponse {
  ran_at: string;
  trace: Array<Record<string, unknown>>;
  classification: Classification | null;
  work_order: BackendWorkOrder | null;
  verification: VerificationReport | null;
  message: string | null;
  halted: string | null;
}

// ─── Simulation ──────────────────────────────────────────────
export interface FaultInjection {
  id: string;
  service_area_id: string;
  asset_id: string | null;
  fault_type: BackendFaultType;
  started_at: string;
  ends_at: string | null;
  cleared_at: string | null;
  is_active: boolean;
  params: Record<string, unknown>;
}

export interface SimulationStatus {
  service_area_id: string;
  service_area_code: string;
  running: boolean;
  tick_seconds: number;
  time_scale: number;
  sensor_count: number;
  last_tick_at: string | null;
  readings_written: number;
  active_injections: FaultInjection[];
}

export interface BackfillResult {
  hours: number;
  step_minutes: number;
  readings_written: number;
  window_start: string;
  window_end: string;
}

// ─── Health / dashboard ──────────────────────────────────────
export interface HealthResponse {
  status: string;
  app_env: string;
  database: string;
  version: string;
  timestamp: string;
  classifier: string;
}

export interface SeverityCounts {
  critical: number;
  warning: number;
  info: number;
}

export interface SensorTrust {
  total: number;
  trusted: number;
  untrusted: string[];
}

export interface DashboardSummary {
  service_area_id: string;
  service_area_code: string;
  service_area_name: string;
  generated_at: string;
  service_area_households: number | null;
  open_incidents: number;
  incident_severity: SeverityCounts;
  households_affected: number;
  households_by_zone: Record<string, number>;
  open_work_orders: number;
  work_orders_by_status: Record<string, number>;
  sla_breached: number;
  active_ttwr_minutes: number | null;
  active_incident_id: string | null;
  mean_ttwr_minutes: number | null;
  closed_in_window: number;
  reopened_in_window: number;
  reopen_rate: number;
  sensors: SensorTrust;
  water_health_score: number;
  network_uptime_pct: number;
  budget_allocated: number | null;
  budget_remaining: number | null;
  autonomous_approval_limit: number | null;
  currency: string;
}
