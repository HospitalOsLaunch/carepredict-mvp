import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type { LiveSnapshot, ShadowSummary, SourceReceipt } from "../api/types";
import { type Assessment, fromLive } from "../domain/view";
import { type FixtureBundle, type ScenarioFixture, loadFixtures } from "./fixtures";

/**
 * Where the cockpit reads from:
 * - "api-live": local FastAPI with a shadow LiveStore (GET /hybrid/live, POST /hybrid/shadow)
 * - "api-plan": local FastAPI without live store; demonstration requests sent to POST /hybrid/plan
 * - "fixture":  no API reachable; precomputed outputs of the same planner
 */
export type Connection = "probing" | "api-live" | "api-plan" | "fixture";

export interface ScenarioOption {
  id: string;
  label: string;
}

export interface Store {
  connection: Connection;
  scenarios: ScenarioOption[];
  scenarioId: string;
  setScenario: (id: string) => void;
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

const LIVE_OPTIONS: ScenarioOption[] = [
  { id: "live", label: "Unité en observation" },
  { id: "live-stale", label: "Confirmations périmées" },
];

function fromScenario(s: ScenarioFixture, origin: Assessment["origin"]): Assessment {
  return {
    origin,
    scenarioId: s.id,
    scenarioLabel: s.label,
    state: s.state,
    plan: s.plan,
    gateReasons: s.plan.decision === "abstain" ? s.plan.reasons : [],
    events: s.request.events,
    resources: null,
    receivedAtBySource: null,
    trace: origin === "fixture" ? s.trace : null,
    episodeId: null,
    factBudgetMinutes: s.request.max_age_minutes,
    expiresAt: s.plan.expires_at,
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

function initialScenario(): string {
  const fromUrl = new URLSearchParams(window.location.search).get("scenario");
  return fromUrl ?? "nominal";
}

export function useAssessment(): Store {
  const [connection, setConnection] = useState<Connection>("probing");
  const [bundle, setBundle] = useState<FixtureBundle | null>(null);
  const [scenarioId, setScenarioId] = useState(initialScenario);
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [snapshot, setSnapshot] = useState<LiveSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadedAt, setLoadedAt] = useState(() => Date.now());
  const request = useRef(0);

  // Probe once: live store → plan API → bundled fixtures.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const fixtures = await loadFixtures();
      if (cancelled) return;
      setBundle(fixtures);
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

  // Build the assessment for the selected scenario.
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
        setAssessment({
          ...fromScenario(s, "api-plan"),
          plan,
          expiresAt: plan.expires_at,
          gateReasons: plan.decision === "abstain" ? plan.reasons : [],
        });
        setLoadedAt(Date.now());
      })
      .catch((e: unknown) => token === request.current && setError(readError(e)))
      .finally(() => token === request.current && setBusy(false));
  }, [bundle, connection, scenarioId, snapshot]);

  const evaluate = useCallback(() => {
    if (connection === "fixture" && bundle) {
      setAssessment(fixtureAssessment(bundle, scenarioId));
      setLoadedAt(Date.now());
      return;
    }
    if (connection === "api-plan") {
      // Re-run the same request: identical inputs give an identical, reproducible plan.
      setScenarioId((id) => id);
      setBundle((b) => (b ? { ...b } : b));
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

  const setScenario = useCallback((id: string) => {
    setScenarioId(id);
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("scenario", id);
      window.history.replaceState(null, "", url);
    } catch {
      /* sandboxed frames may refuse URL changes; the selection still applies */
    }
  }, []);

  const scenarios: ScenarioOption[] =
    connection === "api-live"
      ? [{ id: "live", label: "Unité en observation (API locale)" }]
      : [
          ...(bundle?.scenarios.map((s) => ({ id: s.id, label: s.label })) ?? []),
          ...(connection === "fixture" ? LIVE_OPTIONS : []),
        ];

  return {
    connection,
    scenarios,
    scenarioId,
    setScenario,
    assessment,
    awaitingEvaluation: connection === "api-live" && !!assessment && !assessment.episodeId,
    busy,
    error,
    evaluate,
    quality: connection === "fixture" || connection === "api-plan" ? (bundle?.quality ?? null) : null,
    shadowSummary: connection === "api-live" ? null : (bundle?.live.summary ?? null),
    loadedAt,
  };
}
