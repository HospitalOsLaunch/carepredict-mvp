// API types of the LISCOP modules. Each agent appends its own types under its own
// section only (see docs/liscop/PLAN.md), so parallel branches merge without conflicts.

// --- beds-ed ---

export type BedStatus = "libre" | "occupe" | "a_nettoyer" | "bloque" | "reserve";
export type BedAction = "nettoye" | "bloquer" | "debloquer" | "reserver" | "annuler_reservation";
export type TensionLevel = "normal" | "tension" | "critique";

export interface Bed {
  id: number;
  label: string;
  room: string;
  sex_constraint: "F" | "M" | "X";
  isolation: boolean;
  status: BedStatus;
  status_reason: string | null;
  occupant_sex: "F" | "M" | "U" | null;
  accepts: ("F" | "M")[];
  usable: boolean;
  updated_at: string;
}

export interface UnitTension {
  level: TensionLevel;
  availability_rate: number | null;
}

export interface Availability {
  installed: number;
  occupied: number;
  reserved: number;
  cleaning: number;
  blocked: number;
  closed: number;
  usable: number;
  female: number;
  male: number;
  either: number;
  isolation: number;
  sex_conflict: number;
  extra_beds: number;
  crisis_reserved_beds: number;
  tension: UnitTension;
}

export interface BoardUnit {
  pool_id: number;
  code: string;
  label: string;
  unit_type: string;
  discipline: string;
  availability: Availability;
  rooms: { room: string; beds: Bed[] }[];
}

export interface BoardSite {
  site_id: number;
  site_name: string;
  availability: Availability;
  units: BoardUnit[];
}

export interface BedBoard {
  generated_at: string;
  sites: BoardSite[];
}

export interface EdSnapshot {
  id: number;
  site_id: number;
  at: string;
  present: number;
  waiting_bed: number;
  boarding: number;
  hosted_elsewhere: number;
  source: "calcul" | "declaration";
  comment: string | null;
}

export interface EdCensus {
  site_id: number;
  site_name: string;
  ed_sites: { id: number; name: string }[];
  now: {
    at: string;
    present: number;
    waiting_bed: number;
    longest_wait_hours: number | null;
    hosted_elsewhere: number;
  };
  today_10h: {
    day: string;
    at: string;
    reached: boolean;
    boarding: number;
    computed_boarding: number;
    source: "calcul" | "declaration";
  };
  latest_declaration: EdSnapshot | null;
  definitions: string[];
}

export interface BoardingDay {
  day: string;
  present: number;
  waiting_bed: number;
  boarding: number;
  hosted_elsewhere: number;
  source: "calcul" | "declaration";
  computed_boarding: number;
}

export interface BoardingSeries {
  site_id: number;
  days: BoardingDay[];
}

export type HetLevel = "aucun" | "vigilance" | "het_suggere";

export interface HetCriterion {
  code: string;
  label: string;
  value: number | null;
  threshold: number;
  triggered: boolean;
}

export interface TensionDeclaration {
  id: number;
  site_id: number | null;
  kind: "het" | "plan_blanc";
  level: string;
  started_at: string;
  ended_at: string | null;
  declared_by: string;
  comment: string | null;
}

export interface TensionStatus {
  generated_at: string;
  units: {
    site_id: number;
    site_name: string;
    pool_id: number;
    code: string;
    label: string;
    discipline: string;
    installed: number;
    usable: number;
    tension: UnitTension;
  }[];
  aid: { site_id: number; level: HetLevel; label: string; criteria: HetCriterion[]; notice: string } | null;
  active_declarations: TensionDeclaration[];
}

// --- movement-ingest ---

// --- forecast-engine ---

export type ForecastScope = "unit" | "site" | "group" | "ght" | "departement";
export type ForecastTarget =
  "arrivals" | "discharges" | "available_beds" | "tension_prob" | "boarding_10h" | "ed_arrivals";

export interface ForecastDay {
  day: string;
  horizon: string;
  mean: number;
  q10: number;
  q50: number;
  q90: number;
  p_tension: number | null;
  p_critique: number | null;
}

export interface ForecastSeries {
  scope: ForecastScope;
  scope_key: string;
  label: string;
  site_id: number | null;
  pool_id: number | null;
  target: ForecastTarget;
  beds_installed: number | null;
  model: string | null;
  fallback: boolean | null;
  values: ForecastDay[];
  recent: { day: string; value: number }[];
}

export interface ForecastRunInfo {
  id: number;
  as_of: string;
  created_at: string;
  model_version: string;
  horizon_days: number;
  age_hours: number;
  stale: boolean;
  models_chosen: Record<string, number>;
  fallback_series: number;
  common_shock_variance: number | null;
}

export interface BacktestHeadline {
  created_at: string;
  last_full_day: string;
  origins: number;
  gates: Record<string, string>;
  arrivals_mae_ratio: number | null;
  arrivals_coverage_80: number | null;
  beds_coverage_80: number | null;
  beds_coverage_80_randomised: number | null;
  boarding_mae_ratio: number | null;
}

export interface LiscopForecast {
  scope: ForecastScope;
  targets: ForecastTarget[];
  run: ForecastRunInfo | null;
  last_failure_at: string | null;
  restricted_to_site: number | null;
  synthetic: boolean;
  series: ForecastSeries[];
  backtest: BacktestHeadline | null;
  notes: string[];
}

// --- ror-oru-export ---

export {};
