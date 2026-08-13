/* ============================================================
   JAL-SAKSHI — HTTP client

   One place that knows the base URL, how long to wait, and what a failure
   looks like. Everything else calls `endpoints.ts`.
   ============================================================ */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '') ?? 'http://localhost:8000/api/v1';

/** Default request timeout. The console polls, so a slow request is a dead one. */
const TIMEOUT_MS = 12_000;

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly path: string;

  constructor(path: string, status: number, detail: string) {
    super(`${status} ${path}: ${detail}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.path = path;
  }

  /** 503 means the backend is up but Supabase is not configured. */
  get isUnconfigured(): boolean {
    return this.status === 503;
  }

  get isOffline(): boolean {
    return this.status === 0;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.append(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function request<T>(
  method: 'GET' | 'POST',
  path: string,
  { query, body, signal }: { query?: Query; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const url = `${API_BASE}${withQuery(path, query)}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);

  // Caller-cancelled (component unmounted) and timed-out both abort this fetch.
  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort);

  try {
    const response = await fetch(url, {
      method,
      signal: controller.signal,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
    });

    if (!response.ok) {
      let detail = response.statusText;
      try {
        const payload = await response.json();
        if (typeof payload?.detail === 'string') detail = payload.detail;
        else if (payload?.detail) detail = JSON.stringify(payload.detail);
      } catch {
        /* the body was not JSON; the status line is all we have */
      }
      throw new ApiError(path, response.status, detail);
    }

    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    // Network failure, DNS, CORS, or timeout — status 0 means "no backend".
    const message = error instanceof Error ? error.message : String(error);
    throw new ApiError(path, 0, message);
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', onAbort);
  }
}

export function apiGet<T>(
  path: string,
  options: { query?: Query; signal?: AbortSignal } = {},
): Promise<T> {
  return request<T>('GET', path, options);
}

export function apiPost<T>(
  path: string,
  options: { query?: Query; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  return request<T>('POST', path, options);
}
