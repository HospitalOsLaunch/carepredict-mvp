// Shared HTTP layer for the platform API (/api). Every request carries the session cookie (same origin) and
// the anti-CSRF header the platform requires on state-changing requests. A 401 announces an expired session.

export const SECURITY_HEADER = { "X-Requested-With": "HospitalOS" } as const;
export const UNAUTHORIZED_EVENT = "hos:unauthorized";

export class HttpError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly body: unknown,
  ) {
    super(detail || `HTTP ${status}`);
  }
}

function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
  }
  if (body && typeof body === "object" && "error" in body) return String((body as { error: unknown }).error);
  return fallback;
}

export async function request<T>(
  path: string,
  init: { method?: string; body?: unknown; timeoutMs?: number; quiet401?: boolean } = {},
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), init.timeoutMs ?? 20000);
  try {
    const response = await fetch(path, {
      method: init.method ?? (init.body === undefined ? "GET" : "POST"),
      credentials: "same-origin",
      signal: controller.signal,
      headers: { Accept: "application/json", "Content-Type": "application/json", ...SECURITY_HEADER },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      /* empty or non-JSON body */
    }
    if (!response.ok) {
      if (response.status === 401 && !init.quiet401) window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
      throw new HttpError(response.status, detailOf(body, response.statusText), body);
    }
    return body as T;
  } finally {
    clearTimeout(timer);
  }
}
