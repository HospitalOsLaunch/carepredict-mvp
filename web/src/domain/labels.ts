// Plain-French vocabulary for every backend code shown to a cadre de santé or a
// gestionnaire de lits. Codes stay untranslated in the detail views (title attribute)
// so support can trace them; unknown codes fall back to a readable form, never hidden.

import type { Action, BedState, Decision, ReadinessStage } from "../api/types";

const ENTITY: Record<string, string> = {
  unit: "unité",
  bed: "lit",
  patient: "patient",
  pool: "ressource",
  discharge: "logistique de sortie",
};

const RESOURCE: Record<string, string> = {
  staffed: "lits armés (personnel)",
  cleaning: "bionettoyage",
  transport: "transport sanitaire",
  downstream: "places d'aval",
};

const BLOCKERS: Record<string, string> = {
  patient_not_admitted: "Patient non hospitalisé dans l'unité",
  medical_authorization_not_confirmed: "Autorisation médicale de sortie non confirmée",
  discharge_logistics_missing: "Logistique de sortie non renseignée",
  documents_not_confirmed: "Documents de sortie non confirmés",
  escort_not_confirmed: "Accompagnant non confirmé",
  downstream_requirement_unknown: "Besoin d'aval non renseigné",
  transport_requirement_unknown: "Besoin de transport non renseigné",
  downstream_pool_unverified: "Structure d'aval non vérifiée",
  transport_pool_unverified: "Transporteur non vérifié",
  downstream_unavailable: "Aucune place d'aval confirmée",
  transport_unavailable: "Aucun transport disponible confirmé",
  downstream_acceptance_not_confirmed: "Accord de l'aval non confirmé",
  transport_not_requested: "Transport pas encore demandé",
};

const REASONS: Record<string, string> = {
  lower_simulated_waiting_cost_requires_human_approval:
    "Réduit l'attente simulée. Une validation humaine reste nécessaire.",
  no_admissible_simulated_improvement: "Aucune action n'améliore l'attente simulée.",
  simulated_improvement_rejected_due_to_resource_pressure:
    "Une action réduirait l'attente, mais surchargerait une ressource dans certains scénarios.",
  simulation_invariant_failure:
    "La simulation a détecté une incohérence interne : aucune proposition n'est faite.",
  missing_perimeter: "Le périmètre de l'unité n'est pas déclaré.",
  planner_event_budget_exceeded: "Trop d'événements à traiter pour une évaluation locale.",
  unresolved_local_action_requires_reconciliation: "Une action précédente n'est pas encore réconciliée.",
};

const WARNINGS: Record<string, string> = {
  simulated_resource_pressure_requires_review:
    "La simulation sollicite une ressource sous tension : à vérifier.",
  synthetic_learned_preparation_requires_real_validation:
    "Les délais de préparation viennent d'un modèle entraîné sur du synthétique.",
};

const PATTERNS: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [/^missing:(\w+):(.+)$/, (m) => `Information manquante : ${ENTITY[m[1]!] ?? m[1]} ${m[2]}`],
  [/^undeclared:(\w+):(.+)$/, (m) => `${cap(ENTITY[m[1]!] ?? m[1]!)} ${m[2]} hors périmètre déclaré`],
  [/^stale:(\w+):(.+)$/, (m) => `${cap(ENTITY[m[1]!] ?? m[1]!)} ${m[2]} : information périmée`],
  [
    /^conflicting_sources:(\w+):(.+)$/,
    (m) => `${cap(ENTITY[m[1]!] ?? m[1]!)} ${m[2]} : deux sources se contredisent`,
  ],
  [/^stale_confirmation:(\w+):(.+)$/, (m) => `Confirmation périmée : ${resource(m[1]!)} (${m[2]})`],
  [/^missing_confirmation:(\w+):(.+)$/, (m) => `Confirmation absente : ${resource(m[1]!)} (${m[2]})`],
  [
    /^conflicting_confirmation:(\w+):(.+)$/,
    (m) => `Confirmations contradictoires : ${resource(m[1]!)} (${m[2]})`,
  ],
  [/^unknown_availability:(\w+):(.+)$/, (m) => `Disponibilité inconnue : ${resource(m[1]!)} (${m[2]})`],
  [
    /^confirmation_exceeds_capacity:(\w+):(.+)$/,
    (m) => `Confirmation supérieure à la capacité : ${resource(m[1]!)} (${m[2]})`,
  ],
  [
    /^local_holds_exceed_observed_free:(\w+):(.+)$/,
    (m) => `Réservations locales supérieures au disponible : ${resource(m[1]!)} (${m[2]})`,
  ],
  [/^pool_confirmation_mismatch:(.+)$/, (m) => `Ressource ${m[1]} : capacité et confirmation divergent`],
  [/^unknown_pool_capacity:(.+)$/, (m) => `Ressource ${m[1]} : capacité inconnue`],
  [/^invalid_pool_scope:(.+)$/, (m) => `Ressource ${m[1]} : périmètre incohérent`],
  [/^orphan_discharge:(.+)$/, (m) => `Logistique de sortie sans patient hospitalisé : ${m[1]}`],
  [/^invalid_discharge_pool:(.+):(\w+)$/, (m) => `Sortie ${m[1]} : ${m[2]} incohérent`],
  [/^unknown_resources:(.+)$/, (m) => `Unité ${m[1]} : lits armés ou équipes inconnus`],
  [/^observed_overload:(.+)$/, (m) => `Unité ${m[1]} : plus de lits occupés que de lits armés`],
  [/^unknown_bed_state_or_unit:(.+)$/, (m) => `Lit ${m[1]} : état ou unité inconnus`],
  [/^occupancy_conflict:(.+)$/, (m) => `Lit ${m[1]} : occupation contradictoire`],
  [/^reservation_conflict:(.+)$/, (m) => `Lit ${m[1]} : réservation contradictoire`],
  [/^patient_location_conflict:(.+)$/, (m) => `Patient ${m[1]} : localisation contradictoire`],
  [/^source_import_rejected:(.+)$/, (m) => `Source ${m[1]} bloquée après un import rejeté`],
];

function cap(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function resource(code: string): string {
  return RESOURCE[code] ?? code;
}

/** Any backend reason, issue, gate or blocker code → one plain sentence. */
export function explain(code: string): string {
  const direct = BLOCKERS[code] ?? REASONS[code] ?? WARNINGS[code];
  if (direct) return direct;
  for (const [pattern, render] of PATTERNS) {
    const match = code.match(pattern);
    if (match) return render(match);
  }
  return code.replace(/[_:]/g, " ");
}

/** "bed:L14" → "lit L14" */
export function entityLabel(key: string): string {
  const [kind, ...rest] = key.split(":");
  return `${ENTITY[kind ?? ""] ?? kind} ${rest.join(":")}`;
}

export function isKnownCode(code: string): boolean {
  return explain(code) !== code.replace(/[_:]/g, " ");
}

export const STAGE: Record<ReadinessStage, { label: string; short: string }> = {
  medical_not_confirmed: { label: "En attente de l'autorisation médicale", short: "Avis médical" },
  logistics_blocked: { label: "Logistique bloquée", short: "Bloquée" },
  transport_to_request: { label: "Transport à demander", short: "Transport à demander" },
  ready_for_simulation: { label: "Prête à partir", short: "Prête" },
};

export const BED_STATE: Record<BedState, string> = {
  clean: "Propre",
  dirty: "À nettoyer",
  occupied: "Occupé",
  closed: "Fermé",
  unknown: "État inconnu",
};

export const DECISION: Record<Decision, string> = {
  recommend: "Proposition",
  no_change: "Rien à changer",
  abstain: "Abstention",
};

export const CAPABILITY: Record<string, string> = { oxygene: "Oxygène", oxygen: "Oxygène" };

export function capability(code: string): string {
  return CAPABILITY[code] ?? cap(code.replace(/[_-]/g, " "));
}

/** Imperative sentence naming exactly what the action does. */
export function actionTitle(action: Action): string {
  switch (action.kind) {
    case "no_op":
      return "Ne rien changer pour l'instant";
    case "prioritize_cleaning":
      return `Prioriser le bionettoyage du lit ${action.bed_id}`;
    case "reserve_bed":
      return `Réserver le lit ${action.bed_id} pour ${action.patient_id}`;
    case "request_transport":
      return `Demander le transport de ${action.patient_id}`;
  }
}

export function actionShort(action: Action): string {
  switch (action.kind) {
    case "no_op":
      return "Sans action";
    case "prioritize_cleaning":
      return `Nettoyer ${action.bed_id} en priorité`;
    case "reserve_bed":
      return `Réserver ${action.bed_id} → ${action.patient_id}`;
    case "request_transport":
      return `Transport ${action.patient_id} (${action.bed_id})`;
  }
}

export const TRACE_EVENT: Record<string, string> = {
  request_transport: "Transport demandé",
  departure_ready: "Patient prêt au départ",
  downstream_reserve: "Place d'aval réservée",
  transport_start: "Prise en charge transport",
  transport_end: "Retour du transport",
  depart: "Départ du patient",
  clean_start: "Début du bionettoyage",
  clean_end: "Lit propre",
  admit: "Admission",
  reserve: "Lit réservé",
  reservation_cancel: "Réservation annulée",
  arrival: "Arrivée (hypothèse)",
  resource_change: "Changement de capacité (hypothèse)",
  bed_admissions: "Ouverture ou fermeture d'un lit (hypothèse)",
};
