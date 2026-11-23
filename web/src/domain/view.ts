// Pure derivations from backend contracts to what each screen shows.
// Rule: the backend stays the authority. Stages, blockers, staleness and decisions
// come from its output; facts are only re-read here to show *which link* is missing.

import type {
  Action,
  Bed,
  Candidate,
  Discharge,
  DischargeReadiness,
  FactEvent,
  LiveSnapshot,
  PairedTrace,
  Patient,
  Plan,
  ResourceBudget,
  State,
} from "../api/types";

export type Origin = "fixture" | "api-plan" | "api-live";

export interface Assessment {
  origin: Origin;
  scenarioId: string;
  scenarioLabel: string;
  state: State;
  plan: Plan | null;
  /** Live gates (shadow) or abstention reasons; empty when a plan was computed. */
  gateReasons: string[];
  events: FactEvent[];
  resources: ResourceBudget[] | null;
  receivedAtBySource: Record<string, string> | null;
  trace: PairedTrace | null;
  episodeId: string | null;
  /** Freshness budget used by the backend for facts, in minutes. */
  factBudgetMinutes: number;
  /** When the proposal stops being actionable (live proposal TTL, else plan expiry). */
  expiresAt: string | null;
}

// ---------------------------------------------------------------- time

export const minutesBetween = (from: string, to: string): number =>
  (Date.parse(to) - Date.parse(from)) / 60000;

const PARIS = "Europe/Paris";
const hm = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: PARIS });
const dayHm = new Intl.DateTimeFormat("fr-FR", {
  weekday: "long",
  day: "numeric",
  month: "long",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: PARIS,
});

export const clock = (iso: string): string => hm.format(new Date(iso));
export const longClock = (iso: string): string => dayHm.format(new Date(iso));
export const clockPlus = (iso: string, minutes: number): string =>
  hm.format(new Date(Date.parse(iso) + minutes * 60000));

/** "6 h 42", "45 min", "2 j 4 h" — durations as staff say them. */
export function duration(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} h ${String(m % 60).padStart(2, "0")}`;
  const d = Math.floor(h / 24);
  return `${d} j ${h % 24} h`;
}

export function age(minutes: number): string {
  if (minutes < 1) return "à l'instant";
  return `il y a ${duration(minutes)}`;
}

const integer = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
export const num = (value: number): string => integer.format(value);
const percent = new Intl.NumberFormat("fr-FR", { style: "percent", maximumFractionDigits: 0 });
export const pct = (value: number): string => percent.format(value);

// ---------------------------------------------------------------- freshness

export interface Freshness {
  key: string;
  minutes: number;
  source: string;
  /** Authoritative: only the backend decides that a fact is stale. */
  stale: boolean;
  /** Visual cue: past half of the budget, not yet stale. */
  ageing: boolean;
}

export function freshnessIndex(a: Assessment): Map<string, Freshness> {
  const staleKeys = new Set(
    [...a.state.issues, ...a.gateReasons]
      .filter((c) => c.startsWith("stale:"))
      .map((c) => c.slice("stale:".length)),
  );
  const latest = new Map<string, FactEvent>();
  for (const event of a.events) {
    const key = `${event.fact.kind}:${event.fact.id}`;
    const current = latest.get(key);
    if (!current || event.version > current.version || event.available_at > current.available_at) {
      latest.set(key, event);
    }
  }
  const index = new Map<string, Freshness>();
  for (const [key, event] of latest) {
    const minutes = Math.max(0, minutesBetween(event.available_at, a.state.at));
    index.set(key, {
      key,
      minutes,
      source: event.source,
      stale: staleKeys.has(key),
      ageing: minutes > a.factBudgetMinutes / 2,
    });
  }
  for (const key of staleKeys) {
    if (!index.has(key)) index.set(key, { key, minutes: NaN, source: "", stale: true, ageing: true });
  }
  return index;
}

export function oldestFact(a: Assessment): Freshness | null {
  let oldest: Freshness | null = null;
  for (const f of freshnessIndex(a).values()) {
    if (!Number.isNaN(f.minutes) && (!oldest || f.minutes > oldest.minutes)) oldest = f;
  }
  return oldest;
}

// ---------------------------------------------------------------- situation

export interface Situation {
  waiting: number;
  usable: number;
  dirty: number;
  occupied: number;
  closed: number;
  unknown: number;
  staffedFree: number | null;
  departuresPrepared: number;
  departuresReady: number;
}

export function situation(state: State, plan: Plan | null): Situation {
  const unit = state.units[0];
  const committed = state.beds.filter((b) => b.state === "occupied" || b.reserved_for).length;
  const staffedFree = unit?.staffed_beds == null ? null : Math.max(0, unit.staffed_beds - committed);
  const clean = state.beds.filter((b) => b.state === "clean" && !b.reserved_for).length;
  const readiness = plan?.discharge_readiness ?? [];
  return {
    waiting: state.patients.filter((p) => p.status === "waiting").length,
    usable: staffedFree == null ? clean : Math.min(clean, staffedFree),
    dirty: state.beds.filter((b) => b.state === "dirty").length,
    occupied: state.beds.filter((b) => b.state === "occupied").length,
    closed: state.beds.filter((b) => b.state === "closed").length,
    unknown: state.beds.filter((b) => b.state === "unknown").length,
    staffedFree,
    departuresPrepared: releaseChains(state, plan).length,
    departuresReady: readiness.filter((r) => r.stage === "ready_for_simulation").length,
  };
}

// ---------------------------------------------------------------- release chain (signature)

export type LinkStatus = "ok" | "todo" | "blocked" | "unknown" | "na";

export interface ChainLink {
  id: "medical" | "documents" | "escort" | "downstream" | "transport";
  label: string;
  short?: string;
  status: LinkStatus;
  detail: string;
}

export interface ReleaseChain {
  patient: Patient;
  bed: Bed | null;
  readiness: DischargeReadiness | null;
  links: ChainLink[];
  /** Waiting patients who could take this bed once freed (compatibility only). */
  nextCandidates: Patient[];
}

function tri(value: boolean | null, ok: string, no: string, unknown = "Non renseigné"): [LinkStatus, string] {
  if (value === true) return ["ok", ok];
  if (value === false) return ["todo", no];
  return ["unknown", unknown];
}

export function chainLinks(patient: Patient, d: Discharge | undefined, state: State): ChainLink[] {
  const pool = (id: string | null) => state.pools.find((p) => p.id === id);
  const links: ChainLink[] = [];
  const [ms, md] = tri(patient.medically_cleared, "Sortie autorisée", "Non autorisée");
  links.push({ id: "medical", label: "Avis médical", status: ms === "todo" ? "blocked" : ms, detail: md });
  if (!d) {
    for (const [id, label] of [
      ["documents", "Documents"],
      ["escort", "Accompagnant"],
      ["downstream", "Aval"],
      ["transport", "Transport"],
    ] as const) {
      links.push({ id, label, status: "unknown", detail: "Logistique non renseignée" });
    }
    return links;
  }
  const [ds, dd] = tri(d.documents_ready, "Prêts", "À préparer");
  links.push({ id: "documents", label: "Documents", status: ds, detail: dd });

  if (d.escort_required === false)
    links.push({ id: "escort", label: "Accompagnant", status: "na", detail: "Non requis" });
  else if (d.escort_required == null)
    links.push({ id: "escort", label: "Accompagnant", status: "unknown", detail: "Besoin non renseigné" });
  else {
    const [es, ed] = tri(d.escort_confirmed, "Confirmé", "À confirmer", "À confirmer");
    links.push({ id: "escort", label: "Accompagnant", status: es === "unknown" ? "todo" : es, detail: ed });
  }

  if (d.downstream_required === false)
    links.push({ id: "downstream", label: "Aval", status: "na", detail: "Retour à domicile" });
  else if (d.downstream_required == null)
    links.push({ id: "downstream", label: "Aval", status: "unknown", detail: "Besoin non renseigné" });
  else {
    const p = pool(d.downstream_pool_id);
    const name = p?.id ?? d.downstream_pool_id ?? "structure";
    if (patient.downstream_confirmed !== true)
      links.push({ id: "downstream", label: "Aval", status: "todo", detail: `Accord ${name} à obtenir` });
    else if (!p || p.available == null)
      links.push({
        id: "downstream",
        label: "Aval",
        status: "unknown",
        detail: `${name} : places inconnues`,
      });
    else if (p.available === 0)
      links.push({ id: "downstream", label: "Aval", status: "blocked", detail: `${name} : complet` });
    else links.push({ id: "downstream", label: "Aval", status: "ok", detail: `${name} : accord` });
  }

  if (d.transport_required === false)
    links.push({ id: "transport", label: "Transport", status: "na", detail: "Moyens personnels" });
  else if (d.transport_required == null)
    links.push({ id: "transport", label: "Transport", status: "unknown", detail: "Besoin non renseigné" });
  else {
    const p = pool(d.transport_pool_id);
    if (d.transport_requested === true)
      links.push({ id: "transport", label: "Transport", status: "ok", detail: "Demandé" });
    else if (p?.available === 0)
      links.push({ id: "transport", label: "Transport", status: "blocked", detail: "Aucun disponible" });
    else links.push({ id: "transport", label: "Transport", status: "todo", detail: "À demander" });
  }
  return links;
}

export function compatibleBed(patient: Patient, bed: Bed): boolean {
  return (
    patient.compatible_units.includes(bed.unit_id) &&
    patient.requirements.every((r) => bed.capabilities.includes(r))
  );
}

/** Departures being prepared: a logistics record exists or the release is authorised. */
export function releaseChains(state: State, plan: Plan | null): ReleaseChain[] {
  const readiness = new Map((plan?.discharge_readiness ?? []).map((r) => [r.patient_id, r]));
  const waiting = waitingQueue(state);
  const order: Record<string, number> = {
    transport_to_request: 0,
    ready_for_simulation: 1,
    logistics_blocked: 2,
    medical_not_confirmed: 3,
  };
  return state.patients
    .filter((p) => p.status === "admitted")
    .filter((p) => p.medically_cleared === true || state.discharges.some((d) => d.id === p.id))
    .map((patient) => {
      const bed = state.beds.find((b) => b.id === patient.bed_id) ?? null;
      return {
        patient,
        bed,
        readiness: readiness.get(patient.id) ?? null,
        links: chainLinks(
          patient,
          state.discharges.find((d) => d.id === patient.id),
          state,
        ),
        nextCandidates: bed ? waiting.filter((w) => compatibleBed(w, bed)).slice(0, 3) : [],
      };
    })
    .sort(
      (a, b) =>
        (order[a.readiness?.stage ?? ""] ?? 9) - (order[b.readiness?.stage ?? ""] ?? 9) ||
        a.patient.id.localeCompare(b.patient.id),
    );
}

export function stayCount(state: State, plan: Plan | null): number {
  return state.patients.filter((p) => p.status === "admitted").length - releaseChains(state, plan).length;
}

// ---------------------------------------------------------------- waiting queue

export function waitingQueue(state: State): Patient[] {
  return state.patients
    .filter((p) => p.status === "waiting")
    .sort((a, b) => b.priority - a.priority || a.waiting_since.localeCompare(b.waiting_since));
}

export interface QueueEntry {
  patient: Patient;
  waitedMinutes: number;
  usableNow: Bed[];
  reservedBed: Bed | null;
}

export function queueEntries(state: State): QueueEntry[] {
  const unit = state.units[0];
  const committed = state.beds.filter((b) => b.state === "occupied" || b.reserved_for).length;
  const capacityLeft = unit?.staffed_beds == null ? 0 : unit.staffed_beds - committed;
  return waitingQueue(state).map((patient) => ({
    patient,
    waitedMinutes: minutesBetween(patient.waiting_since, state.at),
    usableNow:
      capacityLeft > 0
        ? state.beds.filter((b) => b.state === "clean" && !b.reserved_for && compatibleBed(patient, b))
        : [],
    reservedBed: state.beds.find((b) => b.reserved_for === patient.id) ?? null,
  }));
}

// ---------------------------------------------------------------- proposal

export interface Comparison {
  baseline: Candidate | null;
  selected: Candidate | null;
  /** Lower is better. Negative delta = less simulated waiting than doing nothing. */
  deltaMean: number | null;
  deltaRatio: number | null;
  deltaTail: number | null;
  ranked: Candidate[];
}

const sameAction = (a: Action, b: Action) =>
  a.kind === b.kind && a.bed_id === b.bed_id && a.patient_id === b.patient_id;

export function comparison(plan: Plan | null): Comparison {
  const candidates = plan?.candidates ?? [];
  const baseline = candidates.find((c) => c.action.kind === "no_op") ?? null;
  const selected = plan ? (candidates.find((c) => sameAction(c.action, plan.selected)) ?? null) : null;
  const deltaMean =
    baseline && selected
      ? selected.mean_waiting_patient_minutes - baseline.mean_waiting_patient_minutes
      : null;
  return {
    baseline,
    selected,
    deltaMean,
    deltaRatio:
      deltaMean != null && baseline && baseline.mean_waiting_patient_minutes > 0
        ? deltaMean / baseline.mean_waiting_patient_minutes
        : null,
    deltaTail:
      baseline && selected
        ? selected.worst_decile_waiting_patient_minutes - baseline.worst_decile_waiting_patient_minutes
        : null,
    ranked: [...candidates].sort((a, b) => a.objective - b.objective),
  };
}

export const isSelected = (plan: Plan | null, c: Candidate): boolean =>
  !!plan && sameAction(plan.selected, c.action);

/** Facts (not causes) that make the selected action legible to the person approving it. */
export function proposalContext(state: State, plan: Plan): string[] {
  const action = plan.selected;
  const bed = state.beds.find((b) => b.id === action.bed_id);
  const waiting = waitingQueue(state);
  const lines: string[] = [];
  if (!bed) return lines;
  const needing = (cap: string) => waiting.filter((p) => p.requirements.includes(cap));
  const cleanWith = (cap: string) =>
    state.beds.filter((b) => b.state === "clean" && !b.reserved_for && b.capabilities.includes(cap));
  if (action.kind === "request_transport" || action.kind === "prioritize_cleaning") {
    for (const cap of bed.capabilities) {
      const n = needing(cap);
      if (n.length) {
        const free = cleanWith(cap).length;
        lines.push(
          `Le lit ${bed.id} est équipé ${cap === "oxygene" ? "oxygène" : cap}. ` +
            `${n.length} patient${n.length > 1 ? "s" : ""} en attente en ${n.length > 1 ? "ont" : "a"} besoin ; ` +
            (free === 0
              ? "aucun lit propre ne l'offre."
              : `${free} lit${free > 1 ? "s" : ""} propre${free > 1 ? "s" : ""} l'offre${free > 1 ? "nt" : ""}.`),
        );
      }
    }
  }
  if (action.kind === "request_transport") {
    const r = plan.discharge_readiness.find((d) => d.patient_id === action.patient_id);
    if (r?.stage === "transport_to_request") {
      lines.push(`Toutes les autres étapes de sortie de ${action.patient_id} sont confirmées.`);
    }
  }
  if (action.kind === "reserve_bed") {
    const p = state.patients.find((x) => x.id === action.patient_id);
    if (p)
      lines.push(
        `${p.id} attend depuis ${duration(minutesBetween(p.waiting_since, state.at))} (priorité ${p.priority}).`,
      );
  }
  return lines;
}

// ---------------------------------------------------------------- normalisation

export function fromLive(
  snapshot: LiveSnapshot,
  plan: Plan | null,
  gateReasons: string[],
  origin: Origin,
  episodeId: string | null,
  expiresAt: string | null = null,
): Assessment {
  return {
    origin,
    scenarioId: "live",
    scenarioLabel: "Unité en observation",
    state: snapshot.state,
    plan,
    gateReasons,
    events: snapshot.events,
    resources: snapshot.resources,
    receivedAtBySource: snapshot.received_at_by_source,
    trace: null,
    episodeId,
    factBudgetMinutes: 5,
    expiresAt: expiresAt ?? plan?.expires_at ?? null,
  };
}

/** Group a list of codes into what a person must do, deduplicated by entity. */
export function gateGroups(codes: string[]): { title: string; codes: string[] }[] {
  const groups = new Map<string, string[]>();
  for (const code of codes) {
    const head =
      code.startsWith("stale_confirmation") || code.includes("confirmation")
        ? "Confirmations de ressources à renouveler"
        : code.startsWith("stale:")
          ? "Informations trop anciennes"
          : code.startsWith("missing:") || code === "missing_perimeter"
            ? "Informations manquantes"
            : code.includes("conflict")
              ? "Informations contradictoires"
              : "Autres contrôles";
    groups.set(head, [...(groups.get(head) ?? []), code]);
  }
  return [...groups].map(([title, list]) => ({ title, codes: list }));
}

// ---------------------------------------------------------------- unit switcher

export interface UnitSummary {
  id: string;
  name: string;
  decision: "recommend" | "no_change" | "abstain" | "pending";
  waiting: number;
  usable: number;
  dirty: number;
  longestWaitMinutes: number | null;
}

export function unitSummary(id: string, name: string, a: Assessment | null): UnitSummary {
  if (!a) return { id, name, decision: "pending", waiting: 0, usable: 0, dirty: 0, longestWaitMinutes: null };
  const s = situation(a.state, a.plan);
  const q = queueEntries(a.state);
  return {
    id,
    name,
    decision: a.plan ? a.plan.decision : a.gateReasons.length ? "abstain" : "pending",
    waiting: s.waiting,
    usable: s.usable,
    dirty: s.dirty,
    longestWaitMinutes: q.length ? Math.max(...q.map((e) => e.waitedMinutes)) : null,
  };
}

/** The single next step a person can take on a departure, in plain imperative French. */
export function nextStep(links: ChainLink[]): { text: string; tone: "ok" | "todo" | "blocked" | "unknown" } {
  const pending = links.find((l) => l.status !== "ok" && l.status !== "na");
  if (!pending) return { text: "Prête à partir", tone: "ok" };
  const verbs: Record<ChainLink["id"], [string, string]> = {
    medical: ["Obtenir l'avis médical de sortie", "Avis médical défavorable"],
    documents: ["Préparer les documents de sortie", "Documents bloqués"],
    escort: ["Confirmer l'accompagnant", "Accompagnant indisponible"],
    downstream: ["Obtenir l'accord de l'aval", "Aval complet : chercher une autre place"],
    transport: ["Demander le transport", "Aucun transport disponible"],
  };
  const [todo, blocked] = verbs[pending.id];
  if (pending.status === "blocked") return { text: blocked, tone: "blocked" };
  if (pending.status === "unknown")
    return { text: `Renseigner : ${pending.label.toLowerCase()}`, tone: "unknown" };
  return { text: todo, tone: "todo" };
}
