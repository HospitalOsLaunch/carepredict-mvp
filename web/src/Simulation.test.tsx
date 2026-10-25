import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App } from "./App";
import type { DemoView } from "./api/simulator";
import initial from "./test/dynamic-session.json";

let view: DemoView;
const response = (value: unknown, status = 200) => ({
  ok: status < 400, status, statusText: "test", json: async () => value,
});

beforeEach(() => {
  view = structuredClone(initial) as DemoView;
  window.localStorage.clear();
  window.history.replaceState(null, "", "/?source=simulator");
  window.location.hash = "";
  vi.stubGlobal("scrollTo", vi.fn());
  HTMLDialogElement.prototype.showModal = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/demo/decision")) {
      const body = JSON.parse(String(init?.body)) as { request_id: string; accept: boolean; plan_id: string };
      view = { ...view, revision: view.revision + 1, can_apply: false, commands: [{
        request_id: body.request_id, plan_id: body.plan_id, at: view.now,
        status: body.accept ? "accepted" : "refusal_recorded", outcome_at: null,
        processing_seconds: 30, effect_scope: "simulator_only",
      }] };
    }
    return response(view);
  }));
});

const ready = () => screen.findByRole("heading", { name: "Prioriser le bionettoyage du lit G02" });

it("uses the connected scenario and sends one explicit, versioned simulated decision", async () => {
  render(<App />);
  await ready();
  expect(screen.getByText("Hôpital simulé · 3 lits")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Valider/ })).toBeNull();
  const apply = screen.getByRole("button", { name: "Appliquer dans le scénario" });
  fireEvent.click(apply);
  await screen.findByText(/Acceptée, traitement en cours/);
  expect((apply as HTMLButtonElement).disabled).toBe(true);
  const writes = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/demo/decision"));
  expect(writes).toHaveLength(1);
  const payload = JSON.parse(String(writes[0]![1]?.body));
  expect(payload.run_id).toBe(view.run_id);
  expect(payload.revision).toBe(initial.revision);
  expect(payload.snapshot_fingerprint).toBe(initial.snapshot.semantic_fingerprint);
  expect(payload.action).toBeUndefined();
});

it("records refusal on the simulator instead of in the local observation journal", async () => {
  render(<App />);
  await ready();
  fireEvent.click(screen.getByRole("button", { name: "Refuser dans le scénario" }));
  await screen.findByText(/Refus enregistré, lecture en cours/);
  const writes = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/demo/decision"));
  expect(JSON.parse(String(writes[0]![1]?.body)).accept).toBe(false);
});

it("accepts a click during a pending read and ignores the late stale response", async () => {
  render(<App />);
  await ready();
  let release: (value: Response) => void = () => { throw new Error("read did not start"); };
  vi.mocked(fetch).mockImplementationOnce(() => new Promise<Response>((resolve) => { release = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "Actualiser" }));
  fireEvent.click(screen.getByRole("button", { name: "Appliquer dans le scénario" }));
  await screen.findByText(/Acceptée, traitement en cours/);
  await act(async () => { release(response(initial) as Response); });
  expect(screen.getByText(/Acceptée, traitement en cours/)).toBeTruthy();
  expect((screen.getByRole("button", { name: "Appliquer dans le scénario" }) as HTMLButtonElement).disabled).toBe(true);
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/demo/decision"))).toHaveLength(1);
});

it("fails visibly with no fixture fallback when the simulator cannot be reached", async () => {
  vi.mocked(fetch).mockRejectedValue(new TypeError("offline"));
  render(<App />);
  expect((await screen.findByRole("alert")).textContent).toMatch(/Aucune donnée précalculée/);
  expect(screen.queryByText("Patients fictifs, vrai planificateur")).toBeNull();
  expect(screen.queryByRole("region", { name: "Attribuer" })).toBeNull();
  expect(vi.mocked(fetch).mock.calls.every(([url]) => String(url).includes("/demo/"))).toBe(true);
});

it("does not replay a rejected action and makes the conflict visible", async () => {
  render(<App />);
  await ready();
  vi.mocked(fetch).mockResolvedValue(response({ detail: "proposal_expired" }, 409) as Response);
  fireEvent.click(screen.getByRole("button", { name: "Appliquer dans le scénario" }));
  expect((await screen.findByRole("alert")).textContent).toMatch(/proposition a changé/);
  await waitFor(() => expect((screen.getByRole("button", { name: "Appliquer dans le scénario" }) as HTMLButtonElement).disabled).toBe(true));
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/demo/decision"))).toHaveLength(1);
});

it("uses server time while paused and does not offer real-world completion controls", async () => {
  render(<App />);
  await ready();
  expect(screen.getByText("En pause")).toBeTruthy();
  expect(within(screen.getByRole("region", { name: "Piloter le scénario" })).getByText("08:30")).toBeTruthy();
  expect(screen.getByText("Simulation connectée")).toBeTruthy();
  expect(screen.queryByText("Observation seule")).toBeNull();
  expect(screen.queryByRole("button", { name: "C'est fait" })).toBeNull();
  fireEvent.keyDown(window, { key: "o" });
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/demo/decision"))).toHaveLength(0);
});
