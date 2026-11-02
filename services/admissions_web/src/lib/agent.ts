import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useReducer, useRef } from "react";

import { api, apiBlob } from "../api/client";
import type { AgentStatus, AgentTask } from "../api/types";
import type {
  ConnectionAction,
  ConnectionIn,
  ConnectionOut,
  ConnectionPatch,
  ConnectionRun,
  ConnectionStatus,
  ReplayOut,
  ReplayStep,
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

/** Engine family shown to people: the exact engine name stays in the settings. */
export function engineLabel(engine: string | null | undefined): string {
  if (!engine) return "—";
  if (engine === "playbook") return "script";
  if (engine.startsWith("open_")) return "modèle ouvert";
  if (engine.startsWith("closed_")) return "Claude";
  return engine;
}

export const LIVE_POLL_MS = 1_000;

/** Appends the steps of a live poll to what is already known (by seq, without duplicates). */
export function mergeReplay(previous: ReplayOut | undefined, next: ReplayOut): ReplayOut {
  if (!previous) return next;
  const known = new Set(previous.steps.map((s) => s.seq));
  const steps = [...previous.steps, ...next.steps.filter((s) => !known.has(s.seq))].sort((a, b) => a.seq - b.seq);
  return { ...next, steps };
}

/** The steps of a task; while it runs, asks every second for the steps after the last one. */
export function useReplay(taskId: number) {
  const client = useQueryClient();
  const key = ["agent", "replay", taskId];
  return useQuery({
    queryKey: key,
    queryFn: async () => {
      const previous = client.getQueryData<ReplayOut>(key);
      const last = previous?.steps.at(-1)?.seq;
      const query = last === undefined ? "" : `?after_seq=${last}`;
      return mergeReplay(previous, await api<ReplayOut>(`/agent/tasks/${taskId}/replay${query}`));
    },
    refetchInterval: (query) => (query.state.data?.live ? LIVE_POLL_MS : false),
    // 403 (direction) and 404 (purged, other group) will not change on retry.
    retry: (count, error) => ((error as { status?: number }).status ?? 500) >= 500 && count < 2
  });
}

export interface FrameState {
  url?: string;
  failed: boolean;
}

/**
 * Frames are fetched with the bearer token as blobs and shown through object URLs, cached by
 * step id: the current one and the next `ahead` frames, so playback does not wait. Every URL is
 * revoked on unmount.
 */
export function useFrames(steps: ReplayStep[], index: number, ahead = 3): (stepId: number) => FrameState {
  // shortcut: the cache keeps every frame of the task (≤ 512 Ko each); evict if tasks grow to hundreds of steps.
  const urls = useRef(new Map<number, string>());
  const failed = useRef(new Set<number>());
  const pending = useRef(new Set<number>());
  const mounted = useRef(true);
  const [, bump] = useReducer((n: number) => n + 1, 0);

  useEffect(() => {
    mounted.current = true;
    const cache = urls.current;
    return () => {
      mounted.current = false;
      for (const url of cache.values()) URL.revokeObjectURL(url);
      cache.clear();
    };
  }, []);

  const wanted = steps
    .slice(Math.max(0, index))
    .filter((s) => s.has_frame)
    .slice(0, ahead + 1)
    .map((s) => s.id);
  const wantedKey = wanted.join(",");

  useEffect(() => {
    for (const id of wanted) {
      if (urls.current.has(id) || failed.current.has(id) || pending.current.has(id)) continue;
      pending.current.add(id);
      apiBlob(`/agent/steps/${id}/frame`)
        .then((blob) => {
          if (mounted.current) urls.current.set(id, URL.createObjectURL(blob));
        })
        .catch(() => failed.current.add(id))
        .finally(() => {
          pending.current.delete(id);
          if (mounted.current) bump();
        });
    }
  }, [wantedKey]); // wantedKey stands for wanted (a new array every render)

  return (stepId) => ({ url: urls.current.get(stepId), failed: failed.current.has(stepId) });
}
