/* ============================================================
   JAL-SAKSHI — typed endpoint functions

   One function per route in shared/API_CONTRACT.md. Nothing here transforms
   data: the shapes are exactly what FastAPI returns (see types/backend.ts).
   ============================================================ */
import { apiGet, apiPost } from './client';
import type {
  AgentRunResponse,
  Anomaly,
  AssetHealthDetail,
  AssetHealthRecord,
  AssetTelemetryResponse,
  BackendSensorReading,
  BackendServiceArea,
  BackendWorkOrder,
  BackendWorkOrderStatus,
  BackfillResult,
  BaselineBand,
  CrewMember,
  CrewRole,
  DashboardSummary,
  DecisionEntry,
  DetectionRun,
  FaultInjection,
  BackendFaultType,
  FaultEvent,
  HealthResponse,
  IncidentDetail,
  NetworkResponse,
  SensorHealth,
  SimulationStatus,
  VerificationReport,
  WorkOrderDetail,
} from '@/types/backend';

/** The demo service area. Every list endpoint scopes to it by default. */
export const SERVICE_AREA = 'demo-vitpur';

type Opt = { signal?: AbortSignal };

// ─── Health & summary ────────────────────────────────────────
export const getHealth = (o: Opt = {}) =>
  apiGet<HealthResponse>('/health', o);

export const getDashboardSummary = (hours = 72, o: Opt = {}) =>
  apiGet<DashboardSummary>('/dashboard/summary', { query: { hours }, ...o });

// ─── Service areas & network ─────────────────────────────────
export const listServiceAreas = (o: Opt = {}) =>
  apiGet<BackendServiceArea[]>('/service-areas', o);

export const getServiceArea = (ref = SERVICE_AREA, o: Opt = {}) =>
  apiGet<BackendServiceArea>(`/service-areas/${ref}`, o);

export const getNetwork = (ref = SERVICE_AREA, o: Opt = {}) =>
  apiGet<NetworkResponse>(`/service-areas/${ref}/network`, o);

// ─── Telemetry ───────────────────────────────────────────────
export const getAssetTelemetry = (
  assetRef: string,
  { hours = 6, limit = 2000, ...o }: Opt & { hours?: number; limit?: number } = {},
) =>
  apiGet<AssetTelemetryResponse>(`/assets/${assetRef}/telemetry`, {
    query: { hours, limit },
    ...o,
  });

export const getSensorReadings = (
  sensorRef: string,
  { hours = 6, limit = 120, ...o }: Opt & { hours?: number; limit?: number } = {},
) =>
  apiGet<BackendSensorReading[]>(`/sensors/${sensorRef}/readings`, {
    query: { hours, limit },
    ...o,
  });

// ─── Asset health ────────────────────────────────────────────
export const getAssetHealth = (
  assetRef: string,
  { days = 365, ...o }: Opt & { days?: number } = {},
) => apiGet<AssetHealthDetail>(`/assets/${assetRef}/health`, { query: { days }, ...o });

export const listAssetHealth = (o: Opt = {}) =>
  apiGet<AssetHealthRecord[]>('/asset-health', o);

// ─── Detection ───────────────────────────────────────────────
export const runDetection = (
  { persist = true, refreshBaseline = false, ...o }:
    Opt & { persist?: boolean; refreshBaseline?: boolean } = {},
) =>
  apiPost<DetectionRun>('/detection/run', {
    query: { persist, refresh_baseline: refreshBaseline },
    ...o,
  });

export const getDetectionStatus = (o: Opt = {}) =>
  apiGet<DetectionRun | null>('/detection/status', o);

export const getSensorHealth = (o: Opt = {}) =>
  apiGet<SensorHealth[]>('/detection/sensor-health', o);

export const getBaselineBand = (sensorRef: string, o: Opt = {}) =>
  apiGet<BaselineBand>(`/detection/baseline/${sensorRef}/band`, o);

export const listAnomalies = (
  { hours = 24, limit = 200, ...o }: Opt & { hours?: number; limit?: number } = {},
) => apiGet<Anomaly[]>('/anomalies', { query: { hours, limit }, ...o });

// ─── Incidents ───────────────────────────────────────────────
export const listIncidents = (
  { hours = 72, limit = 100, status, ...o }:
    Opt & { hours?: number; limit?: number; status?: string } = {},
) => apiGet<FaultEvent[]>('/incidents', { query: { hours, limit, status }, ...o });

export const getIncident = (incidentId: string, o: Opt = {}) =>
  apiGet<IncidentDetail>(`/incidents/${incidentId}`, o);

// ─── Work orders ─────────────────────────────────────────────
export const listWorkOrders = (
  { openOnly = false, limit = 100, status, ...o }:
    Opt & { openOnly?: boolean; limit?: number; status?: BackendWorkOrderStatus } = {},
) =>
  apiGet<BackendWorkOrder[]>('/work-orders', {
    query: { open_only: openOnly, limit, status },
    ...o,
  });

export const getRoster = (o: Opt = {}) =>
  apiGet<CrewMember[]>('/work-orders/roster', o);

/** `ref` may be a UUID or a code ('WO-001'). */
export const getWorkOrder = (ref: string, o: Opt = {}) =>
  apiGet<WorkOrderDetail>(`/work-orders/${ref}`, o);

export const createWorkOrder = (
  faultEventId: string,
  { assetCode, ...o }: Opt & { assetCode?: string } = {},
) =>
  apiPost<BackendWorkOrder>('/work-orders', {
    body: { fault_event_id: faultEventId, asset_code: assetCode },
    ...o,
  });

export const assignWorkOrder = (
  ref: string,
  body: {
    role?: CrewRole;
    person?: string;
    telegram_chat_id?: string;
    phone?: string;
    fault_type?: BackendFaultType;
  } = {},
  o: Opt = {},
) => apiPost<BackendWorkOrder>(`/work-orders/${ref}/assign`, { body, ...o });

export const approveWorkOrder = (ref: string, approvedBy: string, o: Opt = {}) =>
  apiPost<BackendWorkOrder>(`/work-orders/${ref}/approve`, {
    body: { approved_by: approvedBy },
    ...o,
  });

export const acknowledgeWorkOrder = (ref: string, by?: string, o: Opt = {}) =>
  apiPost<BackendWorkOrder>(`/work-orders/${ref}/acknowledge`, {
    query: { by },
    ...o,
  });

export const escalateWorkOrder = (
  ref: string,
  reason = 'escalated by an operator',
  o: Opt = {},
) => apiPost<BackendWorkOrder>(`/work-orders/${ref}/escalate`, { body: { reason }, ...o });

/** The inbound half of the n8n/Telegram contract. Cannot close anything. */
export const sendFieldUpdate = (
  ref: string,
  message: string,
  sender?: string,
  o: Opt = {},
) =>
  apiPost<BackendWorkOrder>(`/work-orders/${ref}/field-update`, {
    body: { message, sender },
    ...o,
  });

/** Reads the sensors. The only path to CLOSED in the system. */
export const verifyWorkOrder = (
  ref: string,
  { faultType = 'UNKNOWN' as BackendFaultType, ...o }:
    Opt & { faultType?: BackendFaultType } = {},
) =>
  apiPost<VerificationReport>(`/work-orders/${ref}/verify`, {
    body: { fault_type: faultType },
    ...o,
  });

export const reopenWorkOrder = (
  ref: string,
  reason = 'reopened by an operator',
  o: Opt = {},
) => apiPost<BackendWorkOrder>(`/work-orders/${ref}/reopen`, { query: { reason }, ...o });

// ─── Agent ───────────────────────────────────────────────────
export const runAgent = (o: Opt = {}) =>
  apiPost<AgentRunResponse>('/agent/run', o);

export const listDecisions = (
  { workOrderId, faultEventId, limit = 100, ...o }:
    Opt & { workOrderId?: string; faultEventId?: string; limit?: number } = {},
) =>
  apiGet<DecisionEntry[]>('/agent/decisions', {
    query: { work_order_id: workOrderId, fault_event_id: faultEventId, limit },
    ...o,
  });

// ─── Simulation ──────────────────────────────────────────────
export const getSimulationStatus = (o: Opt = {}) =>
  apiGet<SimulationStatus>('/simulation/status', o);

export const startSimulation = (o: Opt = {}) =>
  apiPost<SimulationStatus>('/simulation/start', o);

export const pauseSimulation = (o: Opt = {}) =>
  apiPost<SimulationStatus>('/simulation/pause', o);

export const tickSimulation = (o: Opt = {}) =>
  apiPost<SimulationStatus>('/simulation/tick', o);

export const backfillSimulation = (
  { hours = 48, stepMinutes = 5, ...o }:
    Opt & { hours?: number; stepMinutes?: number } = {},
) =>
  apiPost<BackfillResult>('/simulation/backfill', {
    query: { hours, step_minutes: stepMinutes },
    ...o,
  });

export const injectFault = (
  faultType: BackendFaultType,
  { assetId, ...o }: Opt & { assetId?: string } = {},
) =>
  apiPost<FaultInjection>('/simulation/inject', {
    body: {
      service_area_id: SERVICE_AREA,
      fault_type: faultType,
      asset_id: assetId,
    },
    ...o,
  });

export const listInjections = (
  { activeOnly = false, ...o }: Opt & { activeOnly?: boolean } = {},
) =>
  apiGet<FaultInjection[]>('/simulation/injections', {
    query: { active_only: activeOnly },
    ...o,
  });

/** 'Simulate repair'. Recovers the telemetry; closes nothing. */
export const clearInjection = (injectionId: string, o: Opt = {}) =>
  apiPost<FaultInjection>(`/simulation/injections/${injectionId}/clear`, o);

export const clearAllInjections = (o: Opt = {}) =>
  apiPost<FaultInjection[]>('/simulation/injections/clear-all', o);
