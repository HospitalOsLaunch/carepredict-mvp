import { fmtHours, fmtPct, fmtRelative, plural, relativeDay } from "../lib/format";

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

  it("says how long ago or how soon a moment is", () => {
    const now = new Date("2026-11-02T10:00:00Z").getTime();
    expect(fmtRelative("2026-11-02T09:59:40Z", now)).toBe("à l'instant");
    expect(fmtRelative("2026-11-02T09:56:00Z", now)).toBe("il y a 4 minutes");
    expect(fmtRelative("2026-11-02T10:12:00Z", now)).toBe("dans 12 minutes");
    expect(fmtRelative("2026-11-02T07:00:00Z", now)).toBe("il y a 3 heures");
    expect(fmtRelative("2026-10-31T10:00:00Z", now)).toBe("avant-hier");
    expect(fmtRelative(null, now)).toBe("—");
  });

  it("names relative days", () => {
    expect(relativeDay("2026-10-26", "2026-10-25")).toBe("demain");
    expect(relativeDay("2026-10-30", "2026-10-25")).toBe("dans 5 j");
  });
});
