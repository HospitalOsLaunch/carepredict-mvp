import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ComparisonPanel } from "./ui/Comparison";
import { compareEpisodes, type ComparisonResult } from "./api/comparison";
import fixture from "./test/dynamic-comparison.json";

let result: ComparisonResult;
const response = (value: unknown, status = 200) => ({
  ok: status < 400, status, statusText: "test", json: async () => value,
}) as Response;

beforeEach(() => {
  result = structuredClone(fixture) as ComparisonResult;
  vi.stubGlobal("fetch", vi.fn(async () => response(result)));
});

function start() {
  render(<ComparisonPanel />);
  fireEvent.change(screen.getByLabelText("Durée simulée"), { target: { value: "60" } });
  fireEvent.click(screen.getByRole("button", { name: "Comparer" }));
}

it("runs a paired comparison, displays measured results and sends only its configuration", async () => {
  start();
  await screen.findByText("5 minutes-patients d'attente en moins");
  expect(screen.getByRole("table").textContent).toContain("67");
  expect(screen.getByRole("table").textContent).toContain("62");
  expect(fetch).toHaveBeenCalledTimes(1);
  const [url, init] = vi.mocked(fetch).mock.calls[0]!;
  expect(String(url)).toBe("/api/demo/compare");
  expect(JSON.parse(String(init?.body))).toEqual({ seed: 7, horizon_minutes: 60, policy: "accept" });
  expect(screen.getByText(/attentes encore en cours/)).toBeTruthy();
});

it("keeps negative results visible and clears results when settings change", async () => {
  result.waiting_patient_minutes_saved = -5;
  result.waiting_patient_hours_saved = -5 / 60;
  start();
  await screen.findByText("5 minutes-patients d'attente en plus");
  fireEvent.change(screen.getByLabelText("Graine du scénario"), { target: { value: "8" } });
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByRole("button", { name: /Exporter/ })).toBeNull();
});

it("does not turn a zero effect into an improvement and shows the neutrality control", async () => {
  result.manifest.config.policy = "disabled";
  result.waiting_patient_minutes_saved = 0;
  result.physical_trajectories_identical = true;
  render(<ComparisonPanel />);
  fireEvent.change(screen.getByLabelText("Durée simulée"), { target: { value: "60" } });
  fireEvent.change(screen.getByLabelText("Réponse aux recommandations en A1"), { target: { value: "disabled" } });
  fireEvent.click(screen.getByRole("button", { name: "Comparer" }));
  await screen.findByText("Aucune différence d'attente cumulée");
  expect(screen.getByText("Contrôle de neutralité : trajectoires physiques identiques.")).toBeTruthy();
});

it("prevents duplicate requests while the pair is running", async () => {
  let release: (value: Response) => void = () => { throw new Error("request missing"); };
  vi.mocked(fetch).mockImplementation(() => new Promise<Response>((resolve) => { release = resolve; }));
  start();
  const button = screen.getByRole("button", { name: "Comparaison en cours…" });
  fireEvent.click(button);
  expect((screen.getByLabelText("Graine du scénario") as HTMLInputElement).closest("fieldset")?.disabled).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(1);
  await act(async () => { release(response(result)); });
  await screen.findByRole("button", { name: /Exporter/ });
});

it.each([429, 503])("shows HTTP %s without substituting results", async (status) => {
  vi.mocked(fetch).mockResolvedValue(response({ detail: "unavailable" }, status));
  start();
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toMatch(status === 429 ? /déjà en cours/ : /Aucun résultat de remplacement/);
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByRole("button", { name: /Exporter/ })).toBeNull();
});

it("identifies a missing comparison endpoint after a frontend-only update", async () => {
  vi.mocked(fetch).mockResolvedValue(response({ detail: "Not Found" }, 404));
  start();
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toMatch(/HTTP 404/);
  expect(alert.textContent).toMatch(/ancien backend/);
  expect(alert.textContent).toMatch(/Ctrl\+C/);
  expect(screen.queryByRole("table")).toBeNull();
});

it("reports a backend exception without mislabeling it as a lost connection", async () => {
  vi.mocked(fetch).mockResolvedValue(response({ detail: "Internal Server Error" }, 500));
  start();
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toMatch(/erreur interne \(HTTP 500\)/);
  expect(alert.textContent).toMatch(/POST \/demo\/compare/);
  expect(screen.queryByRole("table")).toBeNull();
});

it("explains a client timeout without claiming that the server calculation stopped", async () => {
  vi.mocked(fetch).mockRejectedValue(new DOMException("aborted", "AbortError"));
  start();
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toMatch(/120 secondes/);
  expect(alert.textContent).toMatch(/peut encore terminer/);
  expect(screen.queryByRole("table")).toBeNull();
});

it("rejects an obsolete schema or a response for another configuration", async () => {
  const config = { seed: 7, horizon_minutes: 60, policy: "accept" as const };
  vi.mocked(fetch).mockResolvedValue(response({ ...result, schema_version: "old" }));
  await expect(compareEpisodes(config)).rejects.toThrow(/Unsupported/);
  result.manifest.config.seed = 8;
  vi.mocked(fetch).mockResolvedValue(response(result));
  await expect(compareEpisodes(config)).rejects.toThrow(/mismatched/);
});

it("downloads the complete received result including journals and provenance", async () => {
  const create = vi.fn((_blob: Blob) => "blob:comparison");
  const original = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL = create;
  URL.revokeObjectURL = vi.fn();
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  try {
    start();
    fireEvent.click(await screen.findByRole("button", { name: "Exporter la comparaison (JSON)" }));
    const blob = create.mock.calls[0]?.[0] as Blob | undefined;
    expect(blob).toBeInstanceOf(Blob);
    const exported = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob!);
    });
    expect(JSON.parse(exported)).toEqual(result);
    expect(click).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.getByRole("button", { name: "Comparer" })).toBeTruthy());
  } finally {
    click.mockRestore();
    URL.createObjectURL = original;
    // The browser's delayed cleanup can run after this test.
    URL.revokeObjectURL = originalRevoke ?? (() => undefined);
  }
});
