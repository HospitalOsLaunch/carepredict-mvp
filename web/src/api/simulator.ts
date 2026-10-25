import { call } from "./client";
import type { LiveSnapshot, ShadowEpisode } from "./types";

export interface CommandReceipt {
  request_id: string;
  plan_id: string;
  at: string;
  status: "accepted" | "refusal_recorded" | "executed" | "refused" | "failed";
  outcome_at: string | null;
  processing_seconds: number;
  effect_scope: "simulator_only";
}

export interface DemoView {
  schema_version: "DYNAMIC_DEMO_1";
  mode: "simulation_sandbox";
  run_id: string;
  revision: number;
  unit_name: string;
  now: string;
  speed: number;
  completed: boolean;
  feed_enabled: boolean;
  snapshot: LiveSnapshot;
  episode: ShadowEpisode | null;
  can_apply: boolean;
  commands: CommandReceipt[];
  evaluation: null | {
    waiting_patient_minutes: number;
    waiting_at_end: number;
    admitted_at_end: number;
    departed: number;
    patients_total: number;
    completed_cleanings: number;
    coordination_tasks: number;
    scope: string;
  };
}

export type Operation = "advance" | "play" | "pause" | "disconnect" | "reconnect" | "finish" | "reset";

async function request(path: string, body?: object): Promise<DemoView> {
  const data = await call<DemoView>(path, body ? { method: "POST", body: JSON.stringify(body) } : undefined);
  if (data.schema_version !== "DYNAMIC_DEMO_1" || data.mode !== "simulation_sandbox") {
    throw new Error("Unsupported simulation session");
  }
  return data;
}

function identity(view: DemoView) {
  return { run_id: view.run_id, revision: view.revision, request_id: crypto.randomUUID() };
}

export const simulatorApi = {
  read: () => request("/demo/session"),
  evaluate: () => request("/demo/evaluate", {}),
  control: (view: DemoView, operation: Operation, seconds = 300) =>
    request("/demo/control", { ...identity(view), operation, seconds, speed: 60 }),
  decide: (view: DemoView, accept: boolean) => {
    const plan = view.episode?.assessment.plan;
    if (!plan) return Promise.reject(new Error("No proposal"));
    return request("/demo/decision", {
      ...identity(view), accept, plan_id: plan.plan_id,
      snapshot_fingerprint: view.snapshot.semantic_fingerprint,
    });
  },
};
