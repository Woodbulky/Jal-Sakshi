'use client';
import { useMemo } from 'react';
import {
  getDashboardSummary,
  getIncident,
  getNetwork,
  listDecisions,
  listIncidents,
  listWorkOrders,
} from '@/lib/api/endpoints';
import {
  assetsById,
  ordersByEvent,
  severityFromScore,
  slaRemainingSeconds,
  toIncident,
} from '@/lib/adapters';
import type { Incident, Severity } from '@/types/api';
import type { BackendWorkOrder, DashboardSummary, FaultEvent } from '@/types/backend';
import { useApiResource } from './useApiResource';
import { useNow } from './useNow';

const pad = (n: number) => String(n).padStart(2, '0');

/** `hh:mm:ss` for the SLA pill. */
export function slaStr(s: number): string {
  const v = Math.max(0, Math.floor(s));
  return `${pad(Math.floor(v / 3600))}:${pad(Math.floor((v % 3600) / 60))}:${pad(v % 60)}`;
}

export interface IncidentsResult {
  incidents: Incident[];
  events: FaultEvent[];
  orders: BackendWorkOrder[];
  summary: DashboardSummary | null;
  /** asset_code → severity, for colouring the map. */
  severityByAsset: Map<string, Severity>;
  live: boolean;
  loading: boolean;
  refresh: () => void;
}

/**
 * Open incidents with a live SLA clock.
 *
 * The list is polled; the countdown ticks locally every second so the number
 * on screen moves without hammering the API. Both agree because the deadline,
 * not the remaining time, is what the backend sends.
 */
export function useIncidents({ intervalMs = 8_000 } = {}): IncidentsResult {
  const incidents = useApiResource(
    (signal) => listIncidents({ hours: 72, limit: 100, signal }),
    { intervalMs },
  );
  const orders = useApiResource(
    (signal) => listWorkOrders({ limit: 200, signal }),
    { intervalMs },
  );
  const network = useApiResource((signal) => getNetwork(undefined, { signal }), {
    intervalMs: 60_000,
  });
  const summary = useApiResource(
    (signal) => getDashboardSummary(72, { signal }),
    { intervalMs },
  );

  // Re-render once a second so the SLA countdown advances between polls.
  const now = useNow(1000);

  const live = incidents.data !== null;

  const result = useMemo(() => {
    if (!incidents.data) {
      // Nothing, not something invented. This console used to fall back to a
      // sample incident list here, which meant an unreachable backend rendered
      // four confident diagnoses against assets the network does not contain.
      // On a system whose whole claim is that it reports evidence rather than
      // guesses, plausible filler is the one failure mode that must not exist:
      // an operator cannot tell it from a real reading. `live` is already false
      // in this state, so the UI can say so honestly.
      return {
        incidents: [] as Incident[],
        severityByAsset: new Map<string, Severity>(),
      };
    }

    const assets = network.data ? assetsById(network.data.nodes) : new Map();
    const byEvent = ordersByEvent(orders.data ?? []);
    const ctx = { assets, ordersByEvent: byEvent };

    const open = incidents.data.filter((event) => event.status !== 'RESOLVED');
    const list = open
      .map((event) => {
        const view = toIncident(event, ctx);
        // Recompute the countdown against the live clock, not the poll time.
        return {
          ...view,
          sla_remaining_seconds: slaRemainingSeconds(byEvent.get(event.id), now),
        };
      })
      .sort((a, b) => {
        const rank = { crit: 0, warn: 1, rest: 2, info: 3 };
        return rank[a.severity] - rank[b.severity] || a.sla_remaining_seconds - b.sla_remaining_seconds;
      });

    const severityByAsset = new Map<string, Severity>();
    for (const event of open) {
      const asset = event.asset_id ? assets.get(event.asset_id) : undefined;
      if (!asset) continue;
      severityByAsset.set(asset.asset_code, severityFromScore(event.severity_score));
    }

    return { incidents: list, severityByAsset };
  }, [incidents.data, orders.data, network.data, now]);

  return {
    incidents: result.incidents,
    events: incidents.data ?? [],
    orders: orders.data ?? [],
    summary: summary.data,
    severityByAsset: result.severityByAsset,
    live,
    loading: incidents.loading,
    refresh: () => {
      incidents.refresh();
      orders.refresh();
      summary.refresh();
    },
  };
}

/**
 * One incident: the classification, the anomalies behind it, the work order
 * opened for it and the agent's ledger entries about it.
 */
export function useIncident(incidentId: string | null, { intervalMs = 8_000 } = {}) {
  const incident = useApiResource(
    (signal) => getIncident(incidentId!, { signal }),
    { intervalMs, enabled: Boolean(incidentId), deps: [incidentId] },
  );
  const orders = useApiResource(
    (signal) => listWorkOrders({ limit: 200, signal }),
    { intervalMs, enabled: Boolean(incidentId) },
  );
  const network = useApiResource((signal) => getNetwork(undefined, { signal }), {
    intervalMs: 60_000,
    enabled: Boolean(incidentId),
  });
  const decisions = useApiResource(
    (signal) => listDecisions({ faultEventId: incidentId!, limit: 100, signal }),
    { intervalMs, enabled: Boolean(incidentId), deps: [incidentId] },
  );

  const now = useNow(1000);

  const order = useMemo(
    () => (incident.data ? ordersByEvent(orders.data ?? []).get(incident.data.id) ?? null : null),
    [incident.data, orders.data],
  );

  const asset = useMemo(() => {
    if (!incident.data?.asset_id || !network.data) return null;
    return assetsById(network.data.nodes).get(incident.data.asset_id) ?? null;
  }, [incident.data, network.data]);

  return {
    incident: incident.data,
    asset,
    order,
    decisions: decisions.data ?? [],
    anomalies: incident.data?.anomalies ?? [],
    slaRemaining: slaRemainingSeconds(order ?? undefined, now),
    live: incident.data !== null,
    loading: incident.loading,
    error: incident.error,
    refresh: incident.refresh,
  };
}

/** Elapsed time on the incident the console is watching, as `03h 42m`. */
export function activeTTWR(summary: DashboardSummary | null): string {
  if (!summary?.active_ttwr_minutes) return '00h 00m';
  const total = Math.round(summary.active_ttwr_minutes);
  return `${pad(Math.floor(total / 60))}h ${pad(total % 60)}m`;
}
