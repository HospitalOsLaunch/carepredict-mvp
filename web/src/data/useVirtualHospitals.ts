import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { virtualApi, type Hospital, type HospitalView, type HospitalOverview, type UnitHistory, viewKey } from "../api/virtual";
import { fromLive, unitSummary } from "../domain/view";
import { useOperations, type OperationsWorkspace } from "./useOperations";
import type { Store } from "./useAssessment";
export interface Workspace {
  operations: OperationsWorkspace;
  overview: HospitalOverview | null; history: UnitHistory | null; historyError: string | null;
  view: HospitalView | null; hospitals: Hospital[]; store: Store;
  decide: (accept: boolean, reason?: string) => void;
}
export function useVirtualHospitals(enabled: boolean): Workspace {
  const [overview, setOverview] = useState<HospitalOverview | null>(null);
  const [history, setHistory] = useState<UnitHistory | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [hospitals, setHospitals] = useState<Hospital[]>([]);
  const [id, setId] = useState("");
  const [view, setView] = useState<HospitalView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const pending = useRef<"read" | "mutation" | null>(null);
  const current = useRef<HospitalView | null>(null);
  const run = useCallback(async (operation: () => Promise<HospitalView>, mutation = false) => {
    if (!enabled || !id || pending.current === "mutation" || (!mutation && pending.current)) return;
    const token = ++generation.current;
    pending.current = mutation ? "mutation" : "read";
    if (mutation) setBusy(true);
    try {
      const next = await operation();
      if (token !== generation.current || viewKey(next) !== id) return;
      current.current = next; setView(next); setError(null);
    } catch (e) {
      if (token !== generation.current) return;
      setError(e instanceof ApiError && e.status === 409
        ? "La proposition a changé. La vue va être actualisée avant toute nouvelle décision."
        : "Connexion à l’établissement interrompue. Les données affichées peuvent être anciennes. Le journal permettra de vérifier la réception d’une décision.");
    } finally {
      if (token === generation.current) { pending.current = null; setBusy(false); }
    }
  }, [enabled, id]);
  const refresh = useCallback(() => { void run(() => virtualApi.read(id)); }, [run, id]);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    const load = async () => {
      try { const catalog = await virtualApi.catalog(); if (active) { setHospitals(catalog); setId(old => old || catalog[0]!.id); } }
      catch { if (active) setError("Impossible de joindre les établissements. Nouvelle tentative automatique."); }
    };
    void load(); const timer = window.setInterval(() => { void load(); }, 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [enabled]);
  useEffect(() => {
    if (!enabled || !id) return;
    refresh(); const timer = window.setInterval(refresh, 1500);
    return () => { window.clearInterval(timer); ++generation.current; pending.current = null; };
  }, [enabled, id, refresh]);
  useEffect(() => {
    if (!enabled || !id.includes("/")) return;
    let active = true;
    setHistory(null); setHistoryError(null);
    const load = async () => {
      try {
        const [o, h] = await Promise.all([virtualApi.overview(), virtualApi.history(id)]);
        if (active) { setOverview(o); setHistory(h); setHistoryError(null); }
      } catch { if (active) setHistoryError("Historique et vue hôpital temporairement indisponibles."); }
    };
    void load(); const timer = window.setInterval(() => { void load(); }, 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [enabled, id]);
  const select = useCallback((next: string) => {
    if (!hospitals.some(h => h.id === next) || next === id) return;
    ++generation.current; pending.current = null; current.current = null;
    setView(null); setHistory(null); setError(null); setBusy(false); setId(next);
  }, [hospitals, id]);
  const operations = useOperations(enabled && id.startsWith("H1/"), refresh);
  const decide = useCallback((accept: boolean, reason = "") => {
    const v = current.current;
    if (v && viewKey(v) === id && v.can_decide && !error && v.hospital_id === "H1") {
      operations.submit({kind: "plan_decision", unit_id: v.unit_id!, plan_id: v.episode?.assessment.plan?.plan_id,
        accept_plan: accept, reason});
      return;
    }
    if (v && viewKey(v) === id && v.can_decide && !error)
      void run(() => virtualApi.decide(v, accept, reason, crypto.randomUUID()), true);
  }, [run, error, id, operations]);
  const episode = view?.episode;
  const assessment = view ? fromLive(view.snapshot, episode?.assessment.plan ?? null,
    view.snapshot.issues, "api-live", episode?.episode_id ?? null, episode?.assessment.expires_at ?? null) : null;
  const name = hospitals.find(h => h.id === id)?.name ?? "Établissements";
  const store: Store = { connection: "virtual", units: hospitals.map(h => ({ id: h.id, name: h.name, situations: [] })),
    summaries: [unitSummary(id, name, assessment)], unitId: id, unitName: view?.hospital_id === "H1" ? `${view.hospital_name} · ${view.unit_name}` : `${name} · ${view?.unit_name ?? "Gériatrie"}`,
    setUnit: select, situations: [], situationId: "", setSituation: () => undefined,
    assessment, awaitingEvaluation: !episode, busy, error, evaluate: refresh,
    quality: null, shadowSummary: null, loadedAt: 0 };
  return { view, hospitals, store, decide, overview, history, historyError, operations };
}
