// API types of the LISCOP modules. Each agent appends its own types under its own
// section only (see docs/liscop/PLAN.md), so parallel branches merge without conflicts.

// --- beds-ed ---

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
