/**
 * HTTP client.
 *
 * Single choke point for every request, which is what makes auth a one-file
 * change later: `authHeader()` already injects a bearer token when one is
 * present, so pointing the app at a real OAuth2/JWT issuer means changing the
 * token source in store/auth.ts and nothing here.
 */
import { getToken, clearSession } from "@/store/auth";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  // Declared as fields rather than constructor parameter properties: the
  // project builds with erasableSyntaxOnly, which forbids the shorthand.
  readonly status: number;
  readonly body?: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

function authHeader(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...authHeader(),
      ...init?.headers,
    },
  });

  if (res.status === 401) {
    // The demo backend never issues this, but the seam is wired so a real
    // issuer drops in without touching call sites.
    clearSession();
    throw new ApiError(401, "Session expired");
  }

  if (!res.ok) {
    let detail = res.statusText;
    let body: unknown;
    try {
      body = await res.json();
      const d = (body as { detail?: unknown })?.detail;
      if (typeof d === "string") detail = d;
      else if (d) detail = JSON.stringify(d);
    } catch {
      /* non-JSON error body: keep the status text */
    }
    throw new ApiError(res.status, detail, body);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Drops undefined/null/"" so optional filters never reach the server as "undefined". */
export function qs(params: object): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params) as [string, unknown][]) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) }),
};

/** Absolute URL for the SSE endpoint (EventSource cannot take custom headers). */
export function streamUrl(): string {
  return `${API_BASE}/api/stream/assets`;
}
