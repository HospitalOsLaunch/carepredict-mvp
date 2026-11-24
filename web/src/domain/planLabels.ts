// Words for the 24-hour plan engine (src/hospitalos/decision_support). The engine speaks in
// stable codes; the screen speaks to a cadre de santé. Every code without a translation is
// shown as is: a missing label must never hide what the engine said.
//
// No figure is invented here (T32): numbers only come from the engine's own strings.

import type { DsAction, DsSnapshot } from "../api/decision";

type Reinforcement = DsSnapshot["reinforcements"][number];

export const BASIS: Record<string, { label: string; tone: "fact" | "choice" | "hypothesis" | "option" }> = {
  observed_authorization: { label: "autorisation médicale observée", tone: "fact" },
  validated_instruction: { label: "consigne validée", tone: "choice" },
  hypothesis_only: { label: "hypothèse", tone: "hypothesis" },
  resource_option: { label: "option de renfort", tone: "option" },
};

export const SOURCE: Record<string, string> = {
  internal_pool: "pool interne",
  interim: "intérim",
  shared_unit: "prêt d'une autre unité",
};

export const CONFIRMATION: Record<string, string> = {
  confirmed: "confirmé",
  requested: "demandé, non confirmé",
  not_requested: "non demandé",
  unknown: "confirmation inconnue",
};

export const AUTHORIZATION: Record<string, string> = {
  authorized: "sortie autorisée",
  not_authorized: "sortie non autorisée",
  revoked: "autorisation retirée",
  unknown: "autorisation inconnue",
};

/**
 * Where a reinforcement comes from, always naming the lending unit for a loan: « prêt d'une
 * autre unité » alone would hide which unit is left short.
 */
export function provenance(r: Reinforcement | undefined): string {
  if (!r) return "provenance inconnue";
  if (r.source === "shared_unit") {
    return r.lending_unit ? `prêté par ${r.lending_unit}` : "prêté par une unité non renseignée";
  }
  return SOURCE[r.source] ?? r.source;
}

/** One line per action, the destination and the provenance of every resource explicit. */
export function actionText(a: DsAction, snapshot: DsSnapshot | null, at: (iso: string) => string): string {
  if (a.type === "coordinate_discharge")
    return `Coordonner la sortie de ${a.target} : départ visé à ${at(a.window_start)}, transport demandé maintenant, bionettoyage après le départ`;
  if (a.type === "reinforcement") {
    const r = snapshot?.reinforcements.find((x) => x.option_id === a.target);
    return `Renfort ${r?.skill ?? ""} de ${at(a.window_start)} à ${at(a.window_end)}, ${provenance(r)} (${a.target})`;
  }
  if (a.type === "locked_discharge") return `Sortie de ${a.target} à ${at(a.window_start)}`;
  return `Présence de ${a.target} prolongée jusqu'à ${at(a.window_start)}`;
}

/** Short form for lists and the decision journal. */
export function actionShort(a: DsAction, snapshot: DsSnapshot | null, at: (iso: string) => string): string {
  if (a.type === "coordinate_discharge" || a.type === "locked_discharge")
    return `sortie ${a.target} à ${at(a.window_start)}`;
  if (a.type === "reinforcement") {
    const r = snapshot?.reinforcements.find((x) => x.option_id === a.target);
    return `renfort ${r?.skill ?? ""} ${a.target}${r?.source === "shared_unit" ? ` (${provenance(r)})` : ""}`;
  }
  return `prolongation ${a.target}`;
}

// ---------------------------------------------------------------- reasons and conditions

const REASON: Record<string, string> = {
  lexicographic_objective_improvement_requires_human_approval:
    "Le plan fait mieux que la pratique habituelle : il attend votre décision.",
  habitual_practice_preferred_no_material_improvement:
    "Aucun plan ne fait sensiblement mieux que la pratique habituelle.",
  abstention_data_insufficient: "Données insuffisantes : HospitalOS préfère ne rien proposer.",
  complements_to_locked_scenario_require_human_approval:
    "Des compléments sont proposés autour de vos choix : ils attendent votre décision.",
  conditional_simulation_of_hypothesis_not_executable:
    "Simulation d'une hypothèse : elle ne peut pas devenir un plan à appliquer.",
  locked_scenario_violates_constraints: "Vos choix enfreignent une contrainte : ce plan est impossible.",
};

/**
 * Reasons a person needs. The engine's numeric trace (« tier1 … », « reported … ») repeats
 * the figures already shown with their sources, so it stays in the calculation details.
 */
export function humanReasons(reasons: string[]): string[] {
  const out: string[] = [];
  for (const r of reasons) {
    if (REASON[r]) out.push(REASON[r]);
    else if (r.startsWith("plan remains insufficient"))
      out.push("Même avec ce plan, des soins restent non couverts : il réduit le manque sans le combler.");
  }
  return out;
}

const CONDITION: Record<string, string | null> = {
  medical_authorization_observed_at_decision: "autorisation médicale observée au moment du calcul",
  revalidate_authorization_before_approval: "revérifier l'autorisation avant de valider",
  transport_requested_now_lead_time_respected: "demander le transport maintenant",
  cleaning_only_after_effective_departure: "bionettoyage seulement après le départ effectif",
  "fixed departure hour": "heure de départ imposée",
  "basis:validated_instruction": "consigne validée",
  "basis:hypothesis_only": "hypothèse seulement",
  user_lock_not_a_system_clinical_decision: "votre choix, pas une décision clinique du système",
  "confirmation:requested": "demandé, non confirmé",
  "confirmation:confirmed": "confirmé",
  "requested, NOT confirmed -> result conditional on its presence": "le résultat suppose qu'il vienne",
};

function subject(prefix: string): string {
  const [kind, a, b] = prefix.split(":");
  if (kind === "coord") return `Sortie de ${a}`;
  if (kind === "renfort") return `Renfort ${a}`;
  if (kind === "lock" && a === "locked_discharge") return `Sortie imposée de ${b}`;
  if (kind === "lock" && a === "locked_extension") return `Prolongation de ${b}`;
  return prefix;
}

/** Conditions grouped by what they are about, one line each. */
export function groupedConditions(conditions: string[]): Array<{ about: string; items: string[] }> {
  const groups = new Map<string, string[]>();
  for (const c of conditions) {
    const cut = c.lastIndexOf(": ");
    const [head, code] = cut < 0 ? ["", c] : [c.slice(0, cut), c.slice(cut + 2)];
    if (code.startsWith("skill:")) continue; // already in the action line
    const label = code in CONDITION ? CONDITION[code] : code;
    if (!label) continue;
    const about = head ? subject(head) : "Plan";
    groups.set(about, [...(groups.get(about) ?? []), label]);
  }
  return [...groups].map(([about, items]) => ({ about, items }));
}

export function uncertainty(u: string): string {
  let m = /^(\d+) forecast scenarios/.exec(u);
  if (m) return `Calculé sur ${m[1]} scénarios, les mêmes que ceux qui ont servi à choisir le plan.`;
  m = /^uncovered minutes range over scenarios: ([\d.]+)\.\.([\d.]+)/.exec(u);
  if (m) return `Selon le scénario, de ${Number(m[1])} à ${Number(m[2])} minutes de soins non couvertes.`;
  if (u.startsWith("pointwise scenario means"))
    return "Moyennes heure par heure : pas une garantie sur toute la période.";
  if (u.startsWith("synthetic declared distributions"))
    return "Durées déclarées pour la démonstration, non calibrées sur un établissement réel.";
  return u;
}

const REJECT: Record<string, string> = {
  no_target_hour_before_habitual_plan: "aucune heure utile avant le départ déjà prévu",
  medical_authorization_not_authorized: "sortie non autorisée",
  medical_authorization_revoked: "autorisation retirée",
  destination_unknown: "destination inconnue",
  transport_need_unknown: "besoin de transport inconnu",
  readiness_estimate_unknown: "heure de préparation inconnue",
  "obstacle:aval_non_confirme": "aval non confirmé",
};

/** Why an option was left out, naming the lending unit when a loan would leave it short. */
export function rejection(
  key: string,
  codes: string,
  snapshot: DsSnapshot | null,
): { about: string; why: string } {
  const r = snapshot?.reinforcements.find((x) => x.option_id === key);
  const about = r ? `Renfort ${r.skill} ${key}, ${provenance(r)}` : `Sortie de ${key}`;
  const why = codes
    .split(",")
    .map((c) => {
      const m = /^violates_lending_unit_minimum:([^:]+):(\d+)-(\d+)<(\d+)$/.exec(c);
      if (m) return `le prêt laisserait ${m[1]} sous son minimum (${m[2]} − ${m[3]}, minimum ${m[4]})`;
      return REJECT[c] ?? c;
    })
    .join(", ");
  return { about, why };
}

/** A diagnostic in words, the engine code kept alongside for whoever investigates. */
export function diagnostic(d: string): string {
  let m = /^roster_unknown:([^:]+):(.+)$/.exec(d);
  if (m) return `Planning ${m[1]} inconnu sur ${m[2]}`;
  m = /^locked_transport_unavailable:([^:]+):/.exec(d);
  if (m) return `Aucun transport disponible pour la sortie imposée de ${m[1]}`;
  return d;
}
