import { render, screen, within } from "@testing-library/react";
import { App } from "./App";

beforeEach(() => {
  vi.stubGlobal("scrollTo", vi.fn());
  // No local API in tests: the cockpit must fall back to the bundled planner outputs.
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  window.history.replaceState(null, "", "/?scenario=nominal");
  window.location.hash = "";
});

describe("cockpit", () => {
  it("leads with the proposal, the release chains and the queue", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Demander le transport de P-0412" })).toBeTruthy();
    expect(screen.getByText(/Démonstration : unité et patients fictifs/)).toBeTruthy();
    const releases = screen.getByRole("region", { name: "Sorties à libérer" });
    expect(within(releases).getByLabelText("Étapes de sortie de P-0412")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Patients à placer" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Je l'aurais fait/ })).toBeTruthy();
  });

  it("abstains instead of proposing on unreliable data", async () => {
    window.history.replaceState(null, "", "/?scenario=incomplete");
    render(<App />);
    expect(await screen.findByRole("heading", { name: /Pas de proposition/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Je l'aurais fait/ })).toBeNull();
    expect(screen.getByText("Information manquante : logistique de sortie P-0397")).toBeTruthy();
  });

  it("never offers an execution control", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Demander le transport de P-0412" });
    const labels = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    for (const forbidden of [/envoyer/i, /exécuter/i, /réserver/i, /approuver/i]) {
      expect(labels.some((l) => forbidden.test(l))).toBe(false);
    }
  });
});
