import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App } from "../App";
import { type DsFixture, pointer } from "../api/decision";
import { journal } from "../data/journal";
import fixtureData from "../fixtures/decision.json";

const FX = fixtureData as unknown as DsFixture;
const docs = new Map<string, unknown>(
  [...FX.units, ...FX.manual].map((u) => [u.recommendation.recommendation_id, u.recommendation]),
);

/** T32: every figure resolves, through its pointer, to the engine document it cites. */
function auditFigures(container: HTMLElement): number {
  const nodes = [...container.querySelectorAll<HTMLElement>("[data-src]")];
  for (const n of nodes) {
    const [doc, ptr] = n.dataset.src!.split("#");
    expect(docs.has(doc!)).toBe(true);
    expect(JSON.stringify(pointer(docs.get(doc!), ptr!) ?? null)).toBe(n.dataset.raw);
  }
  for (const cell of container.querySelectorAll<HTMLElement>(".ds-fig b, td.r")) {
    const clone = cell.cloneNode(true) as HTMLElement;
    clone.querySelectorAll("[data-src]").forEach((s) => s.remove());
    expect(clone.textContent).not.toMatch(/\d/);
  }
  return nodes.length;
}

const status = async (scope: HTMLElement, expected: string) =>
  waitFor(() => expect(within(scope).getAllByTestId("ds-status")[0]!.dataset.status).toBe(expected));

beforeEach(() => {
  window.localStorage.clear();
  journal.reset();
  vi.stubGlobal("scrollTo", vi.fn());
  HTMLDialogElement.prototype.showModal = vi.fn();
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  window.history.replaceState(null, "", "/?situation=nominal");
  window.location.hash = "/plan";
});

describe("plan à 24 h (moteur d'aide à la décision)", () => {
  it("opens on the automatic recommendation, without any scenario typed", async () => {
    const { container } = render(<App />);
    const auto = await screen.findByTestId("ds-auto");
    await status(auto, "RECOMMENDATION_READY");
    expect(screen.queryByTestId("ds-manual-form")).toBeNull();
    expect(within(auto).getAllByRole("listitem").length).toBeGreaterThan(0);
    expect(screen.getByTestId("ds-conditional")).toBeTruthy(); // R1 requested, not confirmed
    expect(screen.getByTestId("ds-source").textContent).toMatch(/sans API locale/);
    expect(auditFigures(container)).toBeGreaterThan(10);
    expect(screen.getByTestId("ds-provenance").textContent).toMatch(/PROTOTYPE_UNVALIDATED.*G2 NO-GO/);
  });

  it("approves in demonstration only and sends nothing", async () => {
    render(<App />);
    await status(await screen.findByTestId("ds-auto"), "RECOMMENDATION_READY");
    fireEvent.click(screen.getByTestId("ds-approve"));
    const feedback = await screen.findByTestId("ds-feedback");
    expect(feedback.dataset.outcome).toBe("APPROVED_IN_DEMO");
    expect(feedback.textContent).toMatch(/Aucune commande/);
  });

  it("offline manual mode shows engine-computed scenarios; a hypothesis is never approvable", async () => {
    const { container } = render(<App />);
    await status(await screen.findByTestId("ds-auto"), "RECOMMENDATION_READY");
    fireEvent.click(screen.getByTestId("ds-modify"));
    const examples = await screen.findByTestId("ds-examples");
    fireEvent.click(within(examples).getByRole("button", { name: /X1 sortie 10:00/ }));
    const manual = await screen.findByTestId("ds-manual");
    expect(within(manual).getAllByText("verrouillé")).toHaveLength(2);
    expect(within(screen.getByTestId("ds-branches")).getAllByRole("row")).toHaveLength(4);
    auditFigures(container);
    fireEvent.click(within(examples).getByRole("button", { name: /Hypothèse/ }));
    await status(screen.getByTestId("ds-manual"), "HYPOTHETICAL_ONLY");
    expect((within(screen.getByTestId("ds-manual")).getByTestId("ds-approve") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(examples).getByRole("button", { name: /16:00/ }));
    await status(screen.getByTestId("ds-manual"), "INFEASIBLE");
    expect(screen.getByTestId("ds-manual-diagnostics").textContent).toMatch(/locked_transport_unavailable/);
  });

  it("abstains with explicit diagnostics, and keeps habitual practice when nothing helps", async () => {
    render(<App />);
    await status(await screen.findByTestId("ds-auto"), "RECOMMENDATION_READY");
    fireEvent.change(screen.getByTestId("ds-unit"), { target: { value: "insufficient_data" } });
    await status(await screen.findByTestId("ds-auto"), "INSUFFICIENT_DATA");
    expect(screen.getByTestId("ds-diagnostics").textContent).toMatch(/roster_unknown:IDE/);
    fireEvent.change(screen.getByTestId("ds-unit"), { target: { value: "no_action" } });
    await status(await screen.findByTestId("ds-auto"), "NO_ACTION_PREFERRED");
    expect(screen.getByRole("heading", { name: "Maintenir la pratique habituelle" })).toBeTruthy();
  });

  it("with the local engine API, posts the X1/X2 locks to the same engine", async () => {
    const unit = FX.units[0]!;
    const x1x2 = FX.manual.find((m) => m.id === "x1x2")!;
    const calls: Array<{ url: string; body: unknown }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (!String(url).startsWith("/api/decision")) throw new TypeError("offline");
        calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
        const json = (body: unknown) => ({ ok: true, json: async () => body });
        if (url.endsWith("/units")) return json({ units: FX.units.map(({ id, name }) => ({ id, name })), events: [] });
        if (url.includes("/auto"))
          return json({ doc_id: unit.recommendation.recommendation_id, snapshot: unit.snapshot, recommendation: unit.recommendation });
        if (url.endsWith("/simulate"))
          return json({ doc_id: x1x2.recommendation.recommendation_id, recommendation: x1x2.recommendation });
        throw new Error(`unexpected ${url}`);
      }),
    );
    render(<App />);
    await status(await screen.findByTestId("ds-auto"), "RECOMMENDATION_READY");
    expect(screen.queryByTestId("ds-source")).toBeNull();
    fireEvent.click(screen.getByTestId("ds-modify"));
    const form = await screen.findByTestId("ds-manual-form");
    expect((form.querySelector("select[name=x1]") as HTMLSelectElement).value).toBe("S01");
    fireEvent.click(within(form).getByTestId("ds-run-manual"));
    await screen.findByTestId("ds-manual");
    const sent = calls.find((c) => c.url.endsWith("/simulate"))!.body as { locks: { locks: Array<Record<string, unknown>> } };
    expect(sent.locks.locks[0]).toMatchObject({ kind: "discharge_at", stay_id: "S01", at: "2026-11-17T09:00:00+00:00" });
    expect(sent.locks.locks[1]).toMatchObject({ kind: "extend_presence", stay_id: "S02", extension_hours: 4 });
  });

  it("shows an idempotency conflict from the engine instead of a borrowed success", async () => {
    const unit = FX.units[0]!;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (!String(url).startsWith("/api/decision")) throw new TypeError("offline");
        const json = (body: unknown, ok = true) => ({ ok, statusText: "Conflict", json: async () => body });
        if (url.endsWith("/units")) return json({ units: FX.units.map(({ id, name }) => ({ id, name })), events: [] });
        if (url.includes("/auto"))
          return json({ doc_id: unit.recommendation.recommendation_id, snapshot: unit.snapshot, recommendation: unit.recommendation });
        if (url.endsWith("/review")) return json({ error: "idempotency key already used for another request" }, false);
        throw new Error(`unexpected ${url}`);
      }),
    );
    render(<App />);
    await status(await screen.findByTestId("ds-auto"), "RECOMMENDATION_READY");
    fireEvent.click(screen.getByTestId("ds-approve"));
    expect((await screen.findByTestId("ds-conflict")).textContent).toMatch(/idempotency key already used/);
    expect(screen.queryByTestId("ds-feedback")).toBeNull();
  });
});
