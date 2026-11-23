import { useSyncExternalStore } from "react";
import type { Action, Plan } from "../api/types";
import { actionShort, actionTitle, explain } from "../domain/labels";
import { type Assessment, clockPlus, comparison, minutesBetween } from "../domain/view";

/*
  Decision journal: every proposal HospitalOS made, and what people did with it.

  Lifecycle of one proposal (a record):
    proposed ──▶ validated ──▶ done
        │            └──────▶ abandoned  (« finalement non », with a reason)
        ├──▶ refused        (one-tap reason, optional note)
        ├──▶ expired        (no answer before it went stale)
        └──▶ superseded     (a newer evaluation replaced it)
  « Annuler » removes the person's last step (undo). Notes can be added at any time.
  An evaluation that abstains is kept too, so a colleague can see why nothing was proposed.

  Validating never sends anything: HospitalOS only keeps the trace, people act.
  Storage: this browser (localStorage) until the API exposes a shared journal
  (web/README.md, « Suite côté API »). Demonstration history is generated, read-only
  and flagged `sample`.
*/

export type EventType =
  | "proposed"
  | "abstained"
  | "validated"
  | "done"
  | "refused"
  | "abandoned"
  | "expired"
  | "superseded"
  | "note";

export type Status =
  "pending" | "validated" | "done" | "refused" | "abandoned" | "expired" | "superseded" | "abstained";

export interface Person {
  id: string;
  name: string;
  role: string;
}

export interface DecisionEvent {
  at: string;
  type: EventType;
  /** null: HospitalOS itself (proposal, expiry, replacement). */
  by: Person | null;
  reason?: string;
  note?: string;
}

export interface DecisionRecord {
  id: string;
  planId: string;
  unitId: string;
  unitName: string;
  situation: string;
  stateAt: string;
  proposedAt: string;
  expiresAt: string;
  action: Action | null;
  title: string;
  short: string;
  /** 0: HospitalOS' first choice; 1+: another useful option chosen instead. */
  rank: number;
  deltaRatio: number | null;
  horizonEnd: string;
  why: string[];
  events: DecisionEvent[];
  sample?: boolean;
}

export const REASONS: { id: string; label: string }[] = [
  { id: "already_done", label: "Déjà fait" },
  { id: "information_missing", label: "Information manquante" },
  { id: "clinical_priority", label: "Autre priorité clinique" },
  { id: "resource_unavailable", label: "Ressource indisponible" },
  { id: "wrong_bed", label: "Lit inadapté" },
  { id: "other", label: "Autre raison" },
];
const EXTRA_REASONS: Record<string, string> = { preferred_option: "Autre option préférée" };

export const reasonLabel = (id: string | undefined): string | null =>
  id ? (REASONS.find((r) => r.id === id)?.label ?? EXTRA_REASONS[id] ?? id) : null;

export const STATUS: Record<Status, { label: string; tone: "brand" | "todo" | "ok" | "quiet" | "sun" }> = {
  pending: { label: "En attente de réponse", tone: "brand" },
  validated: { label: "Validée, à faire", tone: "todo" },
  done: { label: "Faite", tone: "ok" },
  refused: { label: "Refusée", tone: "quiet" },
  abandoned: { label: "Finalement non", tone: "quiet" },
  expired: { label: "Sans réponse", tone: "quiet" },
  superseded: { label: "Remplacée", tone: "quiet" },
  abstained: { label: "Pas de proposition", tone: "sun" },
};

const STATUS_OF: Partial<Record<EventType, Status>> = {
  proposed: "pending",
  abstained: "abstained",
  validated: "validated",
  done: "done",
  refused: "refused",
  abandoned: "abandoned",
  expired: "expired",
  superseded: "superseded",
};

/** Status from the last step; a pending proposal past its expiry reads as « sans réponse ». */
export function statusOf(r: DecisionRecord, now?: string): Status {
  let s: Status = "pending";
  for (const e of r.events) s = STATUS_OF[e.type] ?? s;
  if (s === "pending" && now && minutesBetween(r.expiresAt, now) > 0) return "expired";
  return s;
}

/** « −30 % », with one decimal under 10 % so a small effect never reads as zero. */
export function deltaText(ratio: number): string {
  const digits = Math.abs(ratio) < 0.095 ? 1 : 0;
  return new Intl.NumberFormat("fr-FR", {
    style: "percent",
    maximumFractionDigits: digits,
    signDisplay: "exceptZero",
  })
    .format(ratio)
    .replace("-", "−");
}

export const lastStep = (r: DecisionRecord): DecisionEvent | undefined =>
  [...r.events].reverse().find((e) => e.type !== "note");

/** What the person does next, off-system, once they validate. */
export function todoHint(action: Action | null): string {
  if (!action) return "";
  switch (action.kind) {
    case "request_transport":
      return `Appelez le transport pour ${action.patient_id}.`;
    case "prioritize_cleaning":
      return `Prévenez le bionettoyage : ${action.bed_id} en premier.`;
    case "reserve_bed":
      return `Bloquez ${action.bed_id} pour ${action.patient_id} dans votre outil habituel.`;
    default:
      return "";
  }
}

// ---------------------------------------------------------------- storage

const KEY = "hospitalos.journal.v1";
const ME = "hospitalos.me.v1";
const CAP = 1000;

type Listener = () => void;
const listeners = new Set<Listener>();
let cache: DecisionRecord[] | null = null;
let samples: DecisionRecord[] = [];
let snapshot: DecisionRecord[] = [];
let me: Person | null = null;
let storageOk = true;

function load(): DecisionRecord[] {
  if (cache) return cache;
  try {
    const raw = window.localStorage.getItem(KEY);
    cache = raw ? (JSON.parse(raw) as DecisionRecord[]) : [];
  } catch {
    cache = [];
  }
  return cache;
}

function rebuild() {
  snapshot = [...load(), ...samples].sort((a, b) => Date.parse(b.proposedAt) - Date.parse(a.proposedAt));
}

function commit(next: DecisionRecord[]) {
  cache = next.slice(-CAP);
  try {
    window.localStorage.setItem(KEY, JSON.stringify(cache));
    storageOk = true;
  } catch {
    storageOk = false;
  }
  rebuild();
  listeners.forEach((l) => l());
}

function subscribe(l: Listener) {
  listeners.add(l);
  const onStorage = (e: StorageEvent) => {
    if (e.key !== KEY && e.key !== ME) return;
    cache = null;
    me = null;
    rebuild();
    l();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(l);
    window.removeEventListener("storage", onStorage);
  };
}

export function getMe(): Person {
  if (me) return me;
  try {
    const raw = window.localStorage.getItem(ME);
    if (raw) return (me = JSON.parse(raw) as Person);
  } catch {
    /* fall through */
  }
  me = { id: `p-${Math.random().toString(36).slice(2, 10)}`, name: "", role: "" };
  try {
    window.localStorage.setItem(ME, JSON.stringify(me));
  } catch {
    /* kept for this session only */
  }
  return me;
}

/** How a person is named on screen: « vous » for the current person. */
export function who(p: Person | null, current: Person): string {
  if (!p) return "HospitalOS";
  if (p.id === current.id) return current.name ? `${current.name} (vous)` : "Vous";
  return p.name || "Un collègue";
}

function update(id: string, change: (r: DecisionRecord) => DecisionRecord | null) {
  const all = load();
  const i = all.findIndex((r) => r.id === id);
  if (i < 0) return;
  const next = change(all[i]!);
  if (!next) return;
  const copy = [...all];
  copy[i] = next;
  commit(copy);
}

export const journal = {
  get storageOk() {
    return storageOk;
  },

  setMe(p: Pick<Person, "name" | "role">) {
    me = { ...getMe(), name: p.name.trim().slice(0, 40), role: p.role.trim().slice(0, 40) };
    try {
      window.localStorage.setItem(ME, JSON.stringify(me));
    } catch {
      /* session only */
    }
    rebuild();
    listeners.forEach((l) => l());
  },

  /**
   * Keep a trace of what HospitalOS proposed (idempotent). A newer proposal for the same
   * unit replaces older ones still waiting for an answer.
   */
  register(record: DecisionRecord) {
    const all = load();
    const existing = all.find((r) => r.id === record.id);
    const last = existing?.events[existing.events.length - 1];
    // Already current: nothing to do. Shown again after being replaced (a demonstration
    // situation picked again): it becomes current again.
    if (existing && last?.type !== "superseded") return;
    const next = all.map((r) =>
      r.id === record.id
        ? { ...r, events: r.events.slice(0, -1) }
        : r.unitId === record.unitId && r.planId !== record.planId && statusOf(r) === "pending"
          ? { ...r, events: [...r.events, { at: record.proposedAt, type: "superseded" as const, by: null }] }
          : r,
    );
    commit(existing ? next : [...next, record]);
  },

  act(id: string, type: EventType, at: string, extra: { reason?: string; note?: string } = {}) {
    update(id, (r) => ({ ...r, events: [...r.events, { at, type, by: getMe(), ...extra }] }));
  },

  /** Choose another useful option instead of HospitalOS' first choice. */
  choose(main: DecisionRecord, option: DecisionRecord, at: string) {
    const all = load().map((r) =>
      r.id === main.id
        ? {
            ...r,
            events: [...r.events, { at, type: "refused" as const, by: getMe(), reason: "preferred_option" }],
          }
        : r,
    );
    const existing = all.find((r) => r.id === option.id);
    const chosen: DecisionRecord = existing
      ? { ...existing, events: [...existing.events, { at, type: "validated", by: getMe() }] }
      : { ...option, events: [...option.events, { at, type: "validated", by: getMe() }] };
    commit([...all.filter((r) => r.id !== option.id), chosen]);
  },

  /** Undo the current person's last step on a record. */
  undo(id: string) {
    update(id, (r) => {
      const i = r.events.length - 1;
      const last = r.events[i];
      if (!last || !last.by || last.by.id !== getMe().id) return null;
      return { ...r, events: r.events.slice(0, i) };
    });
  },

  /** Forget a record the current person just created (undo of « choisir plutôt »). */
  discard(id: string) {
    commit(load().filter((r) => r.id !== id));
  },

  expire(id: string) {
    update(id, (r) =>
      statusOf(r) === "pending"
        ? { ...r, events: [...r.events, { at: r.expiresAt, type: "expired", by: null }] }
        : null,
    );
  },

  /** Demonstration history, generated around the state instant. Never written to storage. */
  setSamples(next: DecisionRecord[]) {
    samples = next;
    rebuild();
    listeners.forEach((l) => l());
  },

  /** Tests only. */
  reset() {
    cache = null;
    samples = [];
    me = null;
    rebuild();
  },
};

export function useJournal(): { records: DecisionRecord[]; me: Person } {
  const records = useSyncExternalStore(subscribe, () => {
    if (!cache) rebuild();
    return snapshot;
  });
  return { records, me: getMe() };
}

// ---------------------------------------------------------------- records from proposals

const actionKey = (a: Action | null) =>
  a ? `${a.kind}:${a.bed_id ?? "-"}:${a.patient_id ?? "-"}` : "abstain";

/** The record of HospitalOS' first choice (rank 0) or another useful option (rank ≥ 1). */
export function recordFor(
  a: Assessment,
  unit: { id: string; name: string },
  plan: Plan,
  action: Action = plan.selected,
  rank = 0,
): DecisionRecord {
  const cmp = comparison(plan);
  const candidate = plan.candidates.find((c) => actionKey(c.action) === actionKey(action));
  const base = cmp.baseline?.mean_waiting_patient_minutes ?? 0;
  const delta =
    candidate && cmp.baseline && base > 0 ? (candidate.mean_waiting_patient_minutes - base) / base : null;
  const abstain = plan.decision === "abstain";
  return {
    id: `${plan.plan_id}:${actionKey(abstain ? null : action)}`,
    planId: plan.plan_id,
    unitId: unit.id,
    unitName: unit.name,
    situation: a.scenarioLabel,
    stateAt: a.state.at,
    proposedAt: plan.created_at,
    expiresAt: a.expiresAt ?? plan.expires_at,
    action: abstain ? null : action,
    title: abstain ? "Pas de proposition : données à vérifier" : actionTitle(action),
    short: abstain ? "Pas de proposition" : actionShort(action),
    rank,
    deltaRatio: abstain ? null : delta,
    horizonEnd: clockPlus(plan.created_at, plan.horizon_minutes),
    why: (abstain ? plan.reasons : rank === 0 ? plan.reasons : []).slice(0, 4).map(explain),
    events: [{ at: plan.created_at, type: abstain ? "abstained" : "proposed", by: null }],
  };
}

/** Abstention from live gates (no plan computed). */
export function abstentionRecord(
  a: Assessment,
  unit: { id: string; name: string },
  key: string,
): DecisionRecord {
  return {
    id: `${key}:abstain`,
    planId: key,
    unitId: unit.id,
    unitName: unit.name,
    situation: a.scenarioLabel,
    stateAt: a.state.at,
    proposedAt: a.state.at,
    expiresAt: a.state.at,
    action: null,
    title: "Pas de proposition : données à vérifier",
    short: "Pas de proposition",
    rank: 0,
    deltaRatio: null,
    horizonEnd: a.state.at,
    why: a.gateReasons.slice(0, 4).map(explain),
    events: [{ at: a.state.at, type: "abstained", by: null }],
  };
}

/**
 * Other options worth showing next to the first choice: simulated without any rule
 * violation and strictly better than doing nothing. Effects were simulated one by one,
 * never combined.
 */
export function otherOptions(plan: Plan): { action: Action; deltaRatio: number }[] {
  if (plan.decision !== "recommend") return [];
  const cmp = comparison(plan);
  const base = cmp.baseline;
  if (!base || base.mean_waiting_patient_minutes <= 0) return [];
  return cmp.ranked
    .filter(
      (c) =>
        c.action.kind !== "no_op" &&
        actionKey(c.action) !== actionKey(plan.selected) &&
        c.violations.length === 0 &&
        c.objective < base.objective - 1e-9,
    )
    .slice(0, 3)
    .map((c) => ({
      action: c.action,
      deltaRatio:
        (c.mean_waiting_patient_minutes - base.mean_waiting_patient_minutes) /
        base.mean_waiting_patient_minutes,
    }));
}

// ---------------------------------------------------------------- demonstration history

const NADIA: Person = { id: "demo-nadia", name: "Nadia B.", role: "Gestionnaire de lits" };
const KARIM: Person = { id: "demo-karim", name: "Karim T.", role: "Cadre de nuit" };
const SOPHIE: Person = { id: "demo-sophie", name: "Sophie L.", role: "Cadre de santé" };

/** A plausible shift before the state instant, across the demonstration units. Read-only. */
export function demoHistory(stateAt: string, units: { id: string; name: string }[]): DecisionRecord[] {
  const name = (id: string) => units.find((u) => u.id === id)?.name ?? id;
  const t = (min: number) => new Date(Date.parse(stateAt) + min * 60000).toISOString();
  const rec = (
    n: number,
    unitId: string,
    at: number,
    action: Action | null,
    delta: number | null,
    why: string[],
    events: Array<[number, EventType, Person | null, string?, string?]>,
  ): DecisionRecord => ({
    id: `demo-${n}`,
    planId: `demo-plan-${n}`,
    unitId,
    unitName: name(unitId),
    situation: "Historique de démonstration",
    stateAt: t(at),
    proposedAt: t(at),
    expiresAt: t(at + 15),
    action,
    title: action ? actionTitle(action) : "Pas de proposition : données à vérifier",
    short: action ? actionShort(action) : "Pas de proposition",
    rank: 0,
    deltaRatio: delta,
    horizonEnd: clockPlus(t(at), 480),
    why,
    events: [
      { at: t(at), type: action ? "proposed" : "abstained", by: null },
      ...events.map(([m, type, by, reason, note]) => ({
        at: t(at + m),
        type,
        by,
        ...(reason ? { reason } : {}),
        ...(note ? { note } : {}),
      })),
    ],
    sample: true,
  });
  const tr = (p: string, b: string): Action => ({ kind: "request_transport", patient_id: p, bed_id: b });
  const cl = (b: string): Action => ({ kind: "prioritize_cleaning", patient_id: null, bed_id: b });
  const rs = (b: string, p: string): Action => ({ kind: "reserve_bed", patient_id: p, bed_id: b });
  const MP = "medecine-polyvalente";
  const GE = "court-sejour-geriatrique";
  const MI = "medecine-interne";
  const PN = "pneumologie";
  return [
    rec(
      1,
      MP,
      -38,
      cl("L08"),
      -0.12,
      ["Le lit L08 est le seul lit propre possible pour U-1043."],
      [
        [2, "validated", NADIA],
        [19, "done", NADIA],
      ],
    ),
    rec(
      2,
      GE,
      -70,
      tr("G-2207", "G12"),
      -0.18,
      ["Toutes les autres étapes de sortie de G-2207 sont confirmées."],
      [[4, "refused", KARIM, "clinical_priority", "Patient revu par le médecin, sortie décalée à 14 h."]],
    ),
    rec(3, MI, -105, rs("I07", "U-2981"), -0.06, [], []),
    rec(4, MP, -140, null, null, ["Lit L03 : information périmée"], []),
    rec(
      5,
      PN,
      -170,
      rs("R05", "U-4410"),
      -0.21,
      ["Le lit R05 est équipé oxygène."],
      [
        [3, "validated", KARIM],
        [26, "done", KARIM],
        [27, "note", KARIM, undefined, "Fait avec l'IDE de nuit, R05 confirmé à 06:05."],
      ],
    ),
    rec(
      6,
      MP,
      -890,
      tr("P-0377", "L06"),
      -0.24,
      ["Toutes les autres étapes de sortie de P-0377 sont confirmées."],
      [[5, "refused", SOPHIE, "already_done", "Transport déjà commandé par l'IDE à 15 h 50."]],
    ),
    rec(
      7,
      GE,
      -960,
      cl("G15"),
      -0.04,
      [],
      [
        [6, "validated", SOPHIE],
        [40, "abandoned", SOPHIE, "resource_unavailable", "Équipe de bionettoyage en renfort aux urgences."],
      ],
    ),
    rec(8, MI, -1010, rs("I12", "U-2940"), -0.09, [], [[50, "superseded", null]]),
  ];
}

// ---------------------------------------------------------------- export and handover

const csvCell = (v: string) => `"${v.replace(/"/g, '""')}"`;

export function toCsv(records: DecisionRecord[], current: Person, now: string): string {
  const fmt = (iso: string | undefined) =>
    iso
      ? new Intl.DateTimeFormat("fr-FR", {
          dateStyle: "short",
          timeStyle: "short",
          timeZone: "Europe/Paris",
        }).format(new Date(iso))
      : "";
  const head = [
    "Unité",
    "Proposée le",
    "Proposition",
    "Statut",
    "Effet simulé sur l'attente",
    "Décidée par",
    "Rôle",
    "Décidée le",
    "Motif",
    "Notes",
    "Identifiant",
  ];
  const rows = records.map((r) => {
    const step = lastStep(r);
    const human = [...r.events].reverse().find((e) => e.by && e.type !== "note");
    return [
      r.unitName,
      fmt(r.proposedAt),
      r.title,
      STATUS[statusOf(r, now)].label,
      r.deltaRatio != null ? `${Math.round(r.deltaRatio * 100)} %` : "",
      human ? who(human.by, current) : "",
      human?.by?.role ?? "",
      fmt(human?.at ?? (step?.by ? step.at : undefined)),
      reasonLabel(human?.reason) ?? "",
      r.events
        .filter((e) => e.note)
        .map((e) => e.note)
        .join(" | "),
      r.id,
    ];
  });
  return [head, ...rows].map((row) => row.map(csvCell).join(";")).join("\r\n");
}

/** Plain-text handover for the next shift: what is left to do, done, refused, unanswered. */
export function handover(records: DecisionRecord[], current: Person, now: string, title: string): string {
  const by = (s: Status) => records.filter((r) => statusOf(r, now) === s);
  const line = (r: DecisionRecord) => {
    const human = [...r.events].reverse().find((e) => e.by && e.type !== "note");
    const reason = reasonLabel(human?.reason);
    const note = [...r.events].reverse().find((e) => e.note)?.note;
    return `- ${r.unitName} : ${r.short}${human ? ` (${who(human.by, current)})` : ""}${reason ? `, ${reason.toLowerCase()}` : ""}${note ? `. ${note}` : ""}`;
  };
  const block = (label: string, list: DecisionRecord[]) =>
    list.length ? [`${label} (${list.length})`, ...list.map(line), ""] : [];
  return [
    title,
    "",
    ...block("À faire", by("validated")),
    ...block("En attente de réponse", by("pending")),
    ...block("Faites", by("done")),
    ...block("Refusées", by("refused")),
    ...block("Finalement non", by("abandoned")),
    ...block("Sans réponse", by("expired")),
    "Propositions HospitalOS en mode observation : rien n'a été envoyé par l'outil.",
  ].join("\n");
}
