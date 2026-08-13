'use client';
import { useCallback, useMemo, useState } from 'react';
import { listAnomalies, listDecisions, runAgent } from '@/lib/api/endpoints';
import { anomalyToAgentEvent, toAgentEvents, traceToAgentEvents } from '@/lib/adapters';
import type { AgentEvent } from '@/types/api';
import type { AgentRunResponse } from '@/types/backend';
import { useApiResource } from './useApiResource';

const pad = (n: number) => String(n).padStart(2, '0');

function currentTime(): string {
  const d = new Date();
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/**
 * The agent activity feed, from the decision ledger.
 *
 * The ledger is the product's accountability record — "why did this happen?"
 * answered without the model — so the console reads it rather than inventing
 * a narration. Anomalies are folded in so the feed still moves during the
 * long stretches when the agent correctly does nothing.
 *
 * `run()` advances the loop one pass and splices its trace in immediately,
 * before the next poll catches up.
 */
export function useAgentStream(intervalMs = 6_000) {
  const decisions = useApiResource(
    (signal) => listDecisions({ limit: 100, signal }),
    { intervalMs },
  );
  const anomalies = useApiResource(
    (signal) => listAnomalies({ hours: 6, limit: 40, signal }),
    { intervalMs: intervalMs * 2 },
  );

  const live = decisions.data !== null;

  // Events produced locally: an agent run's trace, and operator actions.
  const [local, setLocal] = useState<AgentEvent[]>([]);
  const [lastRun, setLastRun] = useState<AgentRunResponse | null>(null);
  const [running, setRunning] = useState(false);

  const events = useMemo(() => {
    if (!live) {
      // Only what this session actually produced. A scripted narration used to
      // play here when the ledger could not be read, which put invented agent
      // reasoning in the one panel whose entire purpose is to show the real
      // decision trail. An empty panel is the honest answer.
      return [...local];
    }

    const ledger = toAgentEvents(decisions.data ?? []);
    const noise = (anomalies.data ?? []).map(anomalyToAgentEvent);
    const merged = [...ledger, ...noise, ...local].sort((a, b) =>
      a.time.localeCompare(b.time),
    );
    return merged.slice(-60);
  }, [live, decisions.data, anomalies.data, local]);

  const pushEvent = useCallback(
    (status: AgentEvent['status'], message: string, tag?: string) => {
      setLocal((prev) => [...prev, { time: currentTime(), status, message, tag }].slice(-40));
    },
    [],
  );

  const run = useCallback(async () => {
    setRunning(true);
    try {
      const result = await runAgent();
      setLastRun(result);
      setLocal((prev) => [...prev, ...traceToAgentEvents(result.trace, result.ran_at)].slice(-40));
      if (result.halted) {
        pushEvent('warn', 'Agent halted — waiting on a human', result.halted);
      }
      decisions.refresh();
      return result;
    } catch (error) {
      pushEvent('crit', 'Agent pass failed', error instanceof Error ? error.message : undefined);
      return null;
    } finally {
      setRunning(false);
    }
  }, [decisions, pushEvent]);

  return { events, pushEvent, run, running, lastRun, live, decisions: decisions.data ?? [] };
}
