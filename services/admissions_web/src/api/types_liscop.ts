// API types of the LISCOP modules. Each agent appends its own types under its own
// section only (see docs/liscop/PLAN.md), so parallel branches merge without conflicts.

// --- beds-ed ---

export type BedStatus = "libre" | "occupe" | "a_nettoyer" | "bloque" | "reserve";
export type BedAction = "nettoye" | "bloquer" | "debloquer" | "reserver" | "annuler_reservation";
// Coded reasons for blocking a bed: same codes as vocab.BED_BLOCK_REASONS on the API.
export const BED_BLOCK_REASONS = {
  travaux: "Travaux",
  equipement: "Équipement en panne",
  hygiene_isolement: "Hygiène, isolement",
  personnel: "Manque de personnel",
  autre: "Autre"
} as const;
export type BedBlockReason = keyof typeof BED_BLOCK_REASONS;
export const BED_NOTE_MAX = 80;
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

export interface RorCode {
  code: string;
  libelle: string;
}

export type RorForecastNature = "disponibles_attendus" | "liberes_non_promis" | "aucune";

export interface RorPrevision {
  echeance: string;
  date: string;
  temporalite: RorCode;
  moyenne: number;
  fourchette_80: [number, number];
  p_tension: number | null;
  p_critique: number | null;
}

export interface RorCapaciteFhir {
  capacityType: RorCode;
  capacityStatus: RorCode;
  temporalityCapacity: RorCode;
  nbCapacity: number;
  genderCapacityAvailable: RorCode | null;
  capacityClosingType: RorCode | null;
  capacityUpdateDate: string | null;
}

export interface RorUnite {
  site_id: number;
  etablissement: string;
  finess_geographique: string | null;
  pool_id: number;
  identifiant_unite_ror: string | null;
  mention: string;
  libelle_unite: string;
  type_unite: string;
  discipline: string;
  capacites: { statut: RorCode; nombre: number; remarque: string | null }[];
  fermetures: { type_fermeture: RorCode; nombre: number; motif_interne: string }[];
  disponibles_par_genre: {
    femme: number | null;
    homme: number | null;
    indetermine: number | null;
    total: number;
    isolement: number | null;
    niveau: "lit" | "unite";
  };
  operationnel: { en_service: number; reactivables: number; supplementaires: number };
  reserves_crise_sse: number;
  previsionnel: RorPrevision[];
  previsionnel_nature: {
    nature: RorForecastNature;
    libelle: string;
    modele: string | null;
    date_de_calcul: string | null;
    calcule_le: string | null;
  };
  tension: { niveau: TensionLevel; taux_disponibilite: number | null };
  fraicheur: { le: string; source: string; libelle: string; age_heures: number } | null;
  dernier_mouvement_saisi: string | null;
  ror_capacites: RorCapaciteFhir[];
  a_completer: string[];
}

export interface RorExport {
  maquette: boolean;
  avertissement: string;
  emetteur: string;
  genere_le: string;
  date_situation: string;
  synthetique: boolean;
  prevision: { id: number; date_de_calcul: string; calcule_le: string; modele: string; perimee: boolean } | null;
  referentiels: { nom: string; url: string }[];
  hypotheses: string[];
  non_suivi_dans_le_pilote: string[];
  unites: RorUnite[];
}

export interface RorOutboxEntry {
  id: number;
  cree_le: string;
  type: string;
  statut: string;
  empreinte_sha256: string;
  unites: number;
  prepare_par: string | null;
  contenu: RorExport | null;
}
