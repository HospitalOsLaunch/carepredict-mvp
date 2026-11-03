import { unitLabel } from "../lib/queries";

describe("unitLabel", () => {
  const vocab = {
    mentions: { geriatrie: "Gériatrie" },
    unit_codes: { chirurgie_orthopedique: "Chirurgie orthopédique" }
  };

  it("names an SMR mention and an MCO unit the way the teams say them", () => {
    expect(unitLabel(vocab, "geriatrie")).toBe("Gériatrie");
    expect(unitLabel(vocab, "chirurgie_orthopedique")).toBe("Chirurgie orthopédique");
  });

  it("never shows a raw code: an unknown one is made readable", () => {
    expect(unitLabel(vocab, "soins_palliatifs")).toBe("Soins palliatifs");
    expect(unitLabel(undefined, "court_sejour_geriatrique")).toBe("Court sejour geriatrique");
    expect(unitLabel(vocab, null)).toBe("—");
  });
});
