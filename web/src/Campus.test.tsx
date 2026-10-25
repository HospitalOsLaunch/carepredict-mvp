import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";
import fixture from "./test/virtual-hospital.json";
const response = (v: unknown) => ({ ok: true, status: 200, json: async () => v }) as Response;
const history = {
  from: "2026-09-27T10:00:00Z", until: "2026-10-25T10:00:00Z", samples: 673, capacity: 18,
  daily: [{date: "2026-10-25", mean_occupied: 12, samples: 12}], recent: [],
  forecast: { origin: "2026-10-25T10:00:00Z", horizon_minutes: 60, occupied: 13.5 },
  model: { version: "occupancy-ridge-hourly-v1", train_from: "2026-09-28T10:00:00Z", train_until: "2026-10-18T10:00:00Z",
    validation_from: "2026-10-18T11:00:00Z", validation_until: "2026-10-25T10:00:00Z", training_pairs: 480,
    validation_pairs: 168, mae_beds: 1.2, persistence_mae_beds: 1.4, selected: "ridge", data_sha256: "abc123" },
};
beforeEach(() => {
  window.history.replaceState({}, "", "/");
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal("fetch", vi.fn(async (url) => {
    const path = String(url);
    if (path.endsWith("/product/hospitals")) return response({schema_version: "HOSPITAL_WORKSPACE_1", hospitals: [{
      id: "H1", name: "Saint-Clair", units: [{id: "geriatrie", name: "Gériatrie", available: true}, {id: "medecine", name: "Médecine", available: true}]}]});
    if (path.endsWith("/overview")) return response({hospital_id: "H1", name: "Saint-Clair", now: fixture.now, timezone: "Europe/Paris",
      units: [{id: "geriatrie", name: "Gériatrie", capacity: 18, occupied: 12, waiting: 2, available: true, observed_at: fixture.now}]});
    if (path.endsWith("/history")) return response(history);
    const unit = path.includes("/medecine") ? "medecine" : "geriatrie";
    return response({...structuredClone(fixture), hospital_id: "H1", hospital_name: "Saint-Clair", unit_id: unit,
      unit_name: unit === "geriatrie" ? "Gériatrie" : "Médecine", clock_rate: 1});
  }));
});
it("opens a unit within one hospital and exposes historical model provenance", async () => {
  render(<App />);
  await screen.findByText("L’activité dans la durée");
  expect((screen.getByLabelText("Unité") as HTMLSelectElement).value).toBe("H1/geriatrie");
  expect(screen.getByText(/673 observations/)).toBeTruthy();
  expect(screen.getByText(/Prévision apprise/)).toBeTruthy();
  expect(screen.getByRole("link", {name: /Télécharger les observations/}).getAttribute("href")).toContain("/H1/units/geriatrie/history/export");
});
it("scopes a decision to both hospital and unit", async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole("button", {name: "Valider la proposition"}));
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(true));
  const [url, init] = vi.mocked(fetch).mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(url).toBe("/api/product/hospitals/H1/units/geriatrie/decisions");
  expect(JSON.parse(String(init?.body))).toMatchObject({hospital_id: "H1", unit_id: "geriatrie"});
});
it("discards delayed history when switching units in the same hospital", async () => {
  let release: (value: Response) => void = () => undefined;
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((url, init) => String(url).endsWith("/geriatrie/history")
    ? new Promise(resolve => { release = resolve; }) : original(url, init));
  render(<App />);
  await screen.findByRole("button", {name: "Valider la proposition"});
  fireEvent.change(screen.getByLabelText("Unité"), {target: {value: "H1/medecine"}});
  await screen.findByText("Mémoire de l’unité · Médecine");
  await act(async () => release(response({...history, samples: 999999})));
  expect(screen.queryByText(/999999 observations/)).toBeNull();
});
