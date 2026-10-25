export type Role = "admin_groupe" | "coordination" | "direction" | "ingestion";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  site_id: number | null;
  active: boolean;
}

export interface LoginResponse {
  token: string;
  user: User;
  group_name: string;
}

export interface Vocabulary {
  mentions: Record<string, string>;
  sources: Record<string, string>;
  statuses: Record<string, string>;
  refusal_reasons: Record<string, string>;
  loss_reasons: Record<string, string>;
  capacity_reasons: Record<string, string>;
  special_needs: Record<string, string>;
  roles: Record<string, string>;
}

export interface Pool {
  mention: string;
  beds_installed: number;
  beds_open: number;
  isolation_rooms: number;
  occupied: number;
}

export interface Site {
  id: number;
  name: string;
  finess: string | null;
  city: string | null;
  capabilities: string[];
  active: boolean;
  pools: Pool[];
}

export interface Factor {
  code: string;
  label: string;
  value: number;
  weight: number;
  contribution: number;
  detail: string;
}

export interface Suggestion {
  site_id: number;
  site_name: string;
  eligible: boolean;
  blockers: string[];
  score: number;
  factors: Factor[];
  safe_date: string | null;
  probable_date: string | null;
}

export type RequestStatus =
  | "nouvelle"
  | "en_etude"
  | "accord"
  | "confirmee"
  | "admise"
  | "refusee"
  | "perdue";

export interface AdmissionRequest {
  id: number;
  source: string;
  external_ref: string | null;
  received_at: string;
  referrer_facility: string;
  referrer_unit: string | null;
  patient_ref: string;
  patient_age: number | null;
  patient_sex: string | null;
  mention_requested: string;
  clinical_category: string | null;
  care_level: number;
  isolation_required: boolean;
  special_needs: string[];
  desired_date: string | null;
  status: RequestStatus;
  site_id: number | null;
  site_name: string | null;
  proposed_date: string | null;
  first_response_at: string | null;
  closed_at: string | null;
  refusal_reason: string | null;
  loss_reason: string | null;
  notes: string | null;
  waiting_hours: number;
  priority: number;
  best: Suggestion | null;
}

export interface RequestEvent {
  at: string;
  kind: string;
  from_status: string | null;
  to_status: string | null;
  detail: string | null;
  actor: string | null;
}

export interface RequestDetail extends AdmissionRequest {
  suggestions: Suggestion[];
  events: RequestEvent[];
  draft_message: string | null;
  stay_id: number | null;
}

export interface Stay {
  id: number;
  site_id: number;
  site_name: string;
  mention: string;
  patient_ref: string;
  admission_date: string;
  planned_discharge_date: string | null;
  discharge_date: string | null;
  length_of_stay: number;
  prob_within_7_days: number | null;
  median_discharge_day: string | null;
}

export interface DayForecast {
  day: string;
  expected_discharges: number;
  cumulative_expected: number;
  cumulative_p10: number;
  cumulative_p90: number;
  reserved: number;
  free_expected: number;
  free_p10: number;
  free_p90: number;
  prob_at_least_one_free: number;
}

export interface PoolForecast {
  site_id: number;
  site_name: string;
  mention: string;
  beds_open: number;
  beds_installed: number;
  occupied_now: number;
  days: DayForecast[];
}

export interface Forecast {
  as_of: string;
  horizon: number;
  basis: {
    method: string;
    stays_used: number;
    completed_stays_used: number;
    low_data_mentions: string[];
    plan_slip_is_prior: boolean;
  };
  pools: PoolForecast[];
}

export interface SiteCard {
  site_id: number;
  site_name: string;
  city: string | null;
  beds_installed: number;
  beds_open: number;
  occupied: number;
  occupancy_on_open: number | null;
  awaiting_response: number;
  oldest_waiting_hours: number | null;
  discharges_next_7_days: number;
  free_beds_in_7_days: number;
  reserved_next_7_days: number;
}

export interface GroupDashboard {
  as_of: string;
  group_name: string;
  beds_installed: number;
  beds_open: number;
  occupied: number;
  occupancy_on_open: number | null;
  awaiting_response: number;
  responses_median_hours_30d: number | null;
  sites: SiteCard[];
  daily_free_beds: Array<Record<string, number | string>>;
}

export interface Occupancy {
  days: number;
  occupied_bed_days: number;
  open_bed_days: number;
  installed_bed_days: number;
  rate_on_open: number | null;
  rate_on_installed: number | null;
  avg_closed_beds: number;
  closed_bed_days_by_reason: Record<string, number>;
}

export interface RequestsSummary {
  received: number;
  responded: number;
  response_hours_median: number | null;
  response_hours_p90: number | null;
  responded_within_24h: number | null;
  by_status: Record<string, number>;
  accord_rate: number | null;
  conversion_rate: number | null;
  lost_after_accord_rate: number | null;
  refusal_reasons: Record<string, number>;
  loss_reasons: Record<string, number>;
}

export interface NorthStar {
  baseline_rate: number;
  period_rate: number;
  recovered_bed_days: number;
  recovered_low: number | null;
  recovered_high: number | null;
  value_eur: number;
  value_low_eur: number | null;
  value_high_eur: number | null;
  success_fee_eur: number;
  period_days: number;
  baseline_days: number;
  placebo_windows: number;
  included_pools: string[];
  excluded_pools: Record<string, string>;
  interval_note: string;
}

export interface Baseline {
  start: string | null;
  end: string | null;
  frozen_at: string | null;
}

export interface PilotMetrics {
  period_start: string;
  period_end: string;
  site_id: number | null;
  occupancy: Occupancy;
  requests: RequestsSummary;
  baseline: Baseline;
  baseline_occupancy: Occupancy | null;
  north_star: NorthStar | null;
  north_star_unavailable_reason: string | null;
  weekly: Array<{
    week_start: string;
    occupancy_on_open: number | null;
    closed_beds: number;
    received: number;
    admitted: number;
    response_hours_median: number | null;
  }>;
}

export interface Backtest {
  horizon_days: number;
  points: Array<{ as_of: string; predicted: number; p10: number; p90: number; actual: number }>;
  mae: number | null;
  bias: number | null;
  coverage_80: number | null;
  note: string;
}

export interface GroupSettings {
  name: string;
  value_per_bed_day: number;
  success_fee_rate: number;
  scoring_weights: Record<string, number>;
  baseline: Baseline;
}

export interface ImportResult {
  kind: string;
  dry_run: boolean;
  rows: number;
  created: number;
  updated: number;
  errors: Array<{ line: number; column: string | null; message: string }>;
  committed: boolean;
}

export interface AuditEntry {
  at: string;
  user: string | null;
  action: string;
  entity: string;
  entity_id: string | null;
  detail: string | null;
}
