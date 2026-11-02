import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { AgentStatus, AgentTask } from "../api/types";
import type {
  ConnectionAction,
  ConnectionIn,
  ConnectionOut,
  ConnectionPatch,
  ConnectionRun,
  ConnectionStatus,
  WorkerOut
} from "../api/types_agent";

// TanStack Query pauses intervals while the tab is hidden (refetchIntervalInBackground is false).
const POLL_MS = 15_000;
const CONNECTIONS = ["agent", "connections"] as const;

export function useAgentStatus() {
  return useQuery({
    queryKey: ["agent", "status"],
    queryFn: () => api<AgentStatus>("/agent/status"),
    refetchInterval: POLL_MS
  });
}

export function useWorkers() {
  return useQuery({
    queryKey: ["agent", "workers"],
    queryFn: () => api<WorkerOut[]>("/agent/workers"),
    refetchInterval: POLL_MS
  });
}

export function useConnections() {
  return useQuery({
    queryKey: CONNECTIONS,
    queryFn: () => api<ConnectionOut[]>("/agent/connections"),
    refetchInterval: POLL_MS
  });
}

export function useConnectionRuns(id: number, enabled: boolean) {
  return useQuery({
    queryKey: ["agent", "connections", id, "runs"],
    queryFn: () => api<ConnectionRun[]>(`/agent/connections/${id}/runs?limit=20`),
    enabled
  });
}

function useInvalidateAgent() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: ["agent"] });
}

const OPTIMISTIC: Partial<Record<ConnectionAction, ConnectionStatus>> = {
  start: "active",
  pause: "en_pause",
  resume: "active"
};

/** Start / pause / resume / sync now, with the new state shown before the server answers. */
export function useConnectionAction() {
  const client = useQueryClient();
  const invalidate = useInvalidateAgent();
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: ConnectionAction }) =>
      api<unknown>(`/agent/connections/${id}/${action}`, { method: "POST" }),
    onMutate: async ({ id, action }) => {
      await client.cancelQueries({ queryKey: CONNECTIONS, exact: true });
      const previous = client.getQueryData<ConnectionOut[]>(CONNECTIONS);
      client.setQueryData<ConnectionOut[]>(CONNECTIONS, (list) =>
        list?.map((c) =>
          c.id !== id
            ? c
            : action === "sync"
              ? { ...c, pending_tasks: c.pending_tasks + 1 }
              : { ...c, status: OPTIMISTIC[action] ?? c.status }
        )
      );
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) client.setQueryData(CONNECTIONS, context.previous);
    },
    onSettled: invalidate
  });
}

export function useSaveConnection(id: number | null) {
  const invalidate = useInvalidateAgent();
  return useMutation({
    mutationFn: (body: ConnectionIn | ConnectionPatch) =>
      api<ConnectionOut>(id === null ? "/agent/connections" : `/agent/connections/${id}`, {
        method: id === null ? "POST" : "PATCH",
        json: body
      }),
    onSuccess: invalidate
  });
}

export function useArchiveConnection() {
  const invalidate = useInvalidateAgent();
  return useMutation({
    mutationFn: (id: number) => api<unknown>(`/agent/connections/${id}`, { method: "DELETE" }),
    onSuccess: invalidate
  });
}

export function useGroupPause() {
  const invalidate = useInvalidateAgent();
  return useMutation({
    mutationFn: (pause: boolean) => api<AgentStatus>(pause ? "/agent/pause" : "/agent/resume", { method: "POST" }),
    onSuccess: invalidate
  });
}

export function useTaskAction() {
  const invalidate = useInvalidateAgent();
  return useMutation({
    mutationFn: ({ id, what }: { id: number; what: "retry" | "manual" }) =>
      api<AgentTask>(`/agent/tasks/${id}/${what}`, { method: "POST" }),
    onSuccess: invalidate
  });
}

export const KIND_LABEL = {
  portail_orientation: "Portail d'orientation",
  gestion_lits: "Logiciel de gestion des lits"
} as const;

export const TASKS_BY_KIND = {
  portail_orientation: ["sync_inbox", "reply_portal"],
  gestion_lits: ["sync_movements"]
} as const;

export const TASK_LABEL: Record<string, string> = {
  sync_inbox: "Relever les demandes",
  reply_portal: "Reporter les réponses",
  sync_movements: "Relever les mouvements"
};

export const TASK_STATUS: Record<string, { text: string; tone: string }> = {
  pending: { text: "En file", tone: "bg-violet-soft text-violet-dark" },
  running: { text: "En cours", tone: "bg-violet text-white" },
  done: { text: "Faite", tone: "bg-lagoon-soft text-lagoon-dark" },
  manual: { text: "Faite à la main", tone: "bg-sky-deep text-ink-soft" },
  needs_human: { text: "À reprendre", tone: "bg-coral text-white" },
  failed: { text: "Échec", tone: "bg-coral-soft text-coral-dark" },
  cancelled: { text: "Annulée", tone: "bg-sky-deep text-ink-soft" }
};
