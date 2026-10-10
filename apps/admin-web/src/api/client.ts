/**
 * fetch wrapper for admin-api.
 *
 * - All requests target relative `/api/v1/...` (closed network — NO external hosts).
 * - Unwraps the `{ data, meta }` envelope (admin.api.responses.envelope).
 * - Surfaces the standard Error Schema `{ error: { code, message, ... } }` as ApiError.
 * - Sends the dev reverse-proxy header `X-Auth-User` (DEC-003). In production an
 *   oauth2-proxy / ingress injects the real header and this dev value is ignored.
 */
import type { Envelope, ErrorResponse, Meta } from "../types";

export const API_BASE = "/api/v1";

/** Dev auth identity. Configurable via VITE_DEV_AUTH_USER; overridable at runtime. */
const AUTH_USER_STORAGE_KEY = "admin-web.auth-user";

export function getAuthUser(): string {
  const stored =
    typeof localStorage !== "undefined"
      ? localStorage.getItem(AUTH_USER_STORAGE_KEY)
      : null;
  return stored ?? import.meta.env.VITE_DEV_AUTH_USER ?? "admin";
}

export function setAuthUser(user: string): void {
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(AUTH_USER_STORAGE_KEY, user);
  }
}

export class ApiError extends Error {
  code: string;
  status: number;
  detail?: Record<string, unknown> | null;
  requestId?: string;

  constructor(
    status: number,
    body: ErrorResponse["error"] | { message: string },
  ) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = "code" in body ? body.code : `HTTP_${status}`;
    this.detail = "detail" in body ? body.detail : null;
    this.requestId = "request_id" in body ? body.request_id : undefined;
  }
}

export interface RequestOptions {
  method?: string;
  /** JSON body; omit for GET. Mutually exclusive with `formData`. */
  body?: unknown;
  /** multipart/form-data body (document upload). Sets no Content-Type header. */
  formData?: FormData;
  query?: Record<string, string | number | boolean | undefined>;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.append(key, String(value));
    }
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function parseError(res: Response): Promise<ApiError> {
  try {
    const json = (await res.json()) as Partial<ErrorResponse>;
    if (json && json.error) {
      return new ApiError(res.status, json.error);
    }
  } catch {
    // fall through to generic
  }
  return new ApiError(res.status, {
    message: res.statusText || "요청 처리 중 오류가 발생했습니다.",
  });
}

/** Core request; returns the FULL envelope so callers can read `meta`. */
export async function requestEnvelope<T>(
  path: string,
  opts: RequestOptions = {},
): Promise<Envelope<T>> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-Auth-User": getAuthUser(),
  };

  let body: BodyInit | undefined;
  if (opts.formData) {
    body = opts.formData; // browser sets multipart boundary
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }

  const res = await fetch(buildUrl(path, opts.query), {
    method: opts.method ?? (body ? "POST" : "GET"),
    headers,
    body,
    signal: opts.signal,
  });

  if (!res.ok) {
    throw await parseError(res);
  }

  // Health-style endpoints (rare here) may not be enveloped; guard anyway.
  if (res.status === 204) {
    return { data: undefined as unknown as T, meta: {} };
  }
  const json = (await res.json()) as Envelope<T>;
  if (json && typeof json === "object" && "data" in json) {
    return { data: json.data, meta: (json.meta ?? {}) as Meta };
  }
  return { data: json as unknown as T, meta: {} };
}

/** Content-Disposition 의 파일명 — RFC 5987 `filename*=UTF-8''…`(한글) 우선, 없으면 `filename="…"`. */
function dispositionFilename(header: string | null): string | null {
  if (!header) return null;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      // fall through
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1] : null;
}

/**
 * Binary download (원본 파일 등). `<a href>`/`<iframe src>` 는 X-Auth-User 를 보내지 못하므로
 * fetch 로 받아 Blob 으로 넘긴다 — 호출자가 object URL 로 미리보기하거나 저장한다.
 */
export async function requestBlob(
  path: string,
  query?: RequestOptions["query"],
): Promise<{
  blob: Blob;
  filename: string | null;
  contentType: string | null;
}> {
  const res = await fetch(buildUrl(path, query), {
    headers: { "X-Auth-User": getAuthUser() },
  });
  if (!res.ok) throw await parseError(res);
  return {
    blob: await res.blob(),
    filename: dispositionFilename(res.headers.get("Content-Disposition")),
    contentType: res.headers.get("Content-Type"),
  };
}

/** Convenience: returns only `data`. */
export async function request<T>(
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const { data } = await requestEnvelope<T>(path, opts);
  return data;
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"]) =>
    request<T>(path, { query }),
  getEnvelope: <T>(path: string, query?: RequestOptions["query"]) =>
    requestEnvelope<T>(path, { query }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: <T>(path: string, formData: FormData) =>
    request<T>(path, { method: "POST", formData }),
  blob: (path: string, query?: RequestOptions["query"]) =>
    requestBlob(path, query),
};
