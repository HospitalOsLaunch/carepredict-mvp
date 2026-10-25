import { call } from "./client";
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

export async function compareEpisodes(config: ComparisonConfig): Promise<ComparisonResult> {
  const result = await call<ComparisonResult>("/demo/compare", {
    method: "POST", body: JSON.stringify(config),
  }, 120000);
  if (result.schema_version !== "PAIRED_DEMO_1" ||
      result.scope !== "fictional_scenario_only_no_effectiveness_claim" ||
      result.manifest.config.seed !== config.seed ||
      result.manifest.config.horizon_minutes !== config.horizon_minutes ||
      result.manifest.config.policy !== config.policy) {
    throw new Error("Unsupported or mismatched comparison");
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
