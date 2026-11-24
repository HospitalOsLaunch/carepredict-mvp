import { request } from "../api/http";

export type Role = "admin" | "pilot";
export type AccountStatus = "invited" | "active" | "disabled";
export type Environment = "development" | "staging" | "production";

export interface Account {
  id: string;
  email: string;
  role: Role;
  status: AccountStatus;
  display_name: string;
  job_title: string;
  establishment: string;
  default_unit: string;
  analytics_consent: boolean | null;
  created_at: string;
  last_login_at: string | null;
}

export interface Me {
  user: Account;
  environment: Environment;
}

export interface PublicConfig {
  environment: Environment;
  release: string;
  analytics: { provider: "ga4"; measurement_id: string } | null;
}

export interface AuditEvent {
  id: number;
  at: string;
  action: string;
  actor_id: number | null;
  target_id: number | null;
  detail: Record<string, unknown>;
}

export interface ProfileChange {
  display_name?: string;
  job_title?: string;
  establishment?: string;
  default_unit?: string;
  analytics_consent?: boolean;
  clear_analytics_consent?: boolean;
}

export const authApi = {
  config: () => request<PublicConfig>("/api/config", { timeoutMs: 5000 }),
  me: () => request<Me>("/api/auth/me", { quiet401: true, timeoutMs: 5000 }),
  login: (email: string, password: string) =>
    request<Me>("/api/auth/login", { body: { email, password }, quiet401: true }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { body: {} }),
  invitation: (token: string) =>
    request<{ email: string; display_name: string }>(`/api/auth/invitation?token=${encodeURIComponent(token)}`),
  accept: (token: string, password: string, display_name: string) =>
    request<Me>("/api/auth/invitation/accept", { body: { token, password, display_name } }),
  forgot: (email: string) => request<{ detail: string }>("/api/auth/password/forgot", { body: { email } }),
  reset: (token: string, password: string) =>
    request<{ detail: string }>("/api/auth/password/reset", { body: { token, password } }),
};

export const settingsApi = {
  save: (change: ProfileChange) => request<Me>("/api/settings", { method: "PUT", body: change }),
  password: (current_password: string, new_password: string) =>
    request<Me>("/api/settings/password", { body: { current_password, new_password } }),
  revokeOthers: () => request<{ ok: boolean }>("/api/settings/sessions/revoke-others", { body: {} }),
};

export const adminApi = {
  users: () => request<{ users: Account[] }>("/api/admin/users"),
  invite: (email: string, role: Role, display_name: string) =>
    request<{ user: Account }>("/api/admin/users", { body: { email, role, display_name } }),
  resend: (id: string) => request<{ user: Account }>(`/api/admin/users/${encodeURIComponent(id)}/resend`, { body: {} }),
  update: (id: string, change: { role?: Role; status?: "active" | "disabled" }) =>
    request<{ user: Account }>(`/api/admin/users/${encodeURIComponent(id)}`, { method: "PATCH", body: change }),
  audit: () => request<{ events: AuditEvent[] }>("/api/admin/audit"),
};

export const journalApi = {
  get: () => request<{ revision: number; records: unknown[] }>("/api/journal"),
  put: (base_revision: number, records: unknown[]) =>
    request<{ revision: number }>("/api/journal", { method: "PUT", body: { base_revision, records } }),
};
