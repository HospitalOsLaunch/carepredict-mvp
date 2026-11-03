import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { GroupDashboard, Site, Vocabulary } from "../api/types";

export function useVocabulary() {
  return useQuery({
    queryKey: ["vocabulary"],
    queryFn: () => api<Vocabulary>("/vocabulary"),
    staleTime: Infinity
  });
}

export function useSites() {
  return useQuery({ queryKey: ["sites"], queryFn: () => api<Site[]>("/sites") });
}

export function useDashboard() {
  return useQuery({ queryKey: ["dashboard"], queryFn: () => api<GroupDashboard>("/dashboard") });
}

export function label(map: Record<string, string> | undefined, code: string | null | undefined): string {
  if (!code) return "—";
  return map?.[code] ?? code;
}

/** A unit of a site (SMR mention or MCO unit code), as the teams name it: never a raw code. */
export function unitLabel(
  vocab: { mentions?: Record<string, string>; unit_codes?: Record<string, string> } | undefined,
  code: string | null | undefined
): string {
  if (!code) return "—";
  const known = vocab?.mentions?.[code] ?? vocab?.unit_codes?.[code];
  if (known) return known;
  const words = code.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
