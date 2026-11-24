import decision from "../fixtures/decision.json";
import nominal from "../fixtures/scenario-nominal.json";
import type { DsFixture } from "../api/decision";
import { momentLabel, offsetTo, rebase, shiftClockText } from "./clock";
import { planToNow } from "./useDecision";

const NOW = Date.parse("2026-11-24T15:23:41Z"); // 16:23 in Paris

describe("demonstration clock", () => {
  it("moves every instant by one offset, keeping formats and gaps", () => {
    const offset = offsetTo(nominal.state.at, NOW, 5);
    const moved = rebase(nominal, offset);
    expect(moved.state.at).toBe("2026-11-24T15:20:00Z");
    const gap = (o: { state: { at: string }; plan: { expires_at: string } }) =>
      Date.parse(o.plan.expires_at) - Date.parse(o.state.at);
    expect(gap(moved)).toBe(gap(nominal));
    expect(rebase("2026-11-16T19:00:00+00:00", 3_600_000)).toBe("2026-11-16T20:00:00+00:00");
    expect(rebase("Matinée ordinaire", 3_600_000)).toBe("Matinée ordinaire");
  });

  it("names the moment of the day from the moved instant", () => {
    expect(momentLabel("Matinée ordinaire", "2026-11-24T15:20:00Z")).toBe("Après-midi ordinaire");
    expect(momentLabel("Matinée calme", "2026-11-24T07:20:00Z")).toBe("Matinée calme");
    expect(momentLabel("Matinée sous tension", "2026-11-24T22:20:00Z")).toBe("Nuit sous tension");
    expect(momentLabel("Flux interrompu", "2026-11-24T22:20:00Z")).toBe("Flux interrompu");
  });

  it("moves the 24-hour plan by whole days to the nearest 20:00 handover, hours kept", () => {
    const fx = planToNow(decision as unknown as DsFixture, NOW);
    const unit = fx.units[0]!;
    expect(unit.snapshot.as_of).toBe("2026-11-24T19:00:00Z"); // today 20:00 in Paris
    const traj = unit.recommendation.bundle!.evaluations[0]!.trajectory;
    expect(traj[0]!.local_label).toBe("20:00");
    expect(fx.manual.find((m) => m.id === "x1x2")!.label).toMatch(/^X1 sortie 10:00/);
    const diag = fx.units.find((u) => u.id === "insufficient_data")!.recommendation.diagnostics[0]!;
    expect(diag).toMatch(/2026-11-25 14:00 CET/);
    expect(shiftClockText("sortie 10:00", -4 * 3_600_000)).toBe("sortie 06:00");
  });
});
