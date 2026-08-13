'use client';
import { getHealth } from '@/lib/api/endpoints';
import { useApiResource } from './useApiResource';

export type BackendState = 'checking' | 'live' | 'degraded' | 'offline';

/**
 * Whether the console is showing real data.
 *
 * `degraded` means FastAPI answered but Supabase is not configured, so the
 * data endpoints return 503. Saying so is better than an empty dashboard that
 * looks like a healthy network.
 */
export function useBackendStatus(intervalMs = 20_000) {
  const { data, error, settled } = useApiResource(
    (signal) => getHealth({ signal }),
    { intervalMs },
  );

  let state: BackendState = 'checking';
  if (error) state = 'offline';
  else if (data) state = data.status === 'ok' ? 'live' : 'degraded';
  else if (settled) state = 'offline';

  return {
    state,
    live: state === 'live',
    health: data,
    label:
      state === 'live' ? 'Live'
        : state === 'degraded' ? 'Database unconfigured'
          : state === 'offline' ? 'Backend offline — demo data'
            : 'Connecting…',
    badgeClass:
      state === 'live' ? 'b-normal'
        : state === 'degraded' ? 'b-warn'
          : state === 'offline' ? 'b-crit'
            : 'b-neutral',
  };
}
