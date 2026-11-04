import type { AgentPolicy, AgentStatus, EnginePolicy } from "../api/types";
import type { WorkerOut } from "../api/types_agent";

/**
 * What the administrator needs to read the agent's engines: what each one is, whether the
 * agent will really use it, and if not, what is missing — in the words of the agent's own
 * router (services/admissions_agent/router.py, skip_reason), so the screen never promises
 * what the agent will not do.
 */

export const ENGINE_ORDER = ["playbook", "open_light", "open_heavy", "closed_fast", "closed_best"] as const;

export const KIND: Record<EnginePolicy["kind"], { text: string; tone: string; where: string }> = {
  playbook: { text: "Script", tone: "bg-ink text-white", where: "Sur le poste, sans modèle : rien ne sort." },
  openai_compatible: {
    text: "Open source",
    tone: "bg-lagoon-soft text-lagoon-dark",
    where: "Modèle hébergé par le groupe : les écrans restent dans votre infrastructure."
  },
  anthropic: {
    text: "Propriétaire",
    tone: "bg-violet-soft text-violet-dark",
    where: "Les captures d'écran partent chez Anthropic, sous contrat."
  }
};

/** How to make an engine available on a worker (README of the agent, « Variables »). */
export const SETUP: Record<string, string> = {
  playbook: "Livré avec l'agent.",
  open_light: "Sur le poste : OPEN_LIGHT_URL (point d'accès vLLM du groupe), puis une calibration.",
  open_heavy: "Sur le poste : OPEN_HEAVY_URL (point d'accès vLLM du groupe), puis une calibration.",
  closed_fast: "Sur le poste : ANTHROPIC_API_KEY.",
  closed_best: "Sur le poste : ANTHROPIC_API_KEY."
};

export const TASKS: Record<string, { title: string; lead: string; writes: boolean; scriptOnly?: string }> = {
  sync_inbox: {
    title: "Relever les demandes du portail",
    lead: "Lecture seule : l'agent lit la liste des dossiers et les dépose dans HospitalOS.",
    writes: false
  },
  reply_portal: {
    title: "Reporter la réponse sur le portail",
    lead: "Écriture chez l'adresseur : chaque saisie est relue par le script avant d'être déclarée faite.",
    writes: true
  },
  sync_movements: {
    title: "Relever les mouvements du logiciel de lits",
    lead: "Lecture seule : entrées, sorties et mutations du jour.",
    writes: false,
    scriptOnly: "Par script seulement : aucun modèle ne sait encore lire cet écran."
  }
};

export type Preset = "economie" | "souverain" | "qualite";

export const PRESETS: Record<Preset, { title: string; lead: string; routes: Record<string, string[]> }> = {
  economie: {
    title: "Économie",
    lead: "Script, puis open source, puis propriétaire en dernier recours.",
    routes: { sync_inbox: ["playbook", "open_light", "closed_fast"], reply_portal: ["playbook", "open_heavy", "closed_best"] }
  },
  souverain: {
    title: "Souveraineté",
    lead: "Aucun écran ne sort de votre infrastructure : script et modèles auto-hébergés.",
    routes: { sync_inbox: ["playbook", "open_light", "open_heavy"], reply_portal: ["playbook", "open_heavy"] }
  },
  qualite: {
    title: "Fiabilité",
    lead: "Script, puis directement les meilleurs modèles du marché.",
    routes: { sync_inbox: ["playbook", "closed_fast", "closed_best"], reply_portal: ["playbook", "closed_best"] }
  }
};

export function presetOf(policy: AgentPolicy): Preset | null {
  for (const [name, preset] of Object.entries(PRESETS) as Array<[Preset, (typeof PRESETS)[Preset]]>) {
    if (Object.entries(preset.routes).every(([kind, chain]) => JSON.stringify(policy.routes[kind] ?? []) === JSON.stringify(chain)))
      return name;
  }
  return null;
}

export const BASIS: Record<NonNullable<EnginePolicy["identifiable_basis"]>, { label: string; reference: string | null }> = {
  hds: { label: "Hébergement certifié HDS", reference: "N° du certificat HDS de l'hébergeur" },
  contrat: { label: "Contrat couvrant les données de santé", reference: "Référence du contrat ou de l'avenant" },
  demonstration: { label: "Données de démonstration seulement", reference: null }
};

/** Where each engine stands on the workers that are online. */
export interface Availability {
  online: number;
  ready: string[];
  missing: Array<{ worker: string; detail: string | null }>;
}

export function availability(name: string, workers: WorkerOut[]): Availability {
  const online = workers.filter((w) => w.online);
  const ready: string[] = [];
  const missing: Availability["missing"] = [];
  for (const w of online) {
    const e = w.engines.find((x) => x.name === name);
    if (e?.configured) ready.push(w.agent_id);
    else missing.push({ worker: w.agent_id, detail: e?.detail ?? "non signalé par ce poste" });
  }
  return { online: online.length, ready, missing };
}

export type Readiness = { ready: true } | { ready: false; reason: string; fix?: string };

/**
 * Will the agent use this engine for this task? Same checks, in the same order, as the
 * agent's router; plus « no worker online », which the router cannot see.
 */
export function readiness(
  name: string,
  task: string,
  policy: AgentPolicy,
  workers: WorkerOut[],
  status: Pick<AgentStatus, "calibrations" | "spent_today_usd">
): Readiness {
  const engine = policy.engines[name];
  if (!engine) return { ready: false, reason: "moteur inconnu" };
  if (!engine.enabled) return { ready: false, reason: "désactivé", fix: "Activez-le dans sa carte, plus bas." };
  if (engine.kind !== "playbook" && task === "sync_movements") return { ready: false, reason: "relève des mouvements réservée au script" };
  const where = availability(name, workers);
  if (where.online === 0) return { ready: false, reason: "aucun poste en ligne", fix: "Démarrez l'agent sur un poste de l'établissement." };
  if (engine.kind === "playbook" && !workers.some((w) => w.online && w.playbooks.some((p) => (p.tasks as string[]).includes(task))))
    return { ready: false, reason: "aucun script pour cette tâche sur les postes", fix: "Livrez le script de ce logiciel avec l'agent (playbooks/*.yaml)." };
  if (where.ready.length === 0) return { ready: false, reason: "non configuré sur les postes", fix: SETUP[name] };
  if (engine.kind !== "playbook" && !engine.identifiable_data_allowed)
    return {
      ready: false,
      reason: "pas autorisé à voir des données identifiantes",
      fix: "Les portails affichent des noms de patients : autorisez-le, avec sa justification."
    };
  if (engine.min_calibration != null) {
    const score = status.calibrations[name]?.hit_rate;
    if (score === undefined)
      return { ready: false, reason: "jamais calibré", fix: `Sur le poste : python -m services.admissions_agent calibrate --engine ${name}` };
    if (score < engine.min_calibration)
      return {
        ready: false,
        reason: `calibration insuffisante (${pct(score)} < ${pct(engine.min_calibration)})`,
        fix: `Recalibrer : python -m services.admissions_agent calibrate --engine ${name}`
      };
  }
  if (engine.kind !== "playbook") {
    if ((policy.task_budget_usd[task] ?? 0) <= 0) return { ready: false, reason: "budget de la tâche à 0", fix: "Donnez un budget à la tâche." };
    if (status.spent_today_usd >= policy.daily_budget_usd)
      return { ready: false, reason: "plafond du jour atteint", fix: "Il se libère à minuit, ou relevez le plafond." };
  }
  return { ready: true };
}

export function pct(v: number): string {
  return `${Math.round(v * 100)} %`;
}

export function usd(v: number, digits = 2): string {
  return `${v.toLocaleString("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits })} $`;
}

/** What the agent will actually do for a task, in one sentence. */
export function routeSentence(task: string, policy: AgentPolicy, workers: WorkerOut[], status: Pick<AgentStatus, "calibrations" | "spent_today_usd">): string {
  const chain = policy.routes[task] ?? [];
  const usable = chain.filter((n) => readiness(n, task, policy, workers, status).ready);
  if (usable.length === 0) return "Rien ne tournera : aucun moteur de cette route n'est prêt.";
  const names = usable.map((n) => short(policy.engines[n]));
  if (names.length === 1) return `${names[0]} seulement.`;
  return `${names[0]}, puis ${names.slice(1).join(", puis ")} si l'écran a changé.`;
}

export function short(e: EnginePolicy): string {
  return e.kind === "playbook" ? "Le script" : e.label.replace(/\s*\(.*\)\s*$/, "");
}

/** Every difference between the saved policy and the draft, in plain words, for the save bar. */
export function changes(saved: AgentPolicy, draft: AgentPolicy): string[] {
  const out: string[] = [];
  for (const name of ENGINE_ORDER) {
    const a = saved.engines[name];
    const b = draft.engines[name];
    if (!a || !b) continue;
    const label = short(b);
    if (a.enabled !== b.enabled) out.push(`${label} : ${b.enabled ? "activé" : "désactivé"}`);
    if (a.identifiable_data_allowed !== b.identifiable_data_allowed || a.identifiable_basis !== b.identifiable_basis)
      out.push(
        b.identifiable_data_allowed
          ? `${label} : peut voir des données identifiantes (${b.identifiable_basis ? lowerFirst(BASIS[b.identifiable_basis].label) : "sans justification"})`
          : `${label} : ne voit plus de données identifiantes`
      );
    if (a.input_usd_per_mtok !== b.input_usd_per_mtok || a.output_usd_per_mtok !== b.output_usd_per_mtok || a.usd_per_hour !== b.usd_per_hour)
      out.push(`${label} : prix modifié`);
  }
  for (const task of Object.keys(TASKS)) {
    const a = saved.routes[task] ?? [];
    const b = draft.routes[task] ?? [];
    if (JSON.stringify(a) !== JSON.stringify(b))
      out.push(`${TASKS[task].title} : ${b.map((n) => short(draft.engines[n])).join(" → ") || "aucun moteur"}`);
    if ((saved.task_budget_usd[task] ?? 0) !== (draft.task_budget_usd[task] ?? 0))
      out.push(`${TASKS[task].title} : budget ${usd(draft.task_budget_usd[task] ?? 0)} par tâche`);
  }
  if (saved.daily_budget_usd !== draft.daily_budget_usd) out.push(`Plafond du jour : ${usd(draft.daily_budget_usd)}`);
  if (saved.max_attempts !== draft.max_attempts) out.push(`Tentatives avant reprise humaine : ${draft.max_attempts}`);
  if (saved.sync_interval_minutes !== draft.sync_interval_minutes) out.push(`Relève sans connexion : toutes les ${draft.sync_interval_minutes} min`);
  return out;
}

function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}
