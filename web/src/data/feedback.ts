// Shadow-mode opinion capture: "would you have done it?" — kept on this device only.
// The hybrid API exposes no endpoint for it yet (see web/README.md, "Suite côté API").
// It never approves, reserves or sends anything.

export type Verdict = "would_do" | "would_not";

export interface Opinion {
  plan_id: string;
  verdict: Verdict;
  reason: string | null;
  comment: string;
  recorded_at: string;
  state_at: string;
}

export const REASONS: { id: string; label: string }[] = [
  { id: "already_done", label: "Déjà fait" },
  { id: "information_missing", label: "Information manquante" },
  { id: "clinical_priority", label: "Autre priorité clinique" },
  { id: "resource_unavailable", label: "Ressource indisponible" },
  { id: "wrong_bed", label: "Lit inadapté" },
  { id: "other", label: "Autre raison" },
];

const KEY = "hospitalos.shadow-opinions.v1";

export function readOpinions(): Opinion[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Opinion[]) : [];
  } catch {
    return [];
  }
}

export function opinionFor(planId: string): Opinion | null {
  return readOpinions().find((o) => o.plan_id === planId) ?? null;
}

/** Returns false when the browser refuses storage; the UI then says it was not kept. */
export function saveOpinion(opinion: Opinion): boolean {
  try {
    const rest = readOpinions().filter((o) => o.plan_id !== opinion.plan_id);
    window.localStorage.setItem(KEY, JSON.stringify([...rest, opinion].slice(-500)));
    return true;
  } catch {
    return false;
  }
}
