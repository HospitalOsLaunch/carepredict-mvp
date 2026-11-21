import type { LiveSnapshot, Plan, PlanRequest, PlanningOptions, ShadowEpisode } from "./types";

// Local FastAPI hybrid app, proxied by Vite under /api (see vite.config.ts).
// The API has no authentication and no execution endpoint by design.
const BASE = (import.meta.env.VITE_HOSPITALOS_API as string | undefined) ?? "/api";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`HTTP ${status}: ${detail}`);
  }
}

export async function call<T>(path: string, init?: RequestInit, timeoutMs = 20000): Promise<T> {
  const controller = new AbortController();
  const upstream = init?.signal;
  const cancel = () => controller.abort();
  if (upstream?.aborted) cancel();
  else upstream?.addEventListener("abort", cancel, { once: true });
  const timer = setTimeout(cancel, timeoutMs);
  try {
    const response = await fetch(`${BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", Accept: "application/json" },
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = (await response.json()) as { detail?: unknown };
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(response.status, detail);
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
    upstream?.removeEventListener("abort", cancel);
  }
}

export const api = {
  health: () => call<{ status: string; mode: string }>("/health", undefined, 2500),
  live: () => call<LiveSnapshot>("/hybrid/live"),
  shadow: (options: PlanningOptions) =>
    call<ShadowEpisode>("/hybrid/shadow", { method: "POST", body: JSON.stringify(options) }),
  plan: (request: PlanRequest) =>
    call<Plan>("/hybrid/plan", { method: "POST", body: JSON.stringify(request) }),
};
