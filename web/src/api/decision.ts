// 24-hour decision-support engine (src/hospitalos/decision_support), served locally by
// web/decision/serve.py and proxied by Vite under /api/decision. Types mirror the Python
// contracts (contracts/decision_support/*.schema.json); only the fields the screen reads.

export type DecisionStatus =
  | "RECOMMENDATION_READY"
  | "NO_ACTION_PREFERRED"
  | "INSUFFICIENT_DATA"
  | "INFEASIBLE"
  | "HYPOTHETICAL_ONLY"
  | "INVALIDATED";

export interface DsAction {
  action_id: string;
  type: "coordinate_discharge" | "reinforcement" | "locked_discharge" | "locked_extension";
  target: string;
  window_start: string;
  window_end: string;
  preconditions: string[];
  origin: "auto" | "manual_lock";
  basis: string;
  conditional: boolean;
}

export interface DsMetrics {
  uncovered_care_minutes: number;
  waiting_patient_hours: number;
  reinforcement_hours: number;
  beds_returned: number;
  peak_pressure: number | null;
  hours_above_threshold: number | null;
  max_total_staff_required: Record<string, number>;
  max_additional_staff_required: Record<string, number>;
}

export interface DsHour {
  hour_index: number;
  local_label: string;
  pressure_score: number | null;
}

export interface DsEvaluation {
  plan: { plan_id: string; label: string; actions: DsAction[] };
  admissible: boolean;
  conditional_on: string[];
  metrics: DsMetrics;
  confirmed_only: DsMetrics | null;
  trajectory: DsHour[];
}

export interface DsBundle {
  backend: { name: string; version: string; code_sha256: string };
  search: {
    enumerated: number;
    evaluated: number;
    limit: number;
    complete: boolean;
    rejected: Record<string, string>;
  };
  evaluations: DsEvaluation[];
  score: { score_status: string; threshold?: number };
}

export interface DsRecommendation {
  recommendation_id: string;
  status: DecisionStatus;
  scientific_status: string;
  clinical_validation: boolean;
  g2: string;
  mode: "auto" | "manual";
  snapshot_id: string;
  objective_version: string;
  engine_version: string;
  reasons: string[];
  conditions: string[];
  uncertainties: string[];
  diagnostics: string[];
  approvable: boolean;
  baseline_plan_id: string | null;
  primary_plan_id: string | null;
  alternative_plan_id: string | null;
  locked_plan_id: string | null;
  bundle: DsBundle | null;
}

export interface DsStay {
  stay_id: string;
  medical_authorization: string;
  planned_departure: string | null;
}

export interface DsSnapshot {
  snapshot_id: string;
  as_of: string;
  stays: DsStay[];
  reinforcements: Array<{ option_id: string; skill: string; source: string; confirmation: string }>;
}

export interface DsEvent {
  id: string;
  unit: string;
  label: string;
}

export interface DsReview {
  outcome: "APPROVED_IN_DEMO" | "REJECTED" | "MODIFY_REQUESTED" | "INVALIDATED" | "REFUSED";
  reasons: string[];
  recompute_required: boolean;
  external_command_sent: false;
  /** Same key + same content: historical receipt, with validity re-evaluated now. */
  replayed?: boolean;
  current_validity?: string | null;
}

export interface DsCompacted {
  source_sha256: string;
  trajectories_dropped_for: string[];
  recommendation: DsRecommendation;
}

export interface DsFixture {
  engine_version: string;
  units: Array<DsCompacted & { id: string; name: string; snapshot: DsSnapshot }>;
  manual: Array<DsCompacted & { id: string; unit: string; label: string; locks: unknown }>;
  events: DsEvent[];
}

async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(
    `/api/decision${path}`,
    body === undefined
      ? {}
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
  );
  const data = (await res.json()) as T & { error?: string };
  if (!res.ok) throw new Error(data.error ?? res.statusText);
  return data;
}

export const decisionApi = {
  units: () => call<{ units: Array<{ id: string; name: string }>; events: DsEvent[] }>("/units"),
  auto: (unit: string) =>
    call<{ doc_id: string; snapshot: DsSnapshot; recommendation: DsRecommendation }>(
      `/auto?unit=${encodeURIComponent(unit)}`,
    ),
  simulate: (unit: string, locks: unknown) =>
    call<{ doc_id: string; recommendation: DsRecommendation }>("/simulate", { unit, locks }),
  review: (unit: string, recommendation_id: string, decision: string, idempotency_key: string) =>
    call<{ doc_id: string; review: DsReview }>("/review", {
      unit,
      recommendation_id,
      decision,
      idempotency_key,
    }),
  inject: (unit: string, event: string) => call<unknown>("/inject", { unit, event }),
  reset: (unit: string) => call<unknown>("/reset", { unit }),
};

/** RFC 6901 pointer, the same resolution the audit uses (T32). */
export function pointer(doc: unknown, ptr: string): unknown {
  return ptr
    .split("/")
    .slice(1)
    .reduce<unknown>((cur, raw) => {
      const token = raw.replace(/~1/g, "/").replace(/~0/g, "~");
      if (Array.isArray(cur)) return cur[Number(token)];
      return cur && typeof cur === "object" ? (cur as Record<string, unknown>)[token] : undefined;
    }, doc);
}
