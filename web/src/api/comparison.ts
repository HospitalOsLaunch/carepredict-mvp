import { ApiError, call } from "./client";
import type { CommandReceipt, DemoView } from "./simulator";

export interface ComparisonConfig {
  seed: number;
  horizon_minutes: number;
  policy: "accept" | "refuse" | "disabled";
}

export interface ComparisonEpisode {
  evaluation: NonNullable<DemoView["evaluation"]>;
  installed_during_episode: number;
  solicitation_seconds_requested: number;
  commands: CommandReceipt[];
  decisions: { second: number; decision: string; action: string | null; request_id: string | null }[];
  truth_journal: { second: number; kind: string; patient: string | null; bed: string | null }[];
}

export interface ComparisonResult {
  schema_version: "PAIRED_DEMO_1";
  comparison_id: string;
  scope: "fictional_scenario_only_no_effectiveness_claim";
  manifest: {
    config: ComparisonConfig;
    scenario_version: string;
    starts_at: string;
    ends_at: string;
    source_sha256: Record<string, string>;
    runtime_versions: Record<string, string>;
  };
  a0: ComparisonEpisode;
  a1: ComparisonEpisode;
  waiting_patient_minutes_saved: number;
  waiting_patient_hours_saved: number;
  physical_trajectories_identical: boolean;
}

class ComparisonContractError extends Error {}

export function comparisonError(error: unknown): string {
  let message: string;
  if (error instanceof ApiError) {
    if (error.detail === "comparison_environment_changed_restart_required") {
      message = "Le code ou les dépendances ont changé. Arrêtez la démo puis relancez demo.py avant de comparer.";
    } else if (error.status === 404 || error.status === 405) {
      message = `Ce serveur ne propose pas le comparateur (HTTP ${error.status}). Il peut s'agir d'un ancien backend resté lancé après la mise à jour du cockpit. Arrêtez la démo avec Ctrl+C puis relancez python3.11 demo.py.`;
    } else if (error.status === 429) {
      message = "Une comparaison est déjà en cours. Réessayez une fois son calcul terminé.";
    } else if (error.status === 500) {
      message = "Le moteur a rencontré une erreur interne (HTTP 500). Consultez le terminal de la démo : le détail se trouve après POST /demo/compare.";
    } else if ([502, 503, 504].includes(error.status)) {
      message = `Le moteur ou sa passerelle est indisponible (HTTP ${error.status}). Vérifiez le terminal de la démo, puis redémarrez-la si nécessaire.`;
    } else if (error.status === 422) {
      message = "Les paramètres ont été refusés (HTTP 422). Utilisez une graine entière entre 0 et 2147483647 et une durée proposée dans la liste.";
    } else {
      message = `La requête de comparaison a été refusée (HTTP ${error.status}). Consultez le terminal de la démo.`;
    }
  } else if (typeof error === "object" && error !== null && "name" in error && error.name === "AbortError") {
    message = "Le délai de 120 secondes est dépassé. Le serveur peut encore terminer ce calcul. Attendez, puis essayez une durée simulée d'une heure.";
  } else if (error instanceof ComparisonContractError || error instanceof SyntaxError) {
    message = "La réponse du serveur est incompatible avec ce cockpit. Mettez la branche à jour, puis arrêtez et relancez la démo.";
  } else {
    message = "Le comparateur n'a pas reçu de réponse exploitable. Vérifiez que la démo tourne dans son terminal et que le serveur est joignable.";
  }
  return `${message} Aucun résultat de remplacement n'est affiché.`;
}

export async function compareEpisodes(config: ComparisonConfig): Promise<ComparisonResult> {
  const result = await call<ComparisonResult>("/demo/compare", {
    method: "POST", body: JSON.stringify(config),
  }, 120000);
  if (result?.schema_version !== "PAIRED_DEMO_1" ||
      result.scope !== "fictional_scenario_only_no_effectiveness_claim" ||
      result.manifest?.config?.seed !== config.seed ||
      result.manifest.config.horizon_minutes !== config.horizon_minutes ||
      result.manifest.config.policy !== config.policy) {
    throw new ComparisonContractError("Unsupported or mismatched comparison");
  }
  return result;
}

export function downloadComparison(result: ComparisonResult) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `hospitalos-comparaison-${result.comparison_id.slice(0, 12)}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
