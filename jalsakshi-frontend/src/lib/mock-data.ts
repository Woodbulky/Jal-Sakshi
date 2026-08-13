/* ============================================================
   JAL-SAKSHI - Offline fallback data (Vitpur illustration)

   This is NOT the demo data. The real Vitpur service area lives in Supabase
   and reaches the console through `lib/api`. What remains here is the small
   set the UI falls back to when the backend cannot be reached, so a dropped
   connection shows a stale-but-legible console instead of an empty one.

   Anything the backend serves - work orders, verification checks, escalations,
   asset health, telemetry bands - was deleted rather than left to drift out of
   sync with the API.
   ============================================================ */
import type { Incident, AgentEvent, Asset, AssetConnection } from '@/types/api';

// ─── Incidents ───────────────────────────────────────────────
export const INCIDENTS: Incident[] = [
  {
    id: 'INC-2025-0587', asset_id: 'VLV-07', fault_type: 'Valve Closure',
    severity: 'crit', households_affected: 212, status: 'In Repair',
    sla_remaining_seconds: 13147, icon: '#i-valve', detected_at: '10:33 AM, 12 May 2025',
    classification_confidence: 91, vulnerable_facilities: ['school', 'PHC'], zone: 'A',
  },
  {
    id: 'INC-2025-0591', asset_id: 'OHT-01', fault_type: 'Filling Stalled',
    severity: 'crit', households_affected: 486, status: 'Assigned',
    sla_remaining_seconds: 8420, icon: '#i-tank', detected_at: '11:15 AM, 12 May 2025',
    classification_confidence: 87, vulnerable_facilities: [], zone: 'B',
  },
  {
    id: 'INC-2025-0593', asset_id: 'DP-D2', fault_type: 'Pressure Anomaly',
    severity: 'warn', households_affected: 118, status: 'Diagnosing',
    sla_remaining_seconds: 19880, icon: '#i-pipe', detected_at: '09:42 AM, 12 May 2025',
    classification_confidence: 72, vulnerable_facilities: [], zone: 'D',
  },
  {
    id: 'INC-2025-0594', asset_id: 'SEN-C4', fault_type: 'Sensor Offline',
    severity: 'warn', households_affected: 0, status: 'Acknowledged',
    sla_remaining_seconds: 24600, icon: '#i-asset', detected_at: '06:21 AM, 12 May 2025',
    classification_confidence: 99, vulnerable_facilities: [], zone: 'C',
  }
];

// ─── Agent Events ────────────────────────────────────────────
export const AGENT_INITIAL_EVENTS: AgentEvent[] = [
  { time: '10:33:12', status: 'warn', message: 'Sensor anomaly detected', tag: 'VLV-07 · flow residual 3.4σ' },
  { time: '10:33:18', status: 'ok', message: 'Sensor integrity confirmed', tag: 'FM-02 / PT-04 / PT-11 agree' },
  { time: '10:33:26', status: '', message: 'Analyzing flow/pressure signature', tag: '14-day seasonal baseline' },
  { time: '10:33:38', status: 'crit', message: 'Fault classified: Valve Closure', tag: 'confidence 91%' },
  { time: '10:33:41', status: '', message: 'Impact modelled: 212 households', tag: '1 school · 1 PHC' },
  { time: '10:33:45', status: '', message: 'Checking VWSC balance', tag: '₹48,750 available' },
  { time: '10:33:52', status: '', message: 'Selecting field operator', tag: 'Jal Mitra Ramesh · 2.1 km' },
  { time: '10:33:58', status: 'ok', message: 'Work order created WO-2025-0712', tag: 'SLA 4 h' },
  { time: '10:34:05', status: 'ok', message: 'Telegram notification sent', tag: 'delivered' },
  { time: '10:34:07', status: 'live', message: 'SLA running', tag: 'watching restoration signal' },
];

// ─── Assets (Network Map) ────────────────────────────────────
export const ASSETS: Asset[] = [
  { id: 'SRC-01', name: 'Borewell Source', type: 'source', status: 'normal', zone: '', latitude: 23.148, longitude: 77.109, detail: 'Yield 1,320 LPM · Static level 42 m', health_score: 91, x: 120, y: 175 },
  { id: 'PUMP-01', name: 'Pump House 01', type: 'pump', status: 'normal', zone: '', latitude: 23.148, longitude: 77.109, detail: 'Running · 4.2 kW · 1,250 LPM', health_score: 88, x: 300, y: 275 },
  { id: 'OHT-01', name: 'Overhead Tank 01', type: 'oht', status: 'warn', zone: '', latitude: 23.148, longitude: 77.109, detail: 'Level 148 KL / 200 KL · Filling stalled', health_score: 74, x: 520, y: 130 },
  { id: 'JCT-03', name: 'Junction 03', type: 'junction', status: 'normal', zone: '', latitude: 23.148, longitude: 77.109, detail: 'Distribution junction · pressure 18.4 m', health_score: 95, x: 640, y: 210 },
  { id: 'VLV-07', name: 'Valve VLV-07', type: 'valve', status: 'critical', zone: 'A', latitude: 23.148, longitude: 77.109, detail: 'CLOSED · Zone A isolated · 212 households', health_score: 62, x: 730, y: 275 },
  { id: 'DP-A1', name: 'Zone A Distribution', type: 'distribution_point', status: 'critical', zone: 'A', latitude: 23.148, longitude: 77.109, detail: 'No flow · 212 households affected', health_score: 45, x: 830, y: 155 },
  { id: 'TAP-A9', name: 'Zone A Tail-End', type: 'tap', status: 'critical', zone: 'A', latitude: 23.148, longitude: 77.109, detail: 'Tail-end pressure 8.2 m (expected 18–22 m)', health_score: 40, x: 905, y: 120 },
  { id: 'DP-D2', name: 'Zone D Distribution', type: 'distribution_point', status: 'warn', zone: 'D', latitude: 23.148, longitude: 77.109, detail: 'Pressure elevated 31.8 m — back-pressure from Zone A', health_score: 70, x: 600, y: 300 },
  { id: 'DP-B1', name: 'Zone B Distribution', type: 'distribution_point', status: 'normal', zone: 'B', latitude: 23.148, longitude: 77.109, detail: 'Normal · 19.4 m · 386 households', health_score: 92, x: 800, y: 400 },
  { id: 'TAP-B7', name: 'Zone B Tail-End', type: 'tap', status: 'normal', zone: 'B', latitude: 23.148, longitude: 77.109, detail: 'Normal · 18.9 m', health_score: 90, x: 870, y: 430 },
  { id: 'DP-C1', name: 'Zone C Distribution', type: 'distribution_point', status: 'normal', zone: 'C', latitude: 23.148, longitude: 77.109, detail: 'Normal · 20.1 m · 412 households', health_score: 88, x: 400, y: 330 },
  { id: 'SEN-C4', name: 'Sensor SEN-C4', type: 'sensor', status: 'offline', zone: 'C', latitude: 23.148, longitude: 77.109, detail: 'Telemetry offline 04h 12m · battery fault', health_score: 30, x: 250, y: 450 },
];

export const ASSET_CONNECTIONS: AssetConnection[] = [
  { from_asset_id: 'SRC-01', to_asset_id: 'PUMP-01', pipe_type: 'trunk', length_m: 200, status: 'active' },
  { from_asset_id: 'PUMP-01', to_asset_id: 'OHT-01', pipe_type: 'trunk', length_m: 300, status: 'active' },
  { from_asset_id: 'OHT-01', to_asset_id: 'JCT-03', pipe_type: 'distribution', length_m: 150, status: 'active' },
  { from_asset_id: 'JCT-03', to_asset_id: 'VLV-07', pipe_type: 'distribution', length_m: 100, status: 'restricted' },
  { from_asset_id: 'VLV-07', to_asset_id: 'DP-A1', pipe_type: 'distribution', length_m: 120, status: 'dead' },
  { from_asset_id: 'DP-A1', to_asset_id: 'TAP-A9', pipe_type: 'distribution', length_m: 80, status: 'dead' },
  { from_asset_id: 'JCT-03', to_asset_id: 'DP-D2', pipe_type: 'distribution', length_m: 120, status: 'active' },
  { from_asset_id: 'OHT-01', to_asset_id: 'DP-C1', pipe_type: 'distribution', length_m: 250, status: 'active' },
  { from_asset_id: 'DP-C1', to_asset_id: 'SEN-C4', pipe_type: 'distribution', length_m: 180, status: 'active' },
  { from_asset_id: 'VLV-07', to_asset_id: 'DP-B1', pipe_type: 'distribution', length_m: 150, status: 'active' },
  { from_asset_id: 'DP-B1', to_asset_id: 'TAP-B7', pipe_type: 'distribution', length_m: 70, status: 'active' },
];
