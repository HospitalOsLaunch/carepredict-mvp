import { call } from "./client";
export interface Staff {
  id: string;
  name: string;
  role: "bed_manager" | "cadre" | "service";
  unit_id: string;
}
export interface PlacementOption {
  unit_id: string;
  bed_id: string;
  eligible: boolean;
  reasons: string[];
}
export interface PlacementPatient {
  id: string;
  unit_id: string;
  waiting_since: string;
  oxygen: boolean;
  isolation: boolean;
  programmed: boolean;
  options: PlacementOption[];
}
export interface WorkTask {
  id: string;
  kind: string;
  unit_id: string;
  target_unit: string | null;
  patient_id: string | null;
  bed_id: string | null;
  owner_id: string;
  requested_by: string;
  created_at: string;
  due_at: string;
  status: string;
  overdue: boolean;
  reminders: number;
  events: Array<{ at: string; actor: string; status: string; note: string }>;
}
export interface Workplace {
  schema_version: "WORKPLACE_1";
  hospital_id: "H1";
  now: string;
  revision: number;
  tokens: Record<string, string>;
  staff: Staff[];
  patients: PlacementPatient[];
  discharges: Array<{
    id: string;
    unit_id: string;
    phase: string;
    documents_ready: boolean;
    transport_required: boolean;
    transport_ready: boolean;
    downstream_required: boolean;
    downstream_ready: boolean;
    observed_at: string;
  }>;
  admissions: Array<{
    id: string;
    unit_id: string;
    at: string;
    oxygen: boolean;
    isolation: boolean;
    protected_bed: string | null;
  }>;
  constraints: Array<{
    unit_id: string;
    capacity: number;
    physical_beds: number;
    reason: string;
    until: string | null;
    closed_beds: Array<{ bed_id: string; until: string; reason: string }>;
    holds: Array<{ bed_id: string; patient_id: string }>;
  }>;
  tasks: WorkTask[];
  events: Array<{
    id: string;
    at: string;
    actor_id: string;
    kind: string;
    unit_id: string;
    reason: string;
    capacity: number | null;
    until: string | null;
    bed_id: string | null;
    patient_id: string | null;
  }>;
  forecasts: Array<{
    unit_id: string;
    capacity: number;
    planned_next_shift: number;
    discharges_to_prepare: number;
    forecasts: Array<{
      horizon_hours: number;
      at: string;
      origin: string;
      occupied: number;
      lower: number;
      upper: number;
      interval_label: string;
    }>;
  }>;
}
export interface WorkCommand {
  kind:
    | "place"
    | "accept"
    | "reject"
    | "cancel"
    | "remind"
    | "assign"
    | "capacity"
    | "close_bed"
    | "reopen_bed"
    | "protect"
    | "release_hold"
    | "documents"
    | "transport"
    | "downstream"
    | "cleaning"
    | "plan_decision";
  unit_id: string;
  patient_id?: string;
  target_unit?: string;
  bed_id?: string;
  task_id?: string;
  owner_id?: string;
  capacity?: number;
  until?: string;
  reason?: string;
  plan_id?: string;
  accept_plan?: boolean;
}
export type SubmittedCommand = WorkCommand & {
  request_id: string;
  revision: number;
  actor_id: string;
  tokens: Record<string, string>;
};
function checked(v: Workplace): Workplace {
  if (
    v.schema_version !== "WORKPLACE_1" ||
    v.hospital_id !== "H1" ||
    !Array.isArray(v.tasks)
  )
    throw new Error("Incompatible workspace");
  return v;
}
export const operationsApi = {
  read: async () =>
    checked(await call<Workplace>("/product/hospitals/H1/workspace")),
  submit: async (body: SubmittedCommand) =>
    checked(
      await call<Workplace>("/product/hospitals/H1/operations", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    ),
};
