import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";
import fixture from "./test/virtual-hospital.json";
import type { HospitalView } from "./api/virtual";
const response = (v: unknown, status = 200) => ({ ok: status < 400, status, statusText: "test", json: async () => v }) as Response;
function view(id: string) { return { ...structuredClone(fixture), hospital_id: id, hospital_name: `Hôpital ${id}` } as HospitalView; }
beforeEach(() => {
  window.history.replaceState({}, "", "/");
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal("fetch", vi.fn(async (url, init) => {
    const id = String(url).includes("X2") ? "X2" : "X1";
    if (String(url).endsWith("/product/hospitals")) return response({ schema_version: "HOSPITAL_WORKSPACE_1", hospitals: ["X1", "X2"].map(id => ({ id, name: `Hôpital ${id}`, unit_name: "Gériatrie", available: true })) });
    const v = view(id);
    if (init?.method === "POST") { v.can_decide = false; v.decisions = [{ request_id: "receipt", plan_id: "p", at: v.now, action: "prioritize_cleaning", bed_id: "G02", patient_id: null, accepted: true, reason: "", actor: "Équipe de garde", status: "accepted", outcome_at: null }]; }
    return response(v);
  }));
});
it("opens the business cockpit without scenario controls and switches hospital", async () => {
  render(<App />);
  await screen.findByRole("button", { name: "Valider la proposition" });
  expect(screen.getByLabelText("Établissement")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Comparer" })).toBeNull();
  expect(screen.queryByText("Avancer de 5 min")).toBeNull();
  expect(screen.queryByLabelText("Graine du scénario")).toBeNull();
  fireEvent.change(screen.getByLabelText("Établissement"), { target: { value: "X2" } });
  await screen.findByText("Proposition · Hôpital X2");
  expect(screen.queryByText("Proposition · Hôpital X1")).toBeNull();
});
it("sends an authoritative scoped decision, without local completion controls", async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Valider la proposition" }));
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([, i]) => i?.method === "POST")).toBe(true));
  const [url, init] = vi.mocked(fetch).mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(url).toBe("/api/product/hospitals/X1/decisions");
  expect(JSON.parse(String(init?.body))).toMatchObject({ hospital_id: "X1", run_id: fixture.run_id, revision: fixture.revision, accept: true });
  expect(screen.queryByRole("button", { name: /C'est fait/ })).toBeNull();
});
it("requires a reason for refusal", async () => {
  render(<App />); fireEvent.click(await screen.findByRole("button", { name: "Refuser" }));
  expect((screen.getByRole("button", { name: "Enregistrer le refus" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Motif du refus"), { target: { value: "Équipe déjà engagée" } });
  fireEvent.click(screen.getByRole("button", { name: "Enregistrer le refus" }));
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([, i]) => i?.method === "POST")).toBe(true));
  const [, init] = vi.mocked(fetch).mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(JSON.parse(String(init?.body))).toMatchObject({ accept: false, reason: "Équipe déjà engagée" });
});
it("ignores a late hospital response after switching", async () => {
  let release: (r: Response) => void = () => undefined;
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((url, init) => String(url).endsWith("X1/unit")
    ? new Promise<Response>(resolve => { release = resolve; }) : original(url, init));
  render(<App />);
  await waitFor(() => expect((screen.getByLabelText("Établissement") as HTMLSelectElement).value).toBe("X1"));
  fireEvent.change(screen.getByLabelText("Établissement"), { target: { value: "X2" } });
  await screen.findByText("Proposition · Hôpital X2");
  await act(async () => { release(response(view("X1"))); });
  expect(screen.queryByText("Proposition · Hôpital X1")).toBeNull();
});
it("does not fall back to fixture data when the backend is absent", async () => {
  vi.mocked(fetch).mockRejectedValue(new Error("offline")); render(<App />);
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: "Valider la proposition" })).toBeNull();
  expect(screen.queryByText("Patients fictifs, vrai planificateur")).toBeNull();
});
