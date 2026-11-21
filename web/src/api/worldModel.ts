import { call } from "./client";
import { isEvaluation, isPlanReport, readMenu, readUnitMenu, type PlanEvaluation, type PlanMenu, type PlanReport } from "./worldPlans";

export type Flow = "full" | "partial" | "delayed";
export type Phase = "planning" | "confirmed" | "awaiting_report" | "review";
export const COMPARISON_OBJECTIVES = ["transfer_queue", "bed_wait", "uncovered_care"] as const;
export type ComparisonObjective = (typeof COMPARISON_OBJECTIVES)[number];
export const RESOURCE_FAMILIES = ["transport", "cleaning", "staffing", "smr", "beds"] as const;
export type ResourceFamily = (typeof RESOURCE_FAMILIES)[number];
export const RESOURCE_INDICATORS = ["uncovered_ide_minutes", "uncovered_as_minutes", "bed_wait_patient_hours", "cost_eur"] as const;
export type ResourceIndicator = (typeof RESOURCE_INDICATORS)[number];
export interface WmContext { id: string; label: string; feed: Flow; ward_count: number }
export interface WmCatalogue { contexts: WmContext[]; model_version: string }
export interface WmWard { id: string; label: string; beds: number }
export interface WmOption extends Partial<Record<ResourceIndicator, number | null>> {
  id: string;
  label: string;
  kind: "reference" | ResourceFamily;
  ward_id: string | null;
  forecast: number;
  jepa_forecast: number | null;
  eligible?: boolean;
  constraint?: string | null;
  by_ward: number[];
  reconstruction: number | null;
  reconstructed_by_ward: number[] | null;
}
/** Stored sessions predating feasibility metadata contain only feasible options. */
export const canConfirm = (option: WmOption): boolean => option.eligible !== false;
export interface WmReading {
  sample_hour: number;
  published_hour: number;
  observed_stock: number | null;
  by_ward: Array<number | null>;
  visible_components: number;
  total_components: number;
}
export interface WmEvent { hour: number; event: "opened" | "confirmed" | "awaiting_report" | "report_received"; option_id: string | null; ward_id?: string | null }
export interface WmSession {
  id: string; context: WmContext; phase: Phase; hour: number; decision_hour: 12; target_hour: 16;
  publication_hour: number; model_version: string; morning_plan: string[]; wards: WmWard[];
  decision_objective?: ComparisonObjective | null;
  decision_ward_id?: string | null;
  plan_version?: string | null;
  confirmed_plan?: PlanEvaluation | null;
  plan_snapshot?: PlanMenu | null;
  plan_report?: PlanReport | null;
  reference_id: string; selected_id: string | null; options: WmOption[]; observation: WmReading | null; journal: WmEvent[];
}

const object = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;
const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const nullable = (v: unknown) => v === null || num(v);
const int = (v: unknown): v is number => num(v) && Number.isInteger(v) && v >= 0;
const one = (v: unknown, values: readonly string[]) => typeof v === "string" && values.includes(v);
const vector = (v: unknown, count: number, test: (n: unknown) => boolean) => Array.isArray(v) && v.length === count && v.every(test);
function fail(): never { throw new Error("Les données reçues du simulateur sont incohérentes. Actualisez le parcours."); }
function isContext(v: unknown): v is WmContext {
  return object(v) && str(v.id) && str(v.label) && one(v.feed, ["full", "partial", "delayed"]) && int(v.ward_count) && v.ward_count > 0;
}

function catalogue(v: unknown): WmCatalogue {
  if (!object(v) || !str(v.model_version) || !Array.isArray(v.contexts) || !v.contexts.length ||
      !v.contexts.every(isContext) || new Set(v.contexts.map((c) => c.id)).size !== v.contexts.length) fail();
  return { contexts: v.contexts, model_version: v.model_version };
}

function session(raw: unknown, id: string, context: string): WmSession {
  if (!object(raw) || raw.id !== id || !isContext(raw.context) || raw.context.id !== context ||
      !str(raw.model_version) || !one(raw.phase, ["planning", "confirmed", "awaiting_report", "review"]) ||
      !(raw.decision_objective == null || one(raw.decision_objective, COMPARISON_OBJECTIVES)) ||
      (raw.phase === "planning" && raw.decision_objective != null) ||
      raw.decision_hour !== 12 || raw.target_hour !== 16 || !int(raw.hour) || !int(raw.publication_hour) ||
      raw.publication_hour < 16 || !Array.isArray(raw.morning_plan) || !raw.morning_plan.every(str) ||
      !Array.isArray(raw.wards) || raw.wards.length !== raw.context.ward_count ||
      !raw.wards.every((ward) => object(ward) && str(ward.id) && str(ward.label) && num(ward.beds)) ||
      !Array.isArray(raw.options) || !raw.options.length || !str(raw.reference_id) || !Array.isArray(raw.journal)) fail();
  if (!(raw.plan_version == null || str(raw.plan_version)) ||
      !(raw.confirmed_plan == null || (isEvaluation(raw.confirmed_plan) && raw.confirmed_plan.feasible && raw.phase !== "planning")) ||
      !(raw.plan_report == null || (raw.phase === "review" && raw.confirmed_plan != null && isPlanReport(raw.plan_report)))) fail();
  const plan = raw.confirmed_plan;
  const report = raw.plan_report;
  if (raw.plan_snapshot != null) {
    if (!plan || !COMPARISON_OBJECTIVES.some((key) => key === raw.decision_objective)) fail();
    const objective = raw.decision_objective as ComparisonObjective;
    const snapshot = str(raw.decision_ward_id)
      ? readUnitMenu(raw.plan_snapshot, objective, raw.decision_ward_id, context)
      : readMenu(raw.plan_snapshot, objective);
    if ((snapshot.ward_id ?? null) !== (raw.decision_ward_id ?? null)) fail();
    if (!plan.action_ids.every((id) => snapshot.actions.some((a) => a.id === id))) fail();
  }
  if (plan && raw.phase === "review" && !report) fail();
  if (report && raw.context.feed !== "full" && (report.actual_metrics !== null || report.realized !== null || report.case_hours != null)) fail();
  const count = raw.wards.length;
  const wards = new Set(raw.wards.map((w) => w.id));
  if (raw.decision_ward_id != null && (!wards.has(raw.decision_ward_id) || !plan?.ward_metrics ||
      plan.context_id !== context || plan.ward_id !== raw.decision_ward_id || !raw.plan_snapshot)) fail();
  const options = new Set<string>();
  for (const o of raw.options) {
    if (!object(o) || !str(o.id) || options.has(o.id) || !str(o.label) || !one(o.kind, ["reference", ...RESOURCE_FAMILIES]) ||
        !(o.ward_id === null || (str(o.ward_id) && wards.has(o.ward_id))) ||
        !num(o.forecast) || !nullable(o.jepa_forecast) || !vector(o.by_ward, count, num) ||
        !(o.eligible === undefined || typeof o.eligible === "boolean") ||
        !(o.constraint == null || typeof o.constraint === "string") ||
        RESOURCE_INDICATORS.some((key) => o[key] != null && (!num(o[key]) || o[key] < 0)) ||
        !nullable(o.reconstruction) || !(o.reconstructed_by_ward === null || vector(o.reconstructed_by_ward, count, num)) ||
        (raw.phase !== "review" && (o.reconstruction !== null || o.reconstructed_by_ward !== null))) fail();
    options.add(o.id);
  }
  if (wards.size !== count || !raw.options.some((o) => o.id === raw.reference_id && o.kind === "reference") ||
      !(raw.phase === "planning" ? raw.selected_id === null :
        plan ? raw.selected_id === plan.id : str(raw.selected_id) && options.has(raw.selected_id))) fail();
  const r = raw.observation;
  if (raw.phase === "review") {
    if (!object(r) || r.sample_hour !== 16 || !int(r.published_hour) || r.published_hour !== raw.publication_hour || r.published_hour !== raw.hour ||
        !nullable(r.observed_stock) || !vector(r.by_ward, count, nullable) || !int(r.visible_components) ||
        !int(r.total_components) || r.visible_components > r.total_components ||
        !Array.isArray(r.by_ward)) fail();
    const allObserved = r.by_ward.every(num);
    if (allObserved !== num(r.observed_stock)) fail();
    if (allObserved && num(r.observed_stock) && Math.abs(r.by_ward.reduce((a: number, b: number) => a + b, 0) - r.observed_stock) > 1e-4 * Math.max(1, Math.abs(r.observed_stock))) fail();
  } else if (r !== null || (raw.phase === "awaiting_report" ? raw.hour !== 16 : raw.hour !== 12)) fail();
  if (!raw.journal.every((j) => object(j) && int(j.hour) && one(j.event, ["opened", "confirmed", "awaiting_report", "report_received"]) &&
      (j.option_id === null || (str(j.option_id) && (options.has(j.option_id) || j.option_id === plan?.id))))) fail();
  const validated = raw as unknown as WmSession;
  const withinCapacity = (amount: number, capacity: number) =>
    amount >= -1e-6 && amount <= capacity + 1e-6 * Math.max(1, capacity);
  for (const o of validated.options) {
    if (o.kind === "beds" && o.ward_id === null) fail();
    const capacities = validated.wards.map((ward) => ward.beds + Number(o.kind === "beds" && o.ward_id === ward.id));
    const total = capacities.reduce((a, b) => a + b, 0);
    const withinWards = (values: Array<number | null>) =>
      values.every((value, i) => value === null || withinCapacity(value, capacities[i]!));
    if (!withinWards(o.by_ward) || !withinCapacity(o.forecast, total) ||
        (o.jepa_forecast !== null && !withinCapacity(o.jepa_forecast, total)) ||
        (o.reconstruction !== null && !withinCapacity(o.reconstruction, total)) ||
        (o.reconstructed_by_ward !== null && !withinWards(o.reconstructed_by_ward))) fail();
    if (o.id === validated.selected_id && validated.observation && !withinWards(validated.observation.by_ward)) fail();
  }
  return validated;
}

async function sessionCall(id: string, context: string, path: string, init: RequestInit) {
  return session(await call<unknown>(`/world-model/sessions/${encodeURIComponent(id)}${path}`, init, 45000), id, context);
}

export const worldApi = {
  contexts: async (signal: AbortSignal) => catalogue(await call<unknown>("/world-model/contexts", { signal })),
  open: (id: string, context: string, signal: AbortSignal) =>
    sessionCall(id, context, "", { method: "PUT", body: JSON.stringify({ context_id: context }), signal }),
  read: (id: string, context: string, signal: AbortSignal) => sessionCall(id, context, "", { signal }),
  confirm: (id: string, context: string, option: string, signal: AbortSignal, objective?: ComparisonObjective) =>
    sessionCall(id, context, "/confirm", { method: "POST", body: JSON.stringify({ option_id: option, objective }), signal }),
  confirmPlan: (id: string, context: string, actionIds: string[], signal: AbortSignal, objective: ComparisonObjective, scopeIds?: string[]) =>
    sessionCall(id, context, "/plans/confirm", { method: "POST", body: JSON.stringify({ action_ids: actionIds, objective, scope_ids: scopeIds }), signal }),
  async confirmUnit(id: string, context: string, wardId: string, plan: PlanEvaluation, objective: ComparisonObjective, signal: AbortSignal, previewId?: string) {
    const saved = await sessionCall(id, context, "/plans/confirm", {
      method: "POST", body: JSON.stringify({ ward_id: wardId, context_id: context, action_ids: plan.action_ids, objective, preview_id: previewId }), signal,
    });
    if (saved.decision_ward_id !== wardId || saved.decision_objective !== objective || saved.confirmed_plan?.id !== plan.id ||
        saved.confirmed_plan.action_ids.length !== plan.action_ids.length || !plan.action_ids.every(k => saved.confirmed_plan!.action_ids.includes(k))) fail();
    return saved;
  },
  advance: (id: string, context: string, from: 12 | 16, signal: AbortSignal) =>
    sessionCall(id, context, "/advance", { method: "POST", body: JSON.stringify({ from_hour: from }), signal }),
};
