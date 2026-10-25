import { fmtHours, fmtPct, plural, relativeDay } from "../lib/format";

describe("format", () => {
  it("formats waiting times the way coordinators say them", () => {
    expect(fmtHours(0.25)).toBe("15 min");
    expect(fmtHours(19.4)).toBe("19 h");
    expect(fmtHours(72)).toBe("3 j");
    expect(fmtHours(null)).toBe("—");
  });

  it("formats percentages and plurals in French", () => {
    expect(fmtPct(0.8937, 1)).toBe("89,4 %");
    expect(plural(1, "demande", "demandes")).toBe("1 demande");
    expect(plural(0, "lit", "lits")).toBe("0 lit");
    expect(plural(3, "lit", "lits")).toBe("3 lits");
  });

  it("names relative days", () => {
    expect(relativeDay("2026-10-26", "2026-10-25")).toBe("demain");
    expect(relativeDay("2026-10-30", "2026-10-25")).toBe("dans 5 j");
  });
});
