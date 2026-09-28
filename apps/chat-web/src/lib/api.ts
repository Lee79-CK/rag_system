'use client';

import { useAuthStore } from './stores/auth';

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public body?: unknown,
  ) {
    super(message);
  }
}

let refreshing: Promise<boolean> | null = null;

/** refresh 쿠키(HttpOnly, same-origin rewrite)로 access token 재발급 */
export async function refreshAccess(): Promise<boolean> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    try {
      const res = await fetch('/api/v1/auth/refresh', { method: 'POST', credentials: 'include' });
      if (!res.ok) return false;
      const data = (await res.json()) as { access_token: string; user: import('./stores/auth').AuthUser };
      useAuthStore.getState().setSession(data.access_token, data.user);
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

export interface ApiOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  raw?: boolean;
  noAuth?: boolean;
}

export async function api<T = unknown>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { body, raw, noAuth, headers, ...rest } = opts;
  const doFetch = async () => {
    const token = useAuthStore.getState().accessToken;
    const h: Record<string, string> = { ...(headers as Record<string, string>) };
    if (body !== undefined && !(body instanceof FormData)) h['Content-Type'] = 'application/json';
    if (token && !noAuth) h['Authorization'] = `Bearer ${token}`;
    return fetch(path, { ...rest, headers: h, credentials: 'include', body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body) });
  };
  let res = await doFetch();
  if (res.status === 401 && !noAuth && !path.startsWith('/api/v1/auth/login')) {
    const ok = await refreshAccess();
    if (ok) res = await doFetch();
    else useAuthStore.getState().clear();
  }
  if (!res.ok) {
    // chat-gateway 표준 Error Schema (TDD §3.3): { error: { code, message, request_id } }
    let payload: { error?: { code?: string; message?: string }; code?: string; message?: string } = {};
    try {
      payload = (await res.json()) as typeof payload;
    } catch {
      /* ignore */
    }
    const err = payload.error ?? payload;
    throw new ApiError(res.status, err.code ?? 'error', err.message ?? res.statusText, payload);
  }
  if (raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get('content-type') ?? '';
  return (ct.includes('application/json') ? await res.json() : await res.text()) as T;
}

export const get = <T>(path: string) => api<T>(path);
export const post = <T>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body });
export const patch = <T>(path: string, body?: unknown) => api<T>(path, { method: 'PATCH', body });
export const put = <T>(path: string, body?: unknown) => api<T>(path, { method: 'PUT', body });
export const del = <T>(path: string) => api<T>(path, { method: 'DELETE' });
