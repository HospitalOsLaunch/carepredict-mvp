import { call } from "./client";
import type { LiveSnapshot, ShadowEpisode } from "./types";
export interface Hospital { id: string; name: string; unit_name: string; available: boolean }
export interface HospitalView {
  schema_version: "HOSPITAL_WORKSPACE_1"; hospital_id: string; hospital_name: string;
  unit_name: string; run_id: string; revision: number; now: string; clock_rate: number;
  synthetic: true; snapshot: LiveSnapshot; episode: ShadowEpisode | null; can_decide: boolean;
  activity: { admissions: number; departures: number; arrivals: number };
  decisions: Array<{ request_id: string; plan_id: string; at: string; action: string;
    bed_id: string | null; patient_id: string | null; accepted: boolean; reason: string;
    actor: string; status: "accepted" | "refusal_recorded" | "executed" | "refused" | "failed";
    outcome_at: string | null }>;
}
function path(id: string) { return `/product/hospitals/${encodeURIComponent(id)}`; }
async function checked(request: Promise<HospitalView>, id: string) {
  const v = await request;
  if (v.schema_version !== "HOSPITAL_WORKSPACE_1" || v.hospital_id !== id || v.synthetic !== true)
    throw new Error("Incompatible hospital feed");
  return v;
}
export const virtualApi = {
  catalog: async () => {
    const c = await call<{ schema_version: string; hospitals: Hospital[] }>("/product/hospitals");
    if (c.schema_version !== "HOSPITAL_WORKSPACE_1" || !c.hospitals.length) throw new Error("Incompatible catalog");
    return c.hospitals;
  },
  read: (id: string) => checked(call<HospitalView>(`${path(id)}/unit`), id),
  decide: (v: HospitalView, accept: boolean, reason: string, requestId: string) => checked(call<HospitalView>(`${path(v.hospital_id)}/decisions`, {
    method: "POST", body: JSON.stringify({ hospital_id: v.hospital_id, run_id: v.run_id,
      revision: v.revision, request_id: requestId, plan_id: v.episode?.assessment.plan?.plan_id,
      snapshot_fingerprint: v.snapshot.semantic_fingerprint, accept, reason }),
  }), v.hospital_id),
};
