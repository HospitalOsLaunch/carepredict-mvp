import { fireEvent, render, screen, within } from "@testing-library/react";
import { App } from "./App";
import { journal } from "./data/journal";

beforeEach(() => {
  window.localStorage.clear();
  journal.reset();
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
    expect(screen.getByText("Patients fictifs, vrai planificateur")).toBeTruthy();
    const strip = screen.getByRole("navigation", { name: "Situation de l'unité" });
    expect(within(strip).getByRole("button", { name: /À placer\s*4/ })).toBeTruthy();
    const release = screen.getByRole("region", { name: "Libérer" });
    expect(within(release).getByLabelText("Étapes de sortie de P-0412")).toBeTruthy();
    expect(within(release).getAllByText("Demander le transport").length).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "Lits" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Attribuer" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Valider/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Refuser/ })).toBeTruthy();
  });

  it("abstains instead of proposing on unreliable data", async () => {
    window.history.replaceState(null, "", "/?situation=incomplete");
    render(<App />);
    expect(await screen.findByRole("heading", { name: /Pas de proposition/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Valider/ })).toBeNull();
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

  it("refuses in two keystrokes, keeps the reason and sends nothing", async () => {
    render(<App />);
    await ready();
    fireEvent.keyDown(window, { key: "n" });
    expect(await screen.findByText(/Pourquoi \?/)).toBeTruthy();
    fireEvent.keyDown(window, { key: "1" });
    expect(await screen.findByText("Refusée : déjà fait")).toBeTruthy();
    // Undo twice at hand: in the card and in the toast.
    expect(screen.getAllByRole("button", { name: "Annuler" })).toHaveLength(2);
    expect(vi.mocked(fetch).mock.calls.every(([url]) => !String(url).includes("/plan"))).toBe(true);
  });

  it("validates, then marks done, with undo at each step", async () => {
    render(<App />);
    await ready();
    fireEvent.click(screen.getByRole("button", { name: /Valider/ }));
    expect(await screen.findByText(/^Validée par Vous/)).toBeTruthy();
    expect(screen.getByText(/Appelez le transport pour P-0412/)).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Annuler" })[0]!);
    expect(await screen.findByRole("button", { name: /Valider/ })).toBeTruthy();
    fireEvent.keyDown(window, { key: "o" });
    await screen.findByText(/^Validée par Vous/);
    fireEvent.keyDown(window, { key: "f" });
    expect(await screen.findByText("Faite. Merci !")).toBeTruthy();
  });

  it("offers the other useful options and lets the team choose one instead", async () => {
    render(<App />);
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "1 autre option utile" }));
    expect(screen.getByText("Prioriser le bionettoyage du lit L11")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Choisir plutôt" }));
    expect(await screen.findByText("Refusée : autre option préférée")).toBeTruthy();
    const tray = screen.getByRole("region", { name: /En cours de votre côté/ });
    expect(within(tray).getByText("Prioriser le bionettoyage du lit L11")).toBeTruthy();
  });

  it("keeps every decision in a journal colleagues can filter and open", async () => {
    render(<App />);
    await ready();
    fireEvent.keyDown(window, { key: "o" });
    await screen.findByText(/^Validée par Vous/);
    window.location.hash = "/journal";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(await screen.findByRole("heading", { name: "Journal des décisions" })).toBeTruthy();
    const follow = screen.getByRole("region", { name: "À suivre" });
    expect(within(follow).getByText("Demander le transport de P-0412")).toBeTruthy();
    const history = screen.getByRole("region", { name: "Historique" });
    // Demonstration history from colleagues, read-only.
    expect(within(history).getAllByText(/Karim T\./).length).toBeGreaterThan(0);
    fireEvent.click(within(history).getByRole("button", { name: /^Refusées/ }));
    expect(within(history).queryByText("Demander le transport de P-0412")).toBeNull();
    expect(within(history).getByText("Demander le transport de G-2207")).toBeTruthy();
    window.location.hash = "/journal/demo-2";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    const detail = (await screen.findAllByRole("region", { name: "Demander le transport de G-2207" }))[0]!;
    expect(within(detail).getByText(/Patient revu par le médecin/)).toBeTruthy();
    expect(within(detail).getByText("Autre priorité clinique")).toBeTruthy();
  });

  it("keeps decisions on fictitious patients out of the unit's journal, origin recorded", async () => {
    render(<App />);
    await ready();
    fireEvent.keyDown(window, { key: "o" });
    await screen.findByText(/^Validée par Vous/);
    const demo = JSON.parse(window.localStorage.getItem("hospitalos.journal.v2.demo") ?? "[]") as Array<{
      id: string;
      origin: string;
      stateFingerprint: string | null;
    }>;
    const record = demo.find((r) => r.id.includes("request_transport"))!;
    expect(record.origin).toBe("fixture");
    expect(record.id.startsWith("fixture:")).toBe(true);
    expect(record.stateFingerprint).toMatch(/^[0-9a-f]{8,}/);
    expect(window.localStorage.getItem("hospitalos.journal.v2.live")).toBeNull();
    window.location.hash = `/journal/${encodeURIComponent(record.id)}`;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(await screen.findByTestId("journal-space")).toBeTruthy();
    expect(screen.getAllByTestId("jdetail-origin")[0]!.textContent).toBe("Démonstration · patients fictifs");
  });

  it("labels a replayed observation as a replay, never as the unit in observation", async () => {
    window.history.replaceState(null, "", "/?situation=live");
    render(<App />);
    expect(await screen.findByRole("option", { name: "Observation rejouée" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Évaluer maintenant/ })).toBeNull();
  });

  it("moves an old journal without origins aside, flagged, never into the unit's journal", async () => {
    window.localStorage.setItem(
      "hospitalos.journal.v1",
      JSON.stringify([
        {
          id: "plan-old:request_transport:L02:P-0001",
          planId: "plan-old",
          unitId: "medecine-polyvalente",
          unitName: "Médecine polyvalente",
          situation: "Unité en observation",
          stateAt: "2026-10-24T06:00:00Z",
          proposedAt: "2026-10-24T06:00:00Z",
          expiresAt: "2026-10-24T06:15:00Z",
          action: { kind: "request_transport", bed_id: "L02", patient_id: "P-0001" },
          title: "Demander le transport de P-0001",
          short: "Transport P-0001",
          rank: 0,
          deltaRatio: -0.1,
          horizonEnd: "14:00",
          why: [],
          events: [{ at: "2026-10-24T06:00:00Z", type: "proposed", by: null }],
        },
      ]),
    );
    render(<App />);
    await ready();
    window.location.hash = "/journal";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    const history = await screen.findByRole("region", { name: "Historique" });
    fireEvent.change(within(history).getByRole("combobox", { name: "Période" }), { target: { value: "all" } });
    expect(within(history).getByText("origine non enregistrée")).toBeTruthy();
    expect(window.localStorage.getItem("hospitalos.journal.v2.live")).toBeNull();
  });

  it("gives a bed to one patient in line at a time", async () => {
    render(<App />);
    await ready();
    const queue = screen.getByRole("region", { name: "Attribuer" });
    expect(within(queue).getAllByText(/^Lit prêt : L08$/)).toHaveLength(1);
    expect(within(queue).getByText("L08 ira d'abord à U-1043")).toBeTruthy();
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
