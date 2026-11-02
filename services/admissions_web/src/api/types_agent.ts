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
}

export type ConnectionAction = "start" | "pause" | "resume" | "sync";
