'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api/client';

export interface ApiResource<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  /** True once a request has come back, successfully or not. */
  settled: boolean;
  /** True when the last request failed because nothing answered. */
  offline: boolean;
  refresh: () => void;
}

/**
 * Poll one endpoint.
 *
 * The realtime channel in the API contract is not built yet (Claude Code task
 * 11), so the console polls. The interface here is the same one a WebSocket
 * push would fill, so swapping transports later does not touch the pages.
 *
 * `deps` must be stable — the fetcher is re-run whenever they change.
 */
export function useApiResource<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  {
    intervalMs = 0,
    enabled = true,
    deps = [] as unknown[],
  }: { intervalMs?: number; enabled?: boolean; deps?: unknown[] } = {},
): ApiResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [settled, setSettled] = useState(false);
  const [nonce, setNonce] = useState(0);

  // Callers pass an inline arrow, so the fetcher is a new function every
  // render. Keeping the latest one in a ref lets the polling effect depend on
  // the query's inputs rather than on the closure's identity.
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) return;

    const controller = new AbortController();
    let cancelled = false;

    const run = async () => {
      try {
        const result = await fetcherRef.current(controller.signal);
        if (cancelled) return;
        setData(result);
        setError(null);
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        setError(err instanceof ApiError ? err : new ApiError('?', 0, String(err)));
      } finally {
        if (!cancelled) setSettled(true);
      }
    };

    run();
    const timer = intervalMs > 0 ? setInterval(run, intervalMs) : null;

    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, nonce, ...deps]);

  return {
    data,
    error,
    // "Loading" is the window before the first response, not every poll.
    loading: enabled && !settled,
    settled,
    offline: error?.isOffline ?? false,
    refresh,
  };
}
