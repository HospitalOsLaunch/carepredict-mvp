// Computer use: agent workers and connections (docs/agent/CONNEXIONS_SPEC.md, « Contrat d'API »).
// Field names mirror the API exactly.

export type ConnectionKind = "portail_orientation" | "gestion_lits";
export type ConnectionStatus = "arretee" | "active" | "en_pause";
export type ConnectionTask = "sync_inbox" | "reply_portal" | "sync_movements";

export interface WorkerPlaybook {
  name: string;
  label: string;
  kind: ConnectionKind;
  tasks: ConnectionTask[];
}

export interface WorkerOut {
  agent_id: string;
  site_id: number | null;
  online: boolean;
  last_heartbeat_at: string | null;
  version: string | null;
  engines: Array<{ name: string; configured: boolean; detail: string | null }>;
  playbooks: WorkerPlaybook[];
}

export interface ConnectionOut {
  id: number;
  name: string;
  kind: ConnectionKind;
  site_id: number | null;
  site_name: string | null;
  url: string;
  allowed_hosts: string[];
  username: string | null;
  secret_set: boolean;
  secret_updated_at: string | null;
  playbook: string;
  tasks: ConnectionTask[];
  source_system: string | null;
  interval_minutes: number;
  /** "HH:MM", null = from midnight. */
  active_from: string | null;
  /** "HH:MM", null = until midnight. */
  active_to: string | null;
  /** ISO weekdays, 1 = Monday … 7 = Sunday; null = every day. */
  days: number[] | null;
  agent_id: string | null;
  status: ConnectionStatus;
  last_run_at: string | null;
  next_run_at: string | null;
  last_outcome: string | null;
  last_error: string | null;
  pending_tasks: number;
  needs_human: number;
  can_control: boolean;
  can_edit: boolean;
  /** The task the agent is running for this connection right now, to watch live. */
  running_task_id: number | null;
}

export interface ConnectionIn {
  name: string;
  kind: ConnectionKind;
  site_id?: number | null;
  url: string;
  allowed_hosts?: string[];
  username?: string | null;
  /** Write-only: sent only when the administrator typed one. */
  secret?: string;
  playbook: string;
  tasks: ConnectionTask[];
  source_system?: string | null;
  interval_minutes: number;
  active_from?: string | null;
  active_to?: string | null;
  days?: number[] | null;
  agent_id?: string | null;
}

export type ConnectionPatch = Partial<Omit<ConnectionIn, "kind">> & { kind?: ConnectionKind; clear_secret?: true };

/** One run of a connection: an agent task, without any value read on screen. */
export interface ConnectionRun {
  id: number;
  kind: string;
  status: string;
  attempts: number;
  engine_used: string | null;
  cost_usd: number;
  error: string | null;
  request_id: number | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  /** Steps were recorded for the player (kept ADM_AGENT_REPLAY_DAYS days). */
  has_replay: boolean;
  steps_count: number;
}

export type ConnectionAction = "start" | "pause" | "resume" | "sync";

// Player (docs/agent/PLAYER_SPEC.md, « Contrat d'API »): what the agent did, step by step.

export type StepKind =
  | "login"
  | "navigate"
  | "click"
  | "fill"
  | "select"
  | "read"
  | "wait"
  | "scroll"
  | "key"
  | "verify"
  | "model_action"
  | "info"
  | "error";
export type StepOutcome = "ok" | "fail" | "info";
/** Why a zone was covered on the worker before the capture. */
export type MaskReason = "identite" | "secret" | "autre";

/** In viewport pixels (the page as the agent saw it), not frame pixels. */
export interface StepRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface StepMask extends StepRect {
  reason: MaskReason;
}

/** What a reading step sent to HospitalOS: counts and field names, never values. */
export interface StepTransmitted {
  count: number;
  fields: string[];
  /** HospitalOS's answer, on the step that sends; null on a reading step (sent later). */
  applied: number | null;
  duplicates: number | null;
  rejected: number | null;
}

export interface ReplayStep {
  id: number;
  seq: number;
  at: string;
  engine: string;
  kind: StepKind;
  label: string;
  target: string | null;
  pointer: { x: number; y: number } | null;
  box: StepRect | null;
  outcome: StepOutcome;
  duration_ms: number | null;
  viewport: { w: number; h: number } | null;
  masks: StepMask[];
  transmitted: StepTransmitted | null;
  has_frame: boolean;
}

export interface ReplayTask {
  id: number;
  kind: string;
  status: string;
  engine_used: string | null;
  created_at: string;
  finished_at: string | null;
  connection_id: number | null;
  connection_name: string | null;
  site_name: string | null;
}

export interface ReplayOut {
  task: ReplayTask;
  /** The task is still running: poll with after_seq for the next steps. */
  live: boolean;
  retention_until: string | null;
  steps: ReplayStep[];
}
