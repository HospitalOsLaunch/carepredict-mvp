import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { AdmissionRequest, Forecast, RequestDetail } from "../api/types";

export type Scope = "a_traiter" | "ouvertes" | "fermees";

export function useRequests(params: { scope: Scope; site_id?: string; mention?: string; q?: string }) {
  const search = new URLSearchParams({ scope: params.scope });
  if (params.site_id) search.set("site_id", params.site_id);
  if (params.mention) search.set("mention", params.mention);
  if (params.q) search.set("q", params.q);
  return useQuery({
    queryKey: ["requests", params],
    queryFn: () => api<AdmissionRequest[]>(`/requests?${search.toString()}`),
    refetchInterval: 60_000
  });
}

export function useRequest(id: number | null) {
  return useQuery({
    queryKey: ["request", id],
    queryFn: () => api<RequestDetail>(`/requests/${id}`),
    enabled: id !== null
  });
}

export function useForecast() {
  return useQuery({ queryKey: ["forecast"], queryFn: () => api<Forecast>("/forecast") });
}

/** Runs a workflow action and refreshes everything a bed promise can change. */
export function useRequestAction(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ action, body }: { action: string; body?: unknown }) =>
      api<RequestDetail>(`/requests/${id}/${action}`, { method: "POST", json: body ?? {} }),
    onSuccess: (detail) => {
      queryClient.setQueryData(["request", id], detail);
      void queryClient.invalidateQueries({ queryKey: ["requests"] });
      void queryClient.invalidateQueries({ queryKey: ["forecast"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["stays"] });
    }
  });
}
