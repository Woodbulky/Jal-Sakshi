'use client';
import { useCallback, useMemo, useState } from 'react';
import {
  acknowledgeWorkOrder,
  escalateWorkOrder,
  getIncident,
  getNetwork,
  getWorkOrder,
  listWorkOrders,
  reopenWorkOrder,
  sendFieldUpdate,
  verifyWorkOrder,
} from '@/lib/api/endpoints';
import {
  assetsById,
  slaRemainingSeconds,
  toEscalationEntries,
  toWorkOrderView,
} from '@/lib/adapters';
import type { VerificationReport } from '@/types/backend';
import { useApiResource } from './useApiResource';
import { useNow } from './useNow';

/** Every work order in the service area, newest first. */
export function useWorkOrders({ intervalMs = 8_000, openOnly = false } = {}) {
  const orders = useApiResource(
    (signal) => listWorkOrders({ openOnly, limit: 200, signal }),
    { intervalMs, deps: [openOnly] },
  );

  const sorted = useMemo(
    () =>
      [...(orders.data ?? [])].sort((a, b) =>
        (b.created_at ?? '').localeCompare(a.created_at ?? ''),
      ),
    [orders.data],
  );

  return {
    orders: sorted,
    live: orders.data !== null,
    loading: orders.loading,
    error: orders.error,
    refresh: orders.refresh,
  };
}

/**
 * One work order with everything the console shows beside it, plus the actions
 * that move it.
 *
 * There is no `close()` here, deliberately: `verify()` reads the sensors and
 * the backend closes the order only if they agree.
 */
export function useWorkOrder(ref: string | null, { intervalMs = 6_000 } = {}) {
  const detail = useApiResource(
    (signal) => getWorkOrder(ref!, { signal }),
    { intervalMs, enabled: Boolean(ref), deps: [ref] },
  );

  const network = useApiResource((signal) => getNetwork(undefined, { signal }), {
    intervalMs: 60_000,
  });

  const eventId = detail.data?.work_order.fault_event_id ?? null;
  const incident = useApiResource(
    (signal) => getIncident(eventId!, { signal }),
    { enabled: Boolean(eventId), deps: [eventId] },
  );

  const now = useNow(1000);
  const [report, setReport] = useState<VerificationReport | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const view = useMemo(() => {
    if (!detail.data) return null;
    const assets = network.data ? assetsById(network.data.nodes) : new Map();
    const order = detail.data.work_order;
    return toWorkOrderView(order, {
      assignments: detail.data.assignments,
      decisions: detail.data.decisions,
      asset: order.asset_id ? assets.get(order.asset_id) : undefined,
      event: incident.data ?? undefined,
    });
  }, [detail.data, network.data, incident.data]);

  const escalations = useMemo(
    () =>
      detail.data
        ? toEscalationEntries(detail.data.escalations, detail.data.work_order)
        : [],
    [detail.data],
  );

  const act = useCallback(
    async <T,>(name: string, fn: () => Promise<T>): Promise<T | null> => {
      setBusy(name);
      try {
        const result = await fn();
        detail.refresh();
        return result;
      } catch {
        return null;
      } finally {
        setBusy(null);
      }
    },
    [detail],
  );

  const actions = useMemo(
    () => ({
      acknowledge: (by?: string) =>
        ref ? act('acknowledge', () => acknowledgeWorkOrder(ref, by)) : null,
      escalate: (reason?: string) =>
        ref ? act('escalate', () => escalateWorkOrder(ref, reason)) : null,
      /** The n8n/Telegram inbound half. "Fixed" starts verification. */
      fieldUpdate: (message: string, sender?: string) =>
        ref ? act('fieldUpdate', () => sendFieldUpdate(ref, message, sender)) : null,
      reopen: (reason?: string) =>
        ref ? act('reopen', () => reopenWorkOrder(ref, reason)) : null,
      verify: async () => {
        if (!ref) return null;
        const result = await act('verify', () => verifyWorkOrder(ref));
        if (result) setReport(result);
        return result;
      },
    }),
    [ref, act],
  );

  return {
    detail: detail.data,
    order: detail.data?.work_order ?? null,
    view,
    escalations,
    decisions: detail.data?.decisions ?? [],
    incident: incident.data ?? null,
    slaRemaining: slaRemainingSeconds(detail.data?.work_order, now),
    report,
    busy,
    live: detail.data !== null,
    loading: detail.loading,
    error: detail.error,
    refresh: detail.refresh,
    ...actions,
  };
}
