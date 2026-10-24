import { fireEvent, render, screen, within } from "@testing-library/react";
import { App } from "./App";

beforeEach(() => {
  vi.stubGlobal("scrollTo", vi.fn());
  // jsdom has no <dialog> methods.
  HTMLDialogElement.prototype.showModal = vi.fn();
  // No local API in tests: the cockpit must fall back to the bundled planner outputs.
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  window.history.replaceState(null, "", "/?situation=nominal");
  window.location.hash = "";
});

const ready = () => screen.findByRole("heading", { name: "Demander le transport de P-0412" });

describe("cockpit", () => {
  it("leads with the tension strip, the next action and the three flow zones", async () => {
    render(<App />);
    await ready();
    expect(screen.getByText(/Démonstration : unités et patients fictifs/)).toBeTruthy();
    const strip = screen.getByRole("navigation", { name: "Situation de l'unité" });
    expect(within(strip).getByRole("button", { name: /À placer\s*4/ })).toBeTruthy();
    const release = screen.getByRole("region", { name: "Libérer" });
    expect(within(release).getByLabelText("Étapes de sortie de P-0412")).toBeTruthy();
    expect(within(release).getAllByText("Demander le transport").length).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "Lits" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Attribuer" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Je l'aurais fait/ })).toBeTruthy();
  });

  it("abstains instead of proposing on unreliable data", async () => {
    window.history.replaceState(null, "", "/?situation=incomplete");
    render(<App />);
    expect(await screen.findByRole("heading", { name: /Pas de proposition/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Je l'aurais fait/ })).toBeNull();
    expect(screen.getByText("Information manquante : logistique de sortie P-0397")).toBeTruthy();
  });

  it("switches units from the listbox and with digit shortcuts", async () => {
    render(<App />);
    await ready();
    const button = screen.getByRole("button", { name: /Médecine polyvalente/ });
    fireEvent.click(button);
    const list = await screen.findByRole("listbox", { name: "Changer d'unité" });
    expect(within(list).getAllByRole("option")).toHaveLength(4);
    fireEvent.click(within(list).getByRole("option", { name: /Court séjour gériatrique/ }));
    expect(await screen.findByRole("heading", { name: "Prioriser le bionettoyage du lit G17" })).toBeTruthy();
    fireEvent.keyDown(window, { key: "4" });
    expect(await screen.findByRole("heading", { name: /Pas de proposition/ })).toBeTruthy();
    fireEvent.keyDown(window, { key: "3" });
    expect(await screen.findByRole("heading", { name: "Ne rien changer pour l'instant" })).toBeTruthy();
  });

  it("records an opinion in two keystrokes and nothing is sent", async () => {
    window.localStorage.clear();
    render(<App />);
    await ready();
    fireEvent.keyDown(window, { key: "n" });
    expect(await screen.findByText(/Pourquoi \?/)).toBeTruthy();
    fireEvent.keyDown(window, { key: "1" });
    expect(await screen.findByText("Vous ne l'auriez pas fait")).toBeTruthy();
    expect(screen.getByText("(Déjà fait)")).toBeTruthy();
    expect(vi.mocked(fetch).mock.calls.every(([url]) => !String(url).includes("/plan"))).toBe(true);
  });

  it("never offers an execution control", async () => {
    render(<App />);
    await ready();
    const labels = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    for (const forbidden of [/envoyer/i, /exécuter/i, /réserver/i, /approuver/i]) {
      expect(labels.some((l) => forbidden.test(l))).toBe(false);
    }
  });
});
