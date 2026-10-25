import { call } from "./client";
import type { LiveSnapshot, ShadowEpisode } from "./types";
export interface Hospital { id: string; name: string; unit_name: string; available: boolean; hospital_id?: string; unit_id?: string }
export interface HospitalView {
  schema_version: "HOSPITAL_WORKSPACE_1"; hospital_id: string; hospital_name: string;
  unit_id?: string; unit_name: string; run_id: string; revision: number; now: string; clock_rate: number;
  synthetic: true; snapshot: LiveSnapshot; episode: ShadowEpisode | null; can_decide: boolean;
  activity: { admissions: number; departures: number; arrivals: number };
  decisions: Array<{ request_id: string; plan_id: string; at: string; action: string;
    bed_id: string | null; patient_id: string | null; accepted: boolean; reason: string;
    actor: string; status: "accepted" | "refusal_recorded" | "executed" | "refused" | "failed";
    outcome_at: string | null }>;
}
export interface HospitalOverview {
  hospital_id: string; name: string; timezone: string; now: string;
  units: Array<{ id: string; name: string; capacity: number; occupied: number; waiting: number; available: boolean; observed_at: string }>;
}
export interface UnitHistory {
  from: string; until: string; samples: number; capacity: number;
  daily: Array<{ date: string; mean_occupied: number; samples: number }>;
  recent: Array<{ at: string; occupied: number; waiting: number; ready: number }>;
  model: { version: string; train_from: string; train_until: string; validation_from: string; validation_until: string;
    training_pairs: number; validation_pairs: number; mae_beds: number; persistence_mae_beds: number;
    selected: string; data_sha256: string };
  forecast: { origin: string; horizon_minutes: number; occupied: number };
}
export function viewKey(v: HospitalView) { return v.hospital_id === "H1" ? `H1/${v.unit_id}` : v.hospital_id; }
function path(id: string) {
  const [hospital, unit] = id.split("/");
  return `/product/hospitals/${encodeURIComponent(hospital!)}` + (unit ? `/units/${encodeURIComponent(unit)}` : "");
}
async function checked(request: Promise<HospitalView>, id: string) {
  const v = await request;
  if (v.schema_version !== "HOSPITAL_WORKSPACE_1" || viewKey(v) !== id || v.synthetic !== true)
    throw new Error("Incompatible hospital feed");
  return v;
}
export const virtualApi = {
  catalog: async () => {
    const c = await call<{ schema_version: string; hospitals: Array<Hospital & { units?: Array<{id: string; name: string; available: boolean}> }> }>("/product/hospitals");
    if (c.schema_version !== "HOSPITAL_WORKSPACE_1" || !c.hospitals.length) throw new Error("Incompatible catalog");
    return c.hospitals.flatMap(h => h.units ? h.units.map(u => ({ id: `${h.id}/${u.id}`, name: u.name,
      hospital_id: h.id, unit_id: u.id, unit_name: u.name, available: u.available })) : [h]);
  },
  read: (id: string) => checked(call<HospitalView>(`${path(id)}${id.includes("/") ? "" : "/unit"}`), id),
  decide: (v: HospitalView, accept: boolean, reason: string, requestId: string) => checked(call<HospitalView>(`${path(viewKey(v))}/decisions`, {
    method: "POST", body: JSON.stringify({ hospital_id: v.hospital_id, unit_id: v.unit_id, run_id: v.run_id,
      revision: v.revision, request_id: requestId, plan_id: v.episode?.assessment.plan?.plan_id,
      snapshot_fingerprint: v.snapshot.semantic_fingerprint, accept, reason }),
  }), viewKey(v)),
  overview: () => call<HospitalOverview>("/product/hospitals/H1/overview"),
  history: (id: string) => call<UnitHistory>(`${path(id)}/history`),
};
