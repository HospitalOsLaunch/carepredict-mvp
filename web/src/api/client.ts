import type { LiveSnapshot, Plan, PlanRequest, PlanningOptions, ShadowEpisode } from "./types";

// Local FastAPI hybrid app, proxied by Vite under /api (see vite.config.ts).
// The observation API has no execution endpoint. Explicit simulated decisions
// use the separate local simulator gateway from simulator.ts.
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
  const timer = setTimeout(() => controller.abort(), timeoutMs);
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
