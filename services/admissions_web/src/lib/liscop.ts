import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  BedAction,
  BedBoard,
  BoardingSeries,
  EdCensus,
  EdSnapshot,
  TensionDeclaration,
  TensionStatus
} from "../api/types_liscop";

const REFRESH_MS = 60_000;

function query(siteId: number | null): string {
  return siteId === null ? "" : `?site_id=${siteId}`;
}

export function useBedBoard() {
  return useQuery({ queryKey: ["beds"], queryFn: () => api<BedBoard>("/beds"), refetchInterval: REFRESH_MS });
}

export function useBedAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action, reason, note }: { id: number; action: BedAction; reason?: string; note?: string }) =>
      api(`/beds/${id}`, {
        method: "PATCH",
        json: { action, ...(reason ? { reason } : {}), ...(note ? { note } : {}) }
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["beds"] });
      void client.invalidateQueries({ queryKey: ["tension-status"] });
    }
  });
}

export function useEdCensus(siteId: number | null) {
  return useQuery({
    queryKey: ["ed-census", siteId],
    queryFn: () => api<EdCensus>(`/ed/census${query(siteId)}`),
    refetchInterval: REFRESH_MS
  });
}

export function useBoarding(siteId: number | null, days = 90) {
  const params = new URLSearchParams({ days: String(days) });
  if (siteId !== null) params.set("site_id", String(siteId));
  return useQuery({
    queryKey: ["ed-boarding", siteId, days],
    queryFn: () => api<BoardingSeries>(`/ed/boarding?${params.toString()}`)
  });
}

export function useSnapshots(siteId: number | null) {
  return useQuery({
    queryKey: ["ed-snapshots", siteId],
    queryFn: () => api<EdSnapshot[]>(`/ed/snapshots${query(siteId)}`)
  });
}

export function useTensionStatus(siteId: number | null) {
  return useQuery({
    queryKey: ["tension-status", siteId],
    queryFn: () => api<TensionStatus>(`/tension/status${query(siteId)}`),
    refetchInterval: REFRESH_MS
  });
}

export function useDeclarations() {
  return useQuery({
    queryKey: ["tension-declarations"],
    queryFn: () => api<TensionDeclaration[]>("/tension/declarations")
  });
}

/** Any write on the emergency / tension side refreshes every view that depends on it. */
export function useEdWrite<T>(path: string, method: "POST" | "PATCH" = "POST") {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ body, id }: { body: T; id?: number }) =>
      api(id === undefined ? path : `${path}/${id}`, { method, json: body }),
    onSuccess: () => {
      for (const key of ["ed-census", "ed-boarding", "ed-snapshots", "tension-status", "tension-declarations"]) {
        void client.invalidateQueries({ queryKey: [key] });
      }
    }
  });
}
