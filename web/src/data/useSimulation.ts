import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { type DemoView, type Operation, simulatorApi } from "../api/simulator";
import { fromLive, unitSummary } from "../domain/view";
import type { Store } from "./useAssessment";

export interface Simulation {
  view: DemoView | null;
  store: Store;
  control: (operation: Operation, seconds?: number) => void;
  decide: (accept: boolean) => void;
  refresh: () => void;
}

export function useSimulation(enabled: boolean): Simulation {
  const [view, setView] = useState<DemoView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const pending = useRef<"read" | "mutation" | null>(null);
  const needsRefresh = useRef(false);
  const current = useRef<DemoView | null>(null);

  const run = useCallback(async (operation: () => Promise<DemoView>, mutation = false) => {
    if (!enabled || pending.current === "mutation" || (!mutation && pending.current)) return;
    // A user decision supersedes an in-flight poll; its late result is ignored.
    pending.current = mutation ? "mutation" : "read";
    const token = ++generation.current;
    if (mutation) setBusy(true);
    try {
      const next = await operation();
      if (token !== generation.current) return;
      current.current = next;
      setView(next);
      setError(null);
      needsRefresh.current = false;
    } catch (e) {
      if (token !== generation.current) return;
      needsRefresh.current = true;
      setError(e instanceof ApiError && e.status === 409
        ? "Le scénario ou la proposition a changé. Actualisez puis réévaluez avant de décider."
        : "Simulateur injoignable ou incompatible. Aucune donnée précalculée ne le remplace. Actualisez pour vérifier le résultat.");
    } finally {
      if (token === generation.current) {
        pending.current = null;
        setBusy(false);
      }
    }
  }, [enabled]);

  const refresh = useCallback(() => { void run(simulatorApi.read); }, [run]);
  useEffect(() => {
    if (!enabled) return;
    refresh();
    const timer = window.setInterval(() => { if (!needsRefresh.current) refresh(); }, 1000);
    return () => {
      window.clearInterval(timer);
      generation.current += 1;
      pending.current = null;
    };
  }, [enabled, refresh]);

  const control = useCallback((operation: Operation, seconds?: number) => {
    const v = current.current;
    if (v) void run(() => simulatorApi.control(v, operation, seconds), true);
  }, [run]);
  const decide = useCallback((accept: boolean) => {
    const v = current.current;
    if (v && !error) void run(() => simulatorApi.decide(v, accept), true);
  }, [run, error]);
  const evaluate = useCallback(() => { void run(simulatorApi.evaluate, true); }, [run]);
  const episode = view?.episode;
  const assessment = view ? fromLive(
    view.snapshot, episode?.assessment.plan ?? null, view.snapshot.issues,
    "api-live", episode?.episode_id ?? null, episode?.assessment.expires_at ?? null,
  ) : null;
  const unitId = "court-sejour-geriatrique";
  const unitName = view?.unit_name ?? "Court séjour gériatrique";
  const store: Store = {
    connection: "simulation", units: [{ id: unitId, name: unitName, situations: [] }],
    summaries: [unitSummary(unitId, unitName, assessment)], unitId, unitName,
    setUnit: () => undefined, situations: [], situationId: "simulation", setSituation: () => undefined,
    assessment, awaitingEvaluation: !episode, busy, error, evaluate,
    quality: null, shadowSummary: null, loadedAt: 0,
  };
  return { view, store, control, decide, refresh };
}
