/* ============================================================
   JAL-SAKSHI — API & Data Model Types
   Matches shared/API_CONTRACT.md + shared/DATA_MODEL.md
   ============================================================ */

// ─── Service Area ────────────────────────────────────────────
export interface ServiceArea {
  id: string;
  name: string;
  state: string;
  district: string;
  block: string;
  village: string;
  latitude: number;
  longitude: number;
  total_assets: number;
  total_zones: number;
  total_households: number;
  is_demo: boolean;
}

// ─── Assets ──────────────────────────────────────────────────
export type AssetType = 'source' | 'pump' | 'oht' | 'valve' | 'junction' | 'distribution_point' | 'sensor' | 'pipe' | 'tap';
export type AssetStatus = 'normal' | 'warn' | 'critical' | 'offline' | 'maintenance';

export interface Asset {
  id: string;
  name: string;
  type: AssetType;
  status: AssetStatus;
  zone: string;
  latitude: number;
  longitude: number;
  detail: string;
  health_score: number;
  x?: number; // SVG position
  y?: number; // SVG position
  metadata?: Record<string, string | number>;
}

export interface AssetConnection {
  from_asset_id: string;
  to_asset_id: string;
  pipe_type: string;
  length_m: number;
  status: 'active' | 'dead' | 'restricted';
}

// ─── Telemetry ───────────────────────────────────────────────
export interface SensorReading {
  sensor_id: string;
  asset_id: string;
  channel: TelemetryChannel;
  value: number;
  unit: string;
  timestamp: string;
  is_alarm: boolean;
}

export type TelemetryChannel = 'flow' | 'upstream_pressure' | 'tail_pressure' | 'oht_level' | 'pump_energy' | 'turbidity';

export interface TelemetrySnapshot {
  flow: number;
  upstream_pressure: number;
  tail_pressure: number;
  oht_level: number;
  pump_energy: number;
  timestamp: string;
}

export interface TelemetrySeries {
  channel: TelemetryChannel;
  data: number[];
  base: number;
  amplitude: number;
  color: string;
  decimals?: number;
  unit: string;
  label: string;
}

export interface TelemetryBand {
  min: number;
  max: number;
}

// ─── Incidents ───────────────────────────────────────────────
export type Severity = 'crit' | 'warn' | 'rest' | 'info';
export type IncidentStatus = 'Detected' | 'Classified' | 'Assigned' | 'Acknowledged' | 'In Repair' | 'Restoration Detected' | 'Verifying' | 'Closed' | 'Diagnosing';

export interface Incident {
  id: string;
  asset_id: string;
  fault_type: string;
  severity: Severity;
  households_affected: number;
  status: IncidentStatus;
  sla_remaining_seconds: number;
  icon: string;
  detected_at: string;
  classification_confidence: number;
  vulnerable_facilities: string[];
  zone: string;
}

// ─── Work Orders ─────────────────────────────────────────────
export type WorkOrderState = 'Detected' | 'Classified' | 'Assigned' | 'Acknowledged' | 'In Repair' | 'Restoration Detected' | 'Verifying' | 'Closed';

export interface WorkOrder {
  id: string;
  incident_id: string;
  asset_id: string;
  fault_type: string;
  assigned_to: string;
  contact: string;
  created_at: string;
  sla_deadline: string;
  current_state: WorkOrderState;
  sla_remaining_seconds: number;
  priority: Severity;
  estimated_cost: number;
  currency: string;
  funding_source: string;
  description: string;
  location: string;
  asset_type_detail: string;
  notes: WorkOrderNote[];
  timeline: WorkOrderTimelineStep[];
}

export interface WorkOrderNote {
  title: string;
  time: string;
  detail: string;
  status: 'ok' | 'live' | 'pending' | '';
}

export interface WorkOrderTimelineStep {
  label: string;
  time: string;
  icon: string;
  state: 'done' | 'now' | 'pending' | 'alert';
}

// ─── Verification ────────────────────────────────────────────
export interface VerificationCheck {
  key: string;
  name: string;
  expected_range: string;
  current_value: string;
  status: 'pending' | 'running' | 'pass' | 'fail';
  ok_value: string;
  bad_value: string;
}

// ─── Escalation ──────────────────────────────────────────────
export type EscalationLevel = 1 | 2 | 3 | 4;

export interface EscalationEntry {
  level: EscalationLevel;
  role: string;
  entity: string;
  time: string;
  reason: string;
  sla_breach: string;
  evidence: string;
  notification_status: string;
  badge_type: string;
  is_active: boolean;
  is_pending: boolean;
}

// ─── Agent Activity ──────────────────────────────────────────
export interface AgentEvent {
  time: string;
  status: '' | 'ok' | 'warn' | 'crit' | 'live';
  message: string;
  tag?: string;
}

// ─── VWSC / Financial ────────────────────────────────────────
export interface VWSCAccount {
  balance: number;
  currency: string;
  estimated_cost: number;
  approval_required: boolean;
}

// ─── Demo / Simulation ──────────────────────────────────────
export type FaultType = 'valve' | 'burst' | 'pump' | 'power';

export interface FaultDefinition {
  type: FaultType;
  name: string;
  asset: string;
  signature: string;
  severity: Severity;
  effects: Record<string, number>;
  icon: string;
  color_class: string;
}

// ─── Asset Health ────────────────────────────────────────────
export interface AssetHealth {
  asset_id: string;
  health_score: number;
  failure_count_life: number;
  failure_count_12m: number;
  fleet_median_12m: number;
  mean_time_to_repair: string;
  fleet_mttr: string;
  warranty_status: string;
  age_months: number;
  total_repair_cost: number;
  currency: string;
  health_trend: number[]; // monthly scores
  recent_incidents: AssetIncident[];
  recommendation: string;
}

export interface AssetIncident {
  id: string;
  date: string;
  fault: string;
  severity: Severity;
  ttwr: string;
  status: string;
}
