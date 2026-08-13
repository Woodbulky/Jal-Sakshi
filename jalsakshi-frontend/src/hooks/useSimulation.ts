'use client';
import { useCallback, useState } from 'react';
import {
  backfillSimulation,
  clearAllInjections,
  clearInjection,
  getSimulationStatus,
  injectFault,
  pauseSimulation,
  runDetection,
  startSimulation,
  tickSimulation,
} from '@/lib/api/endpoints';
import type { BackendFaultType } from '@/types/backend';
import { useApiResource } from './useApiResource';

/**
 * The demo console's control surface.
 *
 * Everything here is the *operator's* half of the system: it knows which fault
 * was injected. Nothing the agent reads comes through this hook — the console
 * shows ground truth beside the agent's independent diagnosis so an audience
 * can see whether the two agree.
 */
export function useSimulation({ intervalMs = 5_000 } = {}) {
  const status = useApiResource((signal) => getSimulationStatus({ signal }), {
    intervalMs,
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);

  const act = useCallback(
    async <T,>(name: string, fn: () => Promise<T>): Promise<T | null> => {
      setBusy(name);
      setLastError(null);
      try {
        return await fn();
      } catch (error) {
        setLastError(error instanceof Error ? error.message : String(error));
        return null;
      } finally {
        setBusy(null);
        status.refresh();
      }
    },
    [status],
  );

  return {
    status: status.data,
    running: status.data?.running ?? false,
    injections: status.data?.active_injections ?? [],
    live: status.data !== null,
    busy,
    lastError,
    refresh: status.refresh,

    start: () => act('start', startSimulation),
    pause: () => act('pause', pauseSimulation),
    tick: () => act('tick', tickSimulation),
    /** Writes a healthy history so detection has a baseline to compare to. */
    backfill: (hours = 48) => act('backfill', () => backfillSimulation({ hours })),
    inject: (faultType: BackendFaultType, assetId?: string) =>
      act('inject', () => injectFault(faultType, { assetId })),
    /** 'Simulate repair': the pipe is fixed, the work order is not closed. */
    clear: (injectionId: string) => act('clear', () => clearInjection(injectionId)),
    clearAll: () => act('clearAll', clearAllInjections),
    detect: () => act('detect', () => runDetection({})),
  };
}
