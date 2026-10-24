import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type { LiveSnapshot, Plan, ShadowSummary, SourceReceipt } from "../api/types";
import { type Assessment, type UnitSummary, fromLive, unitSummary } from "../domain/view";
import { type FixtureBundle, type ScenarioFixture, loadFixtures } from "./fixtures";

/**
 * Where the cockpit reads from:
 * - "api-live": local FastAPI with a shadow LiveStore (GET /hybrid/live, POST /hybrid/shadow)
 * - "api-plan": local FastAPI without live store; demonstration requests sent to POST /hybrid/plan
 * - "fixture":  no API reachable; precomputed outputs of the same planner
 */
export type Connection = "probing" | "api-live" | "api-plan" | "fixture";

export interface Option {
  id: string;
  label: string;
}

export interface UnitOption {
  id: string;
  name: string;
  situations: Option[];
}

export interface Store {
  connection: Connection;
  units: UnitOption[];
  summaries: UnitSummary[];
  unitId: string;
  unitName: string;
  setUnit: (id: string) => void;
  situations: Option[];
  situationId: string;
  setSituation: (id: string) => void;
  assessment: Assessment | null;
  /** Live mode: snapshot is known but no evaluation has been recorded yet. */
  awaitingEvaluation: boolean;
  busy: boolean;
  error: string | null;
  evaluate: () => void;
  quality: SourceReceipt | null;
  shadowSummary: ShadowSummary | null;
  loadedAt: number;
}

const LIVE_UNIT = "medecine-polyvalente";
const LIVE_SITUATIONS: Option[] = [
  { id: "live", label: "Unité en observation" },
  { id: "live-stale", label: "Confirmations périmées" },
];

function fromScenario(s: ScenarioFixture, origin: Assessment["origin"], plan: Plan = s.plan): Assessment {
  return {
    origin,
    scenarioId: s.id,
    scenarioLabel: s.label,
    state: s.state,
    plan,
    gateReasons: plan.decision === "abstain" ? plan.reasons : [],
    events: s.request.events,
    resources: null,
    receivedAtBySource: null,
    trace: origin === "fixture" ? s.trace : null,
    episodeId: null,
    factBudgetMinutes: s.request.max_age_minutes,
    expiresAt: plan.expires_at,
  };
}

function fixtureAssessment(bundle: FixtureBundle, id: string): Assessment {
  if (id === "live" || id === "live-stale") {
    const episode = id === "live" ? bundle.live.episode : bundle.live.stale_episode;
    const a = episode.assessment;
    return fromLive(a.snapshot, a.plan, a.gate_reasons, "fixture", episode.episode_id, a.expires_at);
  }
  const s = bundle.scenarios.find((x) => x.id === id) ?? bundle.scenarios[0]!;
  return fromScenario(s, "fixture");
}

function readError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return `L'unité ne peut pas être évaluée : ${error.detail}`;
    if (error.status === 422) return `Requête refusée par le contrat : ${error.detail}`;
    return `Le service local a répondu ${error.status}.`;
  }
  if (error instanceof DOMException && error.name === "AbortError") {
    return "Le service local ne répond pas (délai dépassé).";
  }
  return "Le service local est injoignable.";
}

function fromUrl(key: string): string | null {
  try {
    return new URLSearchParams(window.location.search).get(key);
  } catch {
    return null;
  }
}

function writeUrl(key: string, value: string): void {
  try {
    const url = new URL(window.location.href);
    url.searchParams.set(key, value);
    window.history.replaceState(null, "", url);
  } catch {
    /* sandboxed frames may refuse URL changes; the selection still applies */
  }
}

export function useAssessment(): Store {
  const [connection, setConnection] = useState<Connection>("probing");
  const [bundle, setBundle] = useState<FixtureBundle | null>(null);
  const [scenarioId, setScenarioId] = useState(
    () => fromUrl("situation") ?? fromUrl("scenario") ?? "nominal",
  );
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [snapshot, setSnapshot] = useState<LiveSnapshot | null>(null);
  const [apiPlans, setApiPlans] = useState<Record<string, Plan>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadedAt, setLoadedAt] = useState(() => Date.now());
  const [refresh, setRefresh] = useState(0);
  const lastByUnit = useRef<Record<string, string>>({});
  const request = useRef(0);

  // Probe once: live store → plan API → bundled fixtures.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const fixtures = await loadFixtures();
      if (cancelled) return;
      setBundle(fixtures);
      const unit = fromUrl("unit");
      if (unit && !fromUrl("situation") && !fromUrl("scenario")) {
        const first = fixtures.scenarios.find((s) => s.unit === unit);
        if (first) setScenarioId(first.id);
      }
      if (__DEMO_ONLY__) return setConnection("fixture");
      try {
        await api.health();
      } catch {
        if (!cancelled) setConnection("fixture");
        return;
      }
      try {
        const live = await api.live();
        if (cancelled) return;
        setSnapshot(live);
        setScenarioId("live");
        setConnection("api-live");
      } catch (e) {
        if (cancelled) return;
        // 404: the API runs without a live store. 409: store present but not assessable.
        if (e instanceof ApiError && e.status === 409) {
          setError(readError(e));
          setConnection("api-live");
        } else setConnection("api-plan");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Plan API: evaluate every unit's default request once, for the switcher.
  useEffect(() => {
    if (connection !== "api-plan" || !bundle) return;
    const firsts = [...new Map(bundle.scenarios.map((s) => [s.unit, s])).values()];
    for (const s of bundle.scenarios.filter((x) => firsts.some((f) => f.id === x.id))) {
      api
        .plan(s.request)
        .then((plan) => setApiPlans((prev) => ({ ...prev, [s.id]: plan })))
        .catch(() => undefined);
    }
  }, [connection, bundle]);

  // Build the assessment for the selected situation.
  useEffect(() => {
    if (!bundle || connection === "probing") return;
    const token = ++request.current;
    setError(null);
    if (connection === "fixture") {
      setAssessment(fixtureAssessment(bundle, scenarioId));
      setLoadedAt(Date.now());
      return;
    }
    if (connection === "api-live") {
      if (snapshot) {
        setAssessment(fromLive(snapshot, null, [], "api-live", null));
        setLoadedAt(Date.now());
      }
      return;
    }
    const s = bundle.scenarios.find((x) => x.id === scenarioId) ?? bundle.scenarios[0]!;
    setBusy(true);
    api
      .plan(s.request)
      .then((plan) => {
        if (token !== request.current) return;
        setApiPlans((prev) => ({ ...prev, [s.id]: plan }));
        setAssessment(fromScenario(s, "api-plan", plan));
        setLoadedAt(Date.now());
      })
      .catch((e: unknown) => token === request.current && setError(readError(e)))
      .finally(() => token === request.current && setBusy(false));
  }, [bundle, connection, scenarioId, snapshot, refresh]);

  const evaluate = useCallback(() => {
    if (connection === "fixture" && bundle) {
      setAssessment(fixtureAssessment(bundle, scenarioId));
      setLoadedAt(Date.now());
      return;
    }
    if (connection === "api-plan") {
      // Re-run the same request: identical inputs give an identical, reproducible plan.
      setRefresh((n) => n + 1);
      return;
    }
    if (connection !== "api-live") return;
    const token = ++request.current;
    setBusy(true);
    setError(null);
    api
      .shadow({ horizon_minutes: 480, scenarios: 32 })
      .then((episode) => {
        if (token !== request.current) return;
        const a = episode.assessment;
        // Do not touch `snapshot`: it seeds the initial view only, and resetting it would erase the plan.
        setAssessment(
          fromLive(a.snapshot, a.plan, a.gate_reasons, "api-live", episode.episode_id, a.expires_at),
        );
        setLoadedAt(Date.now());
      })
      .catch((e: unknown) => token === request.current && setError(readError(e)))
      .finally(() => token === request.current && setBusy(false));
  }, [bundle, connection, scenarioId]);

  const units: UnitOption[] = useMemo(() => {
    if (connection === "api-live") {
      return [
        { id: LIVE_UNIT, name: "Médecine polyvalente", situations: [{ id: "live", label: "En direct" }] },
      ];
    }
    const map = new Map<string, UnitOption>();
    for (const s of bundle?.scenarios ?? []) {
      const u = map.get(s.unit) ?? { id: s.unit, name: s.unit_name, situations: [] };
      u.situations.push({ id: s.id, label: s.label });
      map.set(s.unit, u);
    }
    if (connection === "fixture") map.get(LIVE_UNIT)?.situations.push(...LIVE_SITUATIONS);
    return [...map.values()];
  }, [bundle, connection]);

  const unitOf = useCallback(
    (sid: string) =>
      sid.startsWith("live") ? LIVE_UNIT : (bundle?.scenarios.find((s) => s.id === sid)?.unit ?? LIVE_UNIT),
    [bundle],
  );
  const unitId = unitOf(scenarioId);
  const unit = units.find((u) => u.id === unitId);

  const setSituation = useCallback(
    (id: string) => {
      setScenarioId(id);
      lastByUnit.current[unitOf(id)] = id;
      writeUrl("situation", id);
    },
    [unitOf],
  );

  const setUnit = useCallback(
    (id: string) => {
      const target = units.find((u) => u.id === id);
      if (!target) return;
      const next = lastByUnit.current[id] ?? target.situations[0]?.id;
      if (next) setSituation(next);
    },
    [units, setSituation],
  );

  const summaries: UnitSummary[] = useMemo(
    () =>
      units.map((u) => {
        if (u.id === unitId) return unitSummary(u.id, u.name, assessment);
        if (!bundle || connection === "api-live") return unitSummary(u.id, u.name, null);
        const sid = lastByUnit.current[u.id] ?? u.situations[0]!.id;
        if (connection === "api-plan") {
          const s = bundle.scenarios.find((x) => x.id === sid);
          const plan = apiPlans[sid];
          return unitSummary(u.id, u.name, s && plan ? fromScenario(s, "api-plan", plan) : null);
        }
        return unitSummary(u.id, u.name, fixtureAssessment(bundle, sid));
      }),
    [units, unitId, assessment, bundle, connection, apiPlans],
  );

  return {
    connection,
    units,
    summaries,
    unitId,
    unitName: unit?.name ?? "Unité",
    setUnit,
    situations: unit?.situations ?? [],
    situationId: scenarioId,
    setSituation,
    assessment,
    awaitingEvaluation: connection === "api-live" && !!assessment && !assessment.episodeId,
    busy,
    error,
    evaluate,
    quality:
      (connection === "fixture" || connection === "api-plan") && unitId === LIVE_UNIT
        ? (bundle?.quality ?? null)
        : null,
    shadowSummary: connection === "api-live" || unitId !== LIVE_UNIT ? null : (bundle?.live.summary ?? null),
    loadedAt,
  };
}
