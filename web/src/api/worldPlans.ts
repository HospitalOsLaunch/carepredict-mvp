import { call } from "./client";
import type { ComparisonObjective } from "./worldModel";

export const ACTION_KINDS = [
  "discharge", "admission", "replacement", "redeployment", "reinforcement", "transport", "cleaning", "smr", "beds",
] as const;
export type PlanKind = (typeof ACTION_KINDS)[number];

export interface PlanAction {
  id: string; label: string; kind: PlanKind; ward_id: string; unit: string; quantity: number;
  start_hour: number; end_hour: number; cost_eur: number; eligible: boolean; constraint: string;
}
export const METRICS = [
  "transfer_queue", "bed_wait_patient_hours", "uncovered_ide_minutes", "uncovered_as_minutes",
  "transport_used", "beds_cleaned", "smr_transfers", "open_beds", "available_beds", "admissions", "discharges",
] as const;
const ACCESS_METRICS = ["redirected_patients", "admission_queue_at_16", "named_admissions", "named_discharges"] as const;
export type PlanMetrics = Record<(typeof METRICS)[number], number> & Partial<Record<(typeof ACCESS_METRICS)[number], number>>;
export const UNIT_METRICS = ["transfer_queue", "bed_wait_patient_hours", "uncovered_ide_minutes", "uncovered_as_minutes"] as const;
export type UnitMetrics = Record<(typeof UNIT_METRICS)[number], number>;
export type CaseHours = Record<string, number | null>;
export const WARD_METRICS = ["transfer_queue", "admissions", "redirected_patients", "care_minutes", "transport_used", "beds_cleaned", "smr_transfers", "available_beds"] as const;
export type WardMetric = (typeof WARD_METRICS)[number];
export type WardImpact = { ward_id: string } & Record<WardMetric, number>;
export interface PlanEvaluation {
  id: string; action_ids: string[]; feasible: boolean; conflicts: string[]; cost_eur: number;
  metrics: PlanMetrics | null; realized: Record<string, number>;
  ward_id?: string | null; context_id?: string | null;
  ward_metrics?: UnitMetrics | null;
  access_warnings?: string[]; case_hours?: CaseHours; ward_impacts?: WardImpact[];
}
export interface PlanReport {
  actual_metrics: PlanMetrics | null; realized: Record<string, number> | null;
  case_hours?: CaseHours | null;
  alternatives: Array<{ plan: PlanEvaluation; reconstructed_queue: number }>;
}
export interface UnitIntake {
  context_id: string; ward_id: string;
  as_of_hour: number;
  capacity_beds: number;
  available_beds: number;
  admission_queue: number;
  transfer_queue: number;
  cases: { id: string; kind: "admission" | "discharge"; available_hour: number; scheduled_hour: number | null; eligible: boolean }[];
}
export interface PlanMenu {
  context_id?: string | null;
  objective: ComparisonObjective; actions: PlanAction[]; reference: PlanEvaluation; recommendations: PlanEvaluation[];
  search: { evaluated: number; complete: boolean; examined?: number; feasible?: number; recommendable?: number; scope_size?: number }; budget_eur: number;
  ward_id?: string | null;
  ward_state?: UnitIntake | null;
  example_action_ids?: string[]; scope_ids?: string[];
}

const number = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v >= 0;
const count = (v: unknown): v is number => number(v) && Number.isSafeInteger(v);
const text = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;
const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const counts = (v: unknown): v is Record<string, number> => object(v) && Object.values(v).every(number);
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(text);
const metrics = (v: unknown): v is PlanMetrics => object(v) && METRICS.every((key) => number(v[key])) &&
  ACCESS_METRICS.every(key => v[key] === undefined || number(v[key]));
const hours = (v: unknown): v is CaseHours => object(v) && Object.entries(v).every(([id,h]) => text(id) &&
  (h === null || (count(h) && h >= 12 && h <= 16)));
const wardImpacts = (v: unknown): v is WardImpact[] => Array.isArray(v) && v.every(w => object(w) && text(w.ward_id) &&
  WARD_METRICS.every(k=>typeof w[k] === "number" && Number.isFinite(w[k]))) && new Set(v.map(w=>w.ward_id)).size === v.length;
function invalid(): never { throw new Error("Le simulateur a retourné un plan incohérent. Actualisez le parcours."); }

export function isEvaluation(v: unknown): v is PlanEvaluation {
  return object(v) && text(v.id) && strings(v.action_ids) && new Set(v.action_ids).size === v.action_ids.length &&
    typeof v.feasible === "boolean" && strings(v.conflicts) && number(v.cost_eur) && counts(v.realized) &&
    (v.ward_metrics == null || (object(v.ward_metrics) && UNIT_METRICS.every(k => number((v.ward_metrics as Record<string, unknown>)[k])))) &&
    (v.access_warnings === undefined || strings(v.access_warnings)) && (v.case_hours === undefined || hours(v.case_hours)) &&
    (v.ward_impacts === undefined || wardImpacts(v.ward_impacts)) &&
    (metrics(v.metrics) || (!v.feasible && v.metrics === null));
}
export function isPlanReport(v: unknown): v is PlanReport {
  return object(v) && (v.actual_metrics === null || metrics(v.actual_metrics)) && (v.realized === null || counts(v.realized)) &&
    (v.case_hours == null || hours(v.case_hours)) &&
    Array.isArray(v.alternatives) && v.alternatives.every((a) => object(a) && isEvaluation(a.plan) && a.plan.feasible && number(a.reconstructed_queue));
}
function isAction(v: unknown): v is PlanAction {
  return object(v) && text(v.id) && text(v.label) && ACTION_KINDS.some((k) => k === v.kind) &&
    text(v.ward_id) && text(v.unit) && number(v.quantity) && v.quantity > 0 && number(v.start_hour) &&
    number(v.end_hour) && v.end_hour > v.start_hour && number(v.cost_eur) && typeof v.eligible === "boolean" &&
    typeof v.constraint === "string";
}
export function readMenu(v: unknown, objective: ComparisonObjective): PlanMenu {
  if (!object(v) || v.objective !== objective || !Array.isArray(v.actions) || !v.actions.every(isAction) ||
      !isEvaluation(v.reference) || !v.reference.feasible || v.reference.action_ids.length ||
      !Array.isArray(v.recommendations) || !v.recommendations.every(isEvaluation) || !number(v.budget_eur) ||
      !object(v.search) || !count(v.search.evaluated) || typeof v.search.complete !== "boolean" ||
      [v.search.examined, v.search.feasible, v.search.recommendable, v.search.scope_size].some(x => x !== undefined && !count(x))) invalid();
  const ids = new Set(v.actions.map((a) => a.id));
  const knownIds = (value: unknown): value is string[] => strings(value) && new Set(value).size === value.length && value.every(id => ids.has(id));
  if (ids.size !== v.actions.length || (v.example_action_ids !== undefined && !knownIds(v.example_action_ids)) ||
      (v.scope_ids !== undefined && !knownIds(v.scope_ids)) ||
      v.recommendations.some(p => !p.feasible || !!p.access_warnings?.length || !knownIds(p.action_ids))) invalid();
  return v as unknown as PlanMenu;
}
const plansPath = (sessionId: string) => "/world-model/sessions/" + encodeURIComponent(sessionId) + "/plans";
function isUnitIntake(v: unknown, context: string, ward: string): v is UnitIntake {
  return object(v) && v.context_id === context && v.ward_id === ward && v.as_of_hour === 12 && count(v.capacity_beds) && number(v.available_beds) &&
    v.available_beds <= v.capacity_beds + 1e-6 && number(v.admission_queue) && number(v.transfer_queue) &&
    Array.isArray(v.cases) && v.cases.every(c => object(c) && text(c.id) &&
      (c.kind === "admission" || c.kind === "discharge") && count(c.available_hour) &&
      (c.scheduled_hour === null || count(c.scheduled_hour)) && typeof c.eligible === "boolean") &&
    new Set(v.cases.map(c => c.id)).size === v.cases.length;
}

export function readUnitMenu(raw: unknown, objective: ComparisonObjective, wardId: string, context: string): PlanMenu {
  const menu = readMenu(raw, objective);
  if (menu.ward_id !== wardId || menu.context_id !== context || !isUnitIntake(menu.ward_state, context, wardId) ||
      [menu.reference, ...menu.recommendations].some(plan => !plan.ward_metrics || plan.context_id !== context || plan.ward_id !== wardId)) {
    throw new Error("La recommandation reçue ne correspond pas à cette unité.");
  }
  return menu;
}
export const plansApi = {
  async unitMenu(sessionId: string, objective: ComparisonObjective, wardId: string, context: string, signal: AbortSignal): Promise<PlanMenu> {
    const query = new URLSearchParams({ objective, ward_id: wardId });
    const raw = await call<unknown>(plansPath(sessionId) + "?" + query, { signal }, 90000);
    return readUnitMenu(raw, objective, wardId, context);
  },
  async unitPreview(sessionId: string, context: string, ward: string, ids: string[], objective: ComparisonObjective, signal: AbortSignal) {
    const result = await call<unknown>(plansPath(sessionId) + "/preview", {
      method: "POST", body: JSON.stringify({ ward_id: ward, context_id: context, objective, action_ids: ids }), signal,
    }, 90000);
    if (!isEvaluation(result) || result.context_id !== context || result.ward_id !== ward ||
        (result.feasible && !result.ward_metrics) || result.action_ids.length !== ids.length ||
        !ids.every(id => result.action_ids.includes(id))) invalid();
    return result;
  },
  async unitState(sessionId: string, context: string, ward: string, signal: AbortSignal) {
    const path = "/world-model/sessions/" + encodeURIComponent(sessionId) + "/wards/" + encodeURIComponent(ward) + "/state";
    const result = await call<unknown>(path, { signal });
    if (!isUnitIntake(result, context, ward)) invalid();
    return result;
  },
  async menu(sessionId: string, objective: ComparisonObjective, signal: AbortSignal): Promise<PlanMenu> {
    return readMenu(await call<unknown>(plansPath(sessionId) + "?objective=" + encodeURIComponent(objective), { signal }, 90000), objective);
  },
  async optimize(sessionId: string, actionIds: string[], objective: ComparisonObjective, signal: AbortSignal): Promise<PlanMenu> {
    const raw = await call<unknown>(plansPath(sessionId) + "/optimize",
      { method: "POST", body: JSON.stringify({ action_ids: actionIds, objective }), signal }, 90000);
    const menu = readMenu(raw, objective);
    if (menu.recommendations.some((p) => !p.action_ids.every((id) => actionIds.includes(id)))) invalid();
    return menu;
  },
  async preview(sessionId: string, actionIds: string[], objective: ComparisonObjective, signal: AbortSignal): Promise<PlanEvaluation> {
    const v = await call<unknown>(plansPath(sessionId) + "/preview",
      { method: "POST", body: JSON.stringify({ action_ids: actionIds, objective }), signal }, 90000);
    if (!isEvaluation(v) || v.action_ids.length !== actionIds.length || !actionIds.every((id) => v.action_ids.includes(id))) invalid();
    return v;
  },
};
