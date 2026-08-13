/* ============================================================
   JAL-SAKSHI — backend → view-model adapters

   The API speaks UPPER_SNAKE enums, UUIDs and UTC timestamps. The console
   speaks labels, short refs and IST clock times. This module is the only
   translation layer; pages never touch `types/backend.ts` shapes directly.
   ============================================================ */
import type {
  Anomaly,
  Assignment,
  BackendAsset,
  BackendAssetStatus,
  BackendFaultType,
  BackendSensorWithLatest,
  BackendWorkOrder,
  BackendWorkOrderStatus,
  CrewRole,
  DecisionEntry,
  Escalation,
  FaultEvent,
  SensorHealth,
  VerificationReport,
} from '@/types/backend';
import type {
  AgentEvent,
  Asset,
  AssetStatus,
  EscalationEntry,
  EscalationLevel,
  Incident,
  IncidentStatus,
  Severity,
  VerificationCheck,
  WorkOrder,
  WorkOrderNote,
  WorkOrderState,
  WorkOrderTimelineStep,
} from '@/types/api';

// ─── Formatting ──────────────────────────────────────────────
/** The demo service area is in India; every clock in the console is IST. */
const IST = 'Asia/Kolkata';

export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
    timeZone: IST,
  });
}

export function fmtSeconds(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: IST,
  });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.toLocaleTimeString('en-IN', {
    hour: '2-digit', minute: '2-digit', hour12: true, timeZone: IST,
  })} · ${d.toLocaleDateString('en-IN', {
    day: '2-digit', month: 'short', timeZone: IST,
  })}`;
}

export function fmtNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return n.toLocaleString('en-IN');
}

export function fmtCurrency(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return `₹${Math.round(n).toLocaleString('en-IN')}`;
}

/** Minutes as the console's duration format: `03h 42m`. */
export function fmtDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return '—';
  const total = Math.max(0, Math.round(minutes));
  return `${String(Math.floor(total / 60)).padStart(2, '0')}h ${String(total % 60).padStart(2, '0')}m`;
}

/** UUIDs are unreadable on stage. Incidents get a stable short ref. */
export function incidentRef(id: string): string {
  return `INC-${id.slice(0, 8).toUpperCase()}`;
}

// ─── Enum labels ─────────────────────────────────────────────
const FAULT_LABELS: Record<BackendFaultType, string> = {
  PUMP_FAILURE: 'Pump Failure',
  POWER_OUTAGE: 'Power Outage',
  PIPELINE_BURST: 'Pipeline Burst',
  VALVE_CLOSURE: 'Valve Closure',
  SOURCE_DEPLETION: 'Source Depletion',
  SENSOR_FAULT: 'Sensor Fault',
  THEFT_OR_UNAUTHORISED_TAPPING: 'Unauthorised Tapping',
  UNKNOWN: 'Unclassified Anomaly',
};

export const faultLabel = (t: BackendFaultType): string => FAULT_LABELS[t] ?? t;

const FAULT_ICONS: Record<BackendFaultType, string> = {
  PUMP_FAILURE: '#i-pump',
  POWER_OUTAGE: '#i-bolt',
  PIPELINE_BURST: '#i-pipe',
  VALVE_CLOSURE: '#i-valve',
  SOURCE_DEPLETION: '#i-drop',
  SENSOR_FAULT: '#i-asset',
  THEFT_OR_UNAUTHORISED_TAPPING: '#i-alert',
  UNKNOWN: '#i-alert',
};

export const faultIcon = (t: BackendFaultType): string => FAULT_ICONS[t] ?? '#i-alert';

const STATUS_LABELS: Record<BackendWorkOrderStatus, string> = {
  DETECTED: 'Detected',
  TRIAGING: 'Diagnosing',
  CLASSIFIED: 'Classified',
  ASSESSED: 'Assessed',
  ASSIGNED: 'Assigned',
  ACKNOWLEDGED: 'Acknowledged',
  IN_REPAIR: 'In Repair',
  RESTORATION_DETECTED: 'Restoration Detected',
  VERIFYING: 'Verifying',
  CLOSED: 'Closed',
  REOPENED: 'Reopened',
  UNVERIFIABLE: 'Unverifiable',
};

export const workOrderStatusLabel = (s: BackendWorkOrderStatus): string =>
  STATUS_LABELS[s] ?? s;

const ROLE_LABELS: Record<CrewRole, string> = {
  PUMP_OPERATOR: 'Pump Operator',
  LINEMAN: 'Lineman',
  ELECTRICIAN: 'Electrician',
  VALVE_OPERATOR: 'Valve Operator',
  INSTRUMENTATION_TECH: 'Instrumentation Technician',
  VWSC_SECRETARY: 'VWSC Secretary',
  BLOCK_ENGINEER: 'Block Junior Engineer',
};

export const roleLabel = (r: CrewRole | null | undefined): string =>
  r ? ROLE_LABELS[r] ?? r : 'Unassigned';

// ─── Severity ────────────────────────────────────────────────
/** The backend scores severity 0–1; the console colours in four buckets. */
export function severityFromScore(score: number): Severity {
  if (score >= 0.66) return 'crit';
  if (score >= 0.33) return 'warn';
  return 'info';
}

export const SEVERITY_LABEL: Record<Severity, string> = {
  crit: 'Critical',
  warn: 'Warning',
  rest: 'Restoring',
  info: 'Info',
};

/** Priority carries severity for a work order that has one. */
export function severityFromPriority(p: BackendWorkOrder['priority']): Severity {
  if (p === 'P1') return 'crit';
  if (p === 'P2') return 'warn';
  return 'info';
}

// ─── Incidents ───────────────────────────────────────────────
export interface IncidentContext {
  /** asset UUID → asset, from the network response. */
  assets: Map<string, BackendAsset>;
  /** fault_event_id → the work order opened for it, if any. */
  ordersByEvent: Map<string, BackendWorkOrder>;
}

export const emptyContext = (): IncidentContext => ({
  assets: new Map(),
  ordersByEvent: new Map(),
});

export function assetsById(assets: BackendAsset[]): Map<string, BackendAsset> {
  return new Map(assets.map((a) => [a.id, a]));
}

export function ordersByEvent(orders: BackendWorkOrder[]): Map<string, BackendWorkOrder> {
  const map = new Map<string, BackendWorkOrder>();
  for (const order of orders) {
    if (!order.fault_event_id) continue;
    const existing = map.get(order.fault_event_id);
    // Keep the newest order for an event: a reopen writes a later one.
    if (!existing || (order.created_at ?? '') > (existing.created_at ?? '')) {
      map.set(order.fault_event_id, order);
    }
  }
  return map;
}

/**
 * Seconds left on the SLA clock. Negative deadlines clamp to zero (breached).
 *
 * A closed order has no clock: the commitment was met or missed when the
 * sensors confirmed restoration, and a countdown still ticking beside
 * `CLOSED` reads as work outstanding on work that is finished. `UNVERIFIABLE`
 * deliberately keeps running — that order can still be verified later, so the
 * village is still owed water.
 */
export function slaRemainingSeconds(
  order: BackendWorkOrder | undefined,
  now = Date.now(),
): number {
  if (!order?.sla_deadline) return 0;
  if (order.status === 'CLOSED') return 0;
  return Math.max(0, Math.round((new Date(order.sla_deadline).getTime() - now) / 1000));
}

export function toIncident(event: FaultEvent, ctx: IncidentContext): Incident {
  const asset = event.asset_id ? ctx.assets.get(event.asset_id) : undefined;
  const order = ctx.ordersByEvent.get(event.id);
  const facilities = Array.isArray(event.evidence?.vulnerable_facilities)
    ? (event.evidence.vulnerable_facilities as string[])
    : [];

  return {
    id: event.id,
    asset_id: asset?.asset_code ?? '—',
    fault_type: faultLabel(event.fault_type),
    severity: event.status === 'RESOLVED' ? 'rest' : severityFromScore(event.severity_score),
    households_affected: event.households_affected,
    status: (order
      ? workOrderStatusLabel(order.status)
      : event.status === 'RESOLVED'
        ? 'Closed'
        : 'Detected') as IncidentStatus,
    sla_remaining_seconds: slaRemainingSeconds(order),
    icon: faultIcon(event.fault_type),
    detected_at: fmtDateTime(event.detected_at),
    classification_confidence: Math.round(event.confidence * 100),
    vulnerable_facilities: facilities,
    zone: asset?.asset_code?.startsWith('ZONE-')
      ? asset.asset_code.replace('ZONE-', '')
      : '',
  };
}

// ─── Work orders ─────────────────────────────────────────────
/** The lifecycle the timeline widget draws, in order. */
const TIMELINE: Array<{ status: BackendWorkOrderStatus; label: string; icon: string }> = [
  { status: 'DETECTED', label: 'Detected', icon: '#i-alert' },
  { status: 'CLASSIFIED', label: 'Classified', icon: '#i-agent' },
  { status: 'ASSIGNED', label: 'Assigned', icon: '#i-user' },
  { status: 'ACKNOWLEDGED', label: 'Acknowledged', icon: '#i-chk' },
  { status: 'IN_REPAIR', label: 'In Repair', icon: '#i-wrench' },
  { status: 'RESTORATION_DETECTED', label: 'Restoration Detected', icon: '#i-drop' },
  { status: 'VERIFYING', label: 'Verifying', icon: '#i-shield' },
  { status: 'CLOSED', label: 'Closed', icon: '#i-clip' },
];

const TIMELINE_INDEX = new Map(TIMELINE.map((s, i) => [s.status, i]));

/** Where a status sits on the ladder. Off-ladder states resolve to the step
 *  they came from: REOPENED is back at repair, UNVERIFIABLE is at verifying. */
function ladderIndex(status: BackendWorkOrderStatus): number {
  if (status === 'REOPENED') return TIMELINE_INDEX.get('IN_REPAIR')!;
  if (status === 'UNVERIFIABLE') return TIMELINE_INDEX.get('VERIFYING')!;
  if (status === 'TRIAGING') return TIMELINE_INDEX.get('DETECTED')!;
  if (status === 'ASSESSED') return TIMELINE_INDEX.get('CLASSIFIED')!;
  return TIMELINE_INDEX.get(status) ?? 0;
}

function stepTime(order: BackendWorkOrder, status: BackendWorkOrderStatus): string {
  const at: Partial<Record<BackendWorkOrderStatus, string | null>> = {
    DETECTED: order.created_at,
    CLASSIFIED: order.created_at,
    ACKNOWLEDGED: order.acknowledged_at,
    IN_REPAIR: order.repair_started_at,
    RESTORATION_DETECTED: order.restoration_detected_at,
    VERIFYING: order.verification_started_at,
    CLOSED: order.closed_at,
  };
  const iso = at[status];
  return iso ? fmtClock(iso) : '—';
}

export function toTimeline(order: BackendWorkOrder): WorkOrderTimelineStep[] {
  const current = ladderIndex(order.status);
  const failed = order.status === 'REOPENED' || order.status === 'UNVERIFIABLE';
  return TIMELINE.map((step, i) => ({
    label: step.label,
    icon: step.icon,
    time: stepTime(order, step.status),
    state:
      i < current ? 'done'
        : i === current ? (failed ? 'alert' : 'now')
          : 'pending',
  }));
}

/** The ledger and the assignment row, rendered as the console's note list. */
export function toNotes(
  order: BackendWorkOrder,
  assignments: Assignment[],
  decisions: DecisionEntry[],
): WorkOrderNote[] {
  const notes: WorkOrderNote[] = [];

  for (const assignment of assignments) {
    notes.push({
      title: `Assigned to ${assignment.assignee_name ?? roleLabel(assignment.assignee_role)}`,
      time: fmtClock(assignment.assigned_at),
      detail: `${roleLabel(assignment.assignee_role)}${
        assignment.phone ? ` · ${assignment.phone}` : ''
      }`,
      status: 'ok',
    });
    if (assignment.acknowledged_at) {
      notes.push({
        title: `Acknowledged by ${assignment.assignee_name ?? roleLabel(assignment.assignee_role)}`,
        time: fmtClock(assignment.acknowledged_at),
        detail: 'Confirmed over the Telegram thread.',
        status: 'ok',
      });
    }
  }

  for (const entry of decisions) {
    if (!entry.state_change && !entry.notes) continue;
    notes.push({
      title: entry.state_change ?? entry.tool_called ?? entry.actor,
      time: fmtClock(entry.ts),
      detail: entry.notes ?? describeDecision(entry),
      status: entry.state_change?.includes('CLOSED') ? 'ok' : '',
    });
  }

  if (order.status === 'VERIFYING' || order.status === 'RESTORATION_DETECTED') {
    notes.push({
      title: 'Awaiting sensor-verified restoration',
      time: '—',
      detail: 'The work order cannot close until telemetry holds inside its expected band.',
      status: 'live',
    });
  }

  return notes;
}

export function toWorkOrderView(
  order: BackendWorkOrder,
  {
    assignments = [],
    decisions = [],
    asset,
    event,
  }: {
    assignments?: Assignment[];
    decisions?: DecisionEntry[];
    asset?: BackendAsset;
    event?: FaultEvent;
  } = {},
): WorkOrder {
  const assignment = assignments[assignments.length - 1];
  return {
    id: order.wo_code,
    incident_id: order.fault_event_id ?? '',
    asset_id: asset?.asset_code ?? '—',
    fault_type: event ? faultLabel(event.fault_type) : (order.action_summary ?? '—'),
    assigned_to: order.assigned_person ?? roleLabel(order.assigned_role),
    contact: assignment?.phone ?? '—',
    created_at: fmtDateTime(order.created_at),
    sla_deadline: fmtDateTime(order.sla_deadline),
    current_state: workOrderStatusLabel(order.status) as WorkOrderState,
    sla_remaining_seconds: slaRemainingSeconds(order),
    priority: severityFromPriority(order.priority),
    estimated_cost: order.estimated_cost ?? 0,
    currency: '₹',
    funding_source: 'VWSC O&M ledger',
    description: order.action_summary ?? '—',
    location: asset ? `${asset.name} · ${asset.asset_code}` : '—',
    asset_type_detail: asset ? asset.asset_type : '—',
    notes: toNotes(order, assignments, decisions),
    timeline: toTimeline(order),
  };
}

// ─── Escalations ─────────────────────────────────────────────
const BADGE_BY_LEVEL = ['b-normal', 'b-normal', 'b-warn', 'b-crit', 'b-crit'];

export function toEscalationEntries(
  escalations: Escalation[],
  order?: BackendWorkOrder,
): EscalationEntry[] {
  const sorted = [...escalations].sort((a, b) => a.level - b.level);
  const highest = sorted.length ? sorted[sorted.length - 1].level : 0;

  return sorted.map((esc) => ({
    level: Math.min(4, Math.max(1, esc.level)) as EscalationLevel,
    role: roleLabel(esc.to_role),
    entity: esc.from_role ? `Escalated from ${roleLabel(esc.from_role)}` : 'Vitpur VWSC',
    time: fmtDateTime(esc.triggered_at),
    reason: esc.reason,
    sla_breach:
      esc.sla_breach_minutes && esc.sla_breach_minutes > 0
        ? `Yes — ${fmtDuration(esc.sla_breach_minutes)} overdue`
        : order?.sla_breached
          ? 'Yes'
          : 'No',
    evidence: 'Attached',
    notification_status: esc.resolved_at ? 'Resolved' : 'Sent',
    badge_type: BADGE_BY_LEVEL[Math.min(4, esc.level)] ?? 'b-neutral',
    is_active: esc.level === highest && !esc.resolved_at,
    is_pending: false,
  }));
}

// ─── Verification ────────────────────────────────────────────
export function toVerificationChecks(report: VerificationReport): VerificationCheck[] {
  return report.checks.map((check, i) => {
    const band =
      check.expected_low !== null && check.expected_high !== null
        ? `${check.expected_low}–${check.expected_high}`
        : check.detail;
    const observed = check.observed !== null ? String(check.observed) : '—';
    return {
      key: `chk-${i}`,
      name: check.name,
      expected_range: band,
      current_value: observed,
      status: check.passed ? 'pass' : 'fail',
      ok_value: observed,
      bad_value: observed,
    };
  });
}

export const VERIFICATION_BADGE: Record<
  VerificationReport['outcome'],
  { label: string; badge: string }
> = {
  PASSED: { label: 'Verified', badge: 'b-normal' },
  FAILED: { label: 'Reopened', badge: 'b-crit' },
  PENDING: { label: 'Watching telemetry', badge: 'b-rest' },
  UNVERIFIABLE: { label: 'Needs human inspection', badge: 'b-warn' },
};

// ─── Agent activity ──────────────────────────────────────────
function describeDecision(entry: DecisionEntry): string {
  const parts: string[] = [];
  if (entry.tool_called) parts.push(entry.tool_called);
  if (entry.confidence !== null && entry.confidence !== undefined) {
    parts.push(`confidence ${Math.round(entry.confidence * 100)}%`);
  }
  const decision = entry.decision ?? {};
  for (const key of ['fault_type', 'outcome', 'role', 'reason']) {
    const value = decision[key];
    if (typeof value === 'string') parts.push(value);
  }
  return parts.join(' · ');
}

/** The decision ledger, rendered as the console's agent activity feed. */
export function toAgentEvents(decisions: DecisionEntry[]): AgentEvent[] {
  return [...decisions]
    .sort((a, b) => a.ts.localeCompare(b.ts))
    .map((entry) => {
      const change = entry.state_change ?? '';
      let status: AgentEvent['status'] = '';
      if (change.includes('CLOSED')) status = 'ok';
      else if (change.includes('REOPENED') || change.includes('UNVERIFIABLE')) status = 'crit';
      else if (change.includes('ESCALAT')) status = 'warn';
      else if (change.includes('ASSIGNED') || change.includes('ACKNOWLEDGED')) status = 'ok';
      else if (change.includes('VERIFYING')) status = 'live';

      return {
        time: fmtSeconds(entry.ts),
        status,
        message: entry.notes ?? change ?? entry.actor,
        tag: describeDecision(entry) || undefined,
      };
    });
}

/** One agent pass returns a node-by-node trace; the console shows it live. */
export function traceToAgentEvents(
  trace: Array<Record<string, unknown>>,
  ranAt: string,
): AgentEvent[] {
  return trace.map((node) => {
    const name = String(node.node ?? node.name ?? 'step');
    const detail = node.summary ?? node.detail ?? node.note ?? node.result;
    return {
      time: fmtSeconds(ranAt),
      status: node.halted ? 'warn' : '',
      message: name.replace(/_/g, ' '),
      tag: typeof detail === 'string' ? detail : undefined,
    };
  });
}

// ─── Anomalies ───────────────────────────────────────────────
export function anomalyToAgentEvent(anomaly: Anomaly): AgentEvent {
  const z = anomaly.z_score !== null ? `${anomaly.z_score.toFixed(1)}σ` : 'flat';
  return {
    time: fmtSeconds(anomaly.detected_at),
    status: anomaly.severity >= 0.66 ? 'crit' : 'warn',
    message: `${anomaly.metric} anomaly on ${anomaly.sensor_code ?? 'sensor'}`,
    tag: `residual ${z}`,
  };
}

// ─── Network map ─────────────────────────────────────────────
/** Where each Vitpur asset sits on the illustrated map. Assets the seed adds
 *  later fall back to a ring layout so nothing disappears from the console. */
const MAP_LAYOUT: Record<string, { x: number; y: number }> = {
  'SRC-01': { x: 120, y: 175 },
  'PMP-01': { x: 300, y: 275 },
  'OHT-01': { x: 520, y: 130 },
  'VLV-01': { x: 700, y: 250 },
  'VLV-02': { x: 620, y: 330 },
  'ZONE-A': { x: 850, y: 160 },
  'ZONE-B': { x: 820, y: 410 },
};

function fallbackPosition(index: number, total: number): { x: number; y: number } {
  const angle = (2 * Math.PI * index) / Math.max(1, total);
  return { x: 500 + 330 * Math.cos(angle), y: 270 + 170 * Math.sin(angle) };
}

const ASSET_STATUS: Record<BackendAssetStatus, AssetStatus> = {
  OPERATIONAL: 'normal',
  DEGRADED: 'warn',
  FAILED: 'critical',
  UNDER_REPAIR: 'maintenance',
  DECOMMISSIONED: 'offline',
};

const ASSET_TYPE: Record<BackendAsset['asset_type'], Asset['type']> = {
  SOURCE: 'source',
  PUMP: 'pump',
  TANK: 'oht',
  VALVE: 'valve',
  ZONE: 'distribution_point',
  PIPELINE: 'pipe',
  TREATMENT: 'junction',
  METER: 'sensor',
};

/** A live map node: seed geometry, live status, live sensor readout. */
export function toMapAsset(
  asset: BackendAsset,
  {
    index = 0,
    total = 1,
    sensors = [],
    incidentSeverity,
    untrustedSensors,
  }: {
    index?: number;
    total?: number;
    sensors?: BackendSensorWithLatest[];
    incidentSeverity?: Severity;
    untrustedSensors?: Set<string>;
  } = {},
): Asset {
  const pos = MAP_LAYOUT[asset.asset_code] ?? fallbackPosition(index, total);
  const mine = sensors.filter((s) => s.asset_id === asset.id);

  let status: AssetStatus = ASSET_STATUS[asset.status] ?? 'normal';
  if (incidentSeverity === 'crit') status = 'critical';
  else if (incidentSeverity === 'warn' && status === 'normal') status = 'warn';
  // An asset whose every instrument is untrusted is not "normal"; it is unseen.
  if (untrustedSensors && mine.length > 0 && mine.every((s) => untrustedSensors.has(s.sensor_code))) {
    status = 'offline';
  }

  const readout = mine
    .filter((s) => s.latest?.value !== null && s.latest?.value !== undefined)
    .slice(0, 3)
    .map((s) => `${s.sensor_type.toLowerCase().replace('_', ' ')} ${s.latest!.value!.toFixed(1)} ${s.unit}`)
    .join(' · ');

  return {
    id: asset.asset_code,
    name: asset.name,
    type: ASSET_TYPE[asset.asset_type] ?? 'junction',
    status,
    zone: asset.asset_code.startsWith('ZONE-') ? asset.asset_code.replace('ZONE-', '') : '',
    latitude: asset.latitude ?? 0,
    longitude: asset.longitude ?? 0,
    detail: readout || `${asset.asset_type} · ${asset.status.toLowerCase()}`,
    health_score: status === 'critical' ? 45 : status === 'warn' ? 72 : status === 'offline' ? 30 : 92,
    x: pos.x,
    y: pos.y,
    metadata: asset.metadata as Record<string, string | number>,
  };
}

/** Backend edges reference asset UUIDs; the map draws in asset codes. */
export function toMapEdge(
  edge: { from_asset_id: string; to_asset_id: string; connection_type: string; length_m: number | null },
  assets: Map<string, BackendAsset>,
  deadAssets: Set<string>,
) {
  const from = assets.get(edge.from_asset_id);
  const to = assets.get(edge.to_asset_id);
  return {
    from_asset_id: from?.asset_code ?? '',
    to_asset_id: to?.asset_code ?? '',
    pipe_type: edge.connection_type.toLowerCase(),
    length_m: edge.length_m ?? 0,
    status: (to && deadAssets.has(to.asset_code) ? 'dead' : 'active') as 'active' | 'dead' | 'restricted',
  };
}

// ─── Sensor health ───────────────────────────────────────────
export function untrustedSet(health: SensorHealth[]): Set<string> {
  return new Set(health.filter((h) => !h.trusted).map((h) => h.sensor_code));
}
