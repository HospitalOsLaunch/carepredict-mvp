import incomplete from "../fixtures/scenario-incomplete.json";
import nominal from "../fixtures/scenario-nominal.json";
import perturbations from "../fixtures/scenario-perturbations.json";
import live from "../fixtures/live.json";
import type { ScenarioFixture } from "../data/fixtures";
import type { ShadowEpisode } from "../api/types";
import { explain, isKnownCode } from "./labels";
import {
  type Assessment,
  comparison,
  freshnessIndex,
  fromLive,
  queueEntries,
  releaseChains,
  situation,
} from "./view";

const scenarios = [nominal, perturbations, incomplete] as unknown as ScenarioFixture[];

function assess(s: ScenarioFixture): Assessment {
  return {
    origin: "fixture",
    scenarioId: s.id,
    scenarioLabel: s.label,
    state: s.state,
    plan: s.plan,
    gateReasons: s.plan.decision === "abstain" ? s.plan.reasons : [],
    events: s.request.events,
    resources: null,
    receivedAtBySource: null,
    trace: s.trace,
    episodeId: null,
    factBudgetMinutes: s.request.max_age_minutes,
    expiresAt: s.plan.expires_at,
  };
}

describe("vocabulary covers every code the planner emitted", () => {
  const episodes = [live.episode, live.stale_episode] as unknown as ShadowEpisode[];
  const codes = new Set<string>([
    ...scenarios.flatMap((s) => [
      ...s.plan.reasons,
      ...s.plan.warnings,
      ...s.state.issues,
      ...s.state.warnings,
      ...s.plan.discharge_readiness.flatMap((r) => r.blockers),
    ]),
    ...episodes.flatMap((e) => e.assessment.gate_reasons),
  ]);
  it.each([...codes])("%s", (code) => {
    expect(isKnownCode(code)).toBe(true);
    expect(explain(code)).not.toMatch(/_/);
  });
});

describe("release chains (libérer)", () => {
  const a = assess(nominal as unknown as ScenarioFixture);
  const chains = releaseChains(a.state, a.plan);

  it("lists departures in preparation, most actionable first", () => {
    expect(chains.map((c) => c.patient.id)).toEqual(["P-0412", "P-0420", "P-0388", "P-0397", "P-0431"]);
  });

  it("shows exactly the missing link, consistent with backend blockers", () => {
    const p0412 = chains[0]!;
    expect(p0412.readiness?.blockers).toEqual(["transport_not_requested"]);
    expect(p0412.links.find((l) => l.id === "transport")?.status).toBe("todo");
    expect(p0412.links.filter((l) => l.status === "todo" || l.status === "blocked")).toHaveLength(1);
    const p0431 = chains.find((c) => c.patient.id === "P-0431")!;
    expect(p0431.links.find((l) => l.id === "medical")?.status).toBe("unknown");
  });

  it("hands the freed oxygen bed to the oxygen patients only", () => {
    expect(chains[0]!.nextCandidates.map((p) => p.id)).toEqual(["U-1049", "U-1041", "U-1043"]);
  });
});

describe("waiting queue (attribuer)", () => {
  const a = assess(nominal as unknown as ScenarioFixture);
  it("orders by professional priority then waiting time, with usable beds", () => {
    const q = queueEntries(a.state);
    expect(q.map((e) => e.patient.id)).toEqual(["U-1049", "U-1041", "U-1043", "U-1047"]);
    expect(q[0]!.usableNow).toHaveLength(0);
    expect(q[2]!.usableNow.map((b) => b.id)).toEqual(["L08"]);
  });

  it("summarises the unit in the situation line", () => {
    expect(situation(a.state, a.plan)).toMatchObject({
      waiting: 4,
      usable: 1,
      dirty: 2,
      departuresPrepared: 5,
    });
  });
});

describe("proposal comparison", () => {
  it("compares the selected action with doing nothing on the same scenarios", () => {
    const c = comparison((nominal as unknown as ScenarioFixture).plan);
    expect(c.selected?.action.kind).toBe("request_transport");
    expect(c.deltaMean).toBeLessThan(0);
    expect(c.ranked[0]).toBe(c.selected);
  });
});

describe("freshness is decided by the backend", () => {
  it("marks only facts the backend declared stale", () => {
    const f = freshnessIndex(assess(incomplete as unknown as ScenarioFixture));
    expect(f.get("bed:L11")?.stale).toBe(true);
    expect([...f.values()].filter((x) => x.stale).map((x) => x.key)).toEqual(["bed:L11"]);
    expect(f.get("bed:L14")?.stale).toBe(false);
  });

  it("keeps live gates visible when the planner is blocked", () => {
    const e = live.stale_episode as unknown as ShadowEpisode;
    const a = fromLive(
      e.assessment.snapshot,
      e.assessment.plan,
      e.assessment.gate_reasons,
      "fixture",
      e.episode_id,
    );
    expect(a.plan).toBeNull();
    expect(a.gateReasons.some((c) => c.startsWith("stale_confirmation:"))).toBe(true);
  });
});

it("does not count a requested transport as ready without availability", () => {
  const state = structuredClone(nominal.state) as ScenarioFixture["state"];
  const patient = state.patients.find(p => p.status === "admitted")!;
  patient.medically_cleared = true;
  state.discharges = [{kind:"discharge",id:patient.id,documents_ready:true,escort_required:false,escort_confirmed:null,downstream_required:false,downstream_pool_id:null,transport_required:true,transport_pool_id:"patient-transport",transport_requested:true}];
  state.pools = [{kind:"pool",id:"patient-transport",resource:"transport",unit_ids:patient.compatible_units,available:0}];
  const chain = releaseChains(state,null).find(c=>c.patient.id===patient.id)!;
  expect(chain.links.find(l=>l.id==="transport")?.status).toBe("todo");
  state.pools[0]!.available = 1;
  expect(releaseChains(state,null).find(c=>c.patient.id===patient.id)!.links.find(l=>l.id==="transport")?.status).toBe("ok");
});
