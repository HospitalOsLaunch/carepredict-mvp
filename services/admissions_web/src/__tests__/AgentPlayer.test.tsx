import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import type { ConnectionOut, ReplayOut, ReplayStep } from "../api/types_agent";
import { AgentPlayer } from "../components/AgentPlayer";
import { AgentReplayPage } from "../pages/AgentReplayPage";
import { ComputerUsePage } from "../pages/ComputerUsePage";

vi.mock("../api/client", () => ({ api: vi.fn(), apiBlob: vi.fn() }));
const auth = { isAdmin: true, canWrite: true };
vi.mock("../auth", () => ({ useAuth: () => auth }));
import { api, apiBlob } from "../api/client";

const T0 = Date.parse("2026-11-02T08:00:00Z");

function step(seq: number, extra: Partial<ReplayStep> = {}): ReplayStep {
  return {
    id: 100 + seq,
    seq,
    at: new Date(T0 + seq * 1000).toISOString(),
    engine: "playbook",
    kind: "click",
    label: `Étape ${seq}`,
    target: "Mouvements du jour",
    pointer: null,
    box: null,
    outcome: "ok",
    duration_ms: 420,
    viewport: { w: 1000, h: 500 },
    masks: [],
    transmitted: null,
    has_frame: true,
    ...extra
  };
}

const STEPS: ReplayStep[] = [
  step(1, { kind: "login", label: "Saisit l'identifiant", masks: [{ x: 250, y: 100, w: 200, h: 50, reason: "secret" }] }),
  step(2, { kind: "navigate", label: "Ouvre la liste des mouvements du jour", pointer: { x: 500, y: 250 }, box: { x: 100, y: 50, w: 100, h: 25 } }),
  step(3, { kind: "wait", label: "Attend la page", has_frame: false, outcome: "info", engine: "open_light" }),
  step(4, {
    kind: "read",
    label: "Lit 12 mouvements",
    engine: "closed_fast",
    masks: [{ x: 0, y: 400, w: 500, h: 50, reason: "identite" }],
    transmitted: { count: 12, fields: ["uf", "lit"], applied: 11, duplicates: 1, rejected: 0 }
  }),
  step(5, { kind: "verify", label: "Relit le dossier pour vérifier la réponse : échec", outcome: "fail" })
];

function replay(extra: Partial<ReplayOut> = {}): ReplayOut {
  return {
    task: {
      id: 7,
      kind: "sync_movements",
      status: "done",
      engine_used: "playbook",
      created_at: new Date(T0).toISOString(),
      finished_at: new Date(T0 + 6000).toISOString(),
      connection_id: 2,
      connection_name: "Lits CH Sud",
      site_name: "CH Sud"
    },
    live: false,
    retention_until: "2026-11-09T08:00:00Z",
    steps: STEPS,
    ...extra
  };
}

let urlCount = 0;
beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(apiBlob).mockReset();
  // Frames never arrive unless a test serves them (withFrames), so no update lands after a test.
  vi.mocked(apiBlob).mockReturnValue(new Promise(() => undefined));
  Object.assign(auth, { isAdmin: true, canWrite: true });
  urlCount = 0;
  URL.createObjectURL = vi.fn(() => `blob:frame-${++urlCount}`);
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.useRealTimers());

const withFrames = () => vi.mocked(apiBlob).mockResolvedValue(new Blob(["jpeg"], { type: "image/jpeg" }));

function wrap(ui: React.ReactNode, path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}

const renderPlayer = (r: ReplayOut = replay()) => wrap(<AgentPlayer replay={r} />);
const renderPage = () =>
  wrap(
    <Routes>
      <Route path="/computer-use/passages/:taskId" element={<AgentReplayPage />} />
    </Routes>,
    "/computer-use/passages/7"
  );

const transcript = () => screen.getByRole("list", { name: "Transcription" });
const current = () => within(transcript()).getAllByRole("listitem").find((li) => li.getAttribute("aria-current") === "step");

describe("AgentPlayer", () => {
  it("shows the header, the steps and the transcript with engines, outcomes and what was sent", async () => {
    withFrames();
    vi.mocked(api).mockResolvedValue(replay() as never);
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: "Lits CH Sud" })).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/agent/tasks/7/replay");
    expect(screen.getByText("CH Sud")).toBeInTheDocument();
    expect(screen.getByText("Relever les mouvements")).toBeInTheDocument();
    expect(screen.getByText("Faite")).toBeInTheDocument();
    expect(screen.getByText("9 novembre")).toBeInTheDocument();
    expect(screen.getByText(/Conservé jusqu'au/)).toBeInTheDocument();

    const items = within(transcript()).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveAttribute("aria-current", "step");
    expect(items[0]).toHaveTextContent("Saisit l'identifiant");
    expect(items[0]).toHaveTextContent("script");
    expect(items[0]).toHaveTextContent("420 ms");
    expect(items[0]).toHaveTextContent("réussi");
    expect(items[2]).toHaveTextContent("modèle ouvert");
    expect(items[3]).toHaveTextContent("Claude");
    expect(items[3]).toHaveTextContent("transmis : 12 éléments (appliqués 11, doublons 1)");
    expect(items[3]).toHaveTextContent("champs : uf, lit");
    expect(items[4]).toHaveTextContent("échec");
    expect(await screen.findByRole("img", { name: /Écran à l'étape 1 : Saisit l'identifiant/ })).toHaveAttribute("src", "blob:frame-1");
    expect(screen.getAllByTestId("markers")[0].querySelectorAll("[data-outcome=fail]")).toHaveLength(1);
  });

  it("plays in real time between steps, faster at 2×, and stops at the end", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    renderPlayer();
    fireEvent.click(screen.getByRole("button", { name: "Lecture" }));
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(999));
    expect(current()).toHaveTextContent("Saisit l'identifiant");
    act(() => vi.advanceTimersByTime(1));
    expect(current()).toHaveTextContent("Ouvre la liste");

    fireEvent.click(screen.getByRole("button", { name: "2×" }));
    expect(screen.getByRole("button", { name: "2×" })).toHaveAttribute("aria-pressed", "true");
    act(() => vi.advanceTimersByTime(500));
    expect(current()).toHaveTextContent("Attend la page");
    act(() => vi.advanceTimersByTime(500));
    act(() => vi.advanceTimersByTime(500));
    expect(current()).toHaveTextContent("Relit le dossier");
    expect(screen.getByRole("button", { name: "Lecture" })).toBeInTheDocument();
  });

  it("caps a long pause between two steps", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    renderPlayer(replay({ steps: [step(1), step(2, { at: new Date(T0 + 60_000).toISOString() })] }));
    fireEvent.click(screen.getByRole("button", { name: "Lecture" }));
    act(() => vi.advanceTimersByTime(2500));
    expect(current()).toHaveTextContent("Étape 2");
  });

  it("moves step by step, image by image (skipping steps without image), and with the keyboard", () => {
    renderPlayer();
    fireEvent.click(screen.getByRole("button", { name: "Étape suivante" }));
    expect(current()).toHaveTextContent("Ouvre la liste");
    fireEvent.click(screen.getByRole("button", { name: "Image suivante" }));
    expect(current()).toHaveTextContent("Lit 12 mouvements");
    fireEvent.click(screen.getByRole("button", { name: "Étape précédente" }));
    expect(current()).toHaveTextContent("Attend la page");

    fireEvent.keyDown(document.body, { key: "ArrowLeft" });
    expect(current()).toHaveTextContent("Ouvre la liste");
    fireEvent.keyDown(document.body, { key: "ArrowRight", shiftKey: true });
    expect(current()).toHaveTextContent("Attend la page");
    fireEvent.keyDown(document.body, { key: " " });
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
  });

  it("seeks with the scrubber and by clicking a transcript line", () => {
    renderPlayer();
    const range = screen.getByRole("slider", { name: "Barre de temps" });
    fireEvent.change(range, { target: { value: "3" } });
    expect(current()).toHaveTextContent("Lit 12 mouvements");
    expect(range).toHaveAttribute("aria-valuetext", "Étape 4 sur 5 : Lit 12 mouvements");
    fireEvent.click(within(transcript()).getByRole("button", { name: /Saisit l'identifiant/ }));
    expect(current()).toHaveTextContent("Saisit l'identifiant");
  });

  it("draws the masks with their reason, the pointer and the box, scaled to the viewport", async () => {
    withFrames();
    renderPlayer();
    const mask = await screen.findByTitle("Masqué : mot de passe");
    expect(mask).toHaveStyle({ left: "25%", top: "20%", width: "20%", height: "10%" });
    expect(mask).toHaveTextContent("Masqué : mot de passe");

    fireEvent.click(screen.getByRole("button", { name: "Étape suivante" }));
    await waitFor(() => expect(screen.getByTestId("pointer")).toHaveStyle({ left: "50%", top: "50%" }));
    expect(screen.getByTestId("box")).toHaveStyle({ left: "10%", top: "10%", width: "10%", height: "5%" });

    fireEvent.change(screen.getByRole("slider"), { target: { value: "3" } });
    expect(await screen.findByTitle("Masqué : identité patient")).toHaveStyle({ left: "0%", top: "80%", width: "50%" });
  });

  it("prefetches the next frames, caches them by step and revokes them on unmount", async () => {
    withFrames();
    const view = renderPlayer();
    await screen.findByRole("img");
    // Current + the next 3 frames with an image (step 3 has none).
    await waitFor(() => expect(apiBlob).toHaveBeenCalledTimes(4));
    expect(apiBlob).toHaveBeenCalledWith("/agent/steps/101/frame");
    expect(apiBlob).toHaveBeenCalledWith("/agent/steps/105/frame");
    expect(apiBlob).not.toHaveBeenCalledWith("/agent/steps/103/frame");
    fireEvent.click(screen.getByRole("button", { name: "Étape suivante" }));
    fireEvent.click(screen.getByRole("button", { name: "Étape précédente" }));
    expect(apiBlob).toHaveBeenCalledTimes(4);

    view.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(4);
    for (let k = 1; k <= 4; k++) expect(URL.revokeObjectURL).toHaveBeenCalledWith(`blob:frame-${k}`);
  });

  it("explains a step without image", () => {
    renderPlayer();
    fireEvent.change(screen.getByRole("slider"), { target: { value: "2" } });
    expect(screen.getByText("Pas d'image pour cette étape : capture retenue pour protéger une zone")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("says when the script captures no screen at all", () => {
    renderPlayer(replay({ steps: STEPS.map((s) => ({ ...s, has_frame: false })) }));
    expect(screen.getByText("Ce script ne capture pas d'écran")).toBeInTheDocument();
    expect(apiBlob).not.toHaveBeenCalled();
  });

  it("follows a live task: polls with after_seq every second and appends the new steps", async () => {
    let calls = 0;
    vi.mocked(api).mockImplementation(async (path: string) => {
      calls += 1;
      if (path === "/agent/tasks/7/replay") return replay({ live: true, steps: STEPS.slice(0, 2), task: { ...replay().task, status: "running", finished_at: null } }) as never;
      if (path === "/agent/tasks/7/replay?after_seq=2") return replay({ live: true, steps: [STEPS[2]] }) as never;
      if (path === "/agent/tasks/7/replay?after_seq=3") return replay({ live: false, steps: [] }) as never;
      throw new Error(`unexpected ${path}`);
    });
    renderPage();
    const live = await screen.findByRole("button", { name: /En direct/ });
    expect(live).toHaveAttribute("aria-pressed", "true");
    expect(transcript()).toHaveAttribute("aria-live", "polite");
    expect(current()).toHaveTextContent("Ouvre la liste");

    await waitFor(() => expect(within(transcript()).getAllByRole("listitem")).toHaveLength(3), { timeout: 2500 });
    expect(api).toHaveBeenCalledWith("/agent/tasks/7/replay?after_seq=2");
    expect(current()).toHaveTextContent("Attend la page");

    await waitFor(() => expect(api).toHaveBeenCalledWith("/agent/tasks/7/replay?after_seq=3"), { timeout: 2500 });
    await waitFor(() => expect(screen.queryByRole("button", { name: /En direct/ })).not.toBeInTheDocument());
    const settled = calls;
    await new Promise((r) => setTimeout(r, 1300));
    expect(calls).toBe(settled);
  }, 10_000);

  it("leaves the live head when the user navigates, and comes back with « En direct »", () => {
    renderPlayer(replay({ live: true }));
    expect(current()).toHaveTextContent("Relit le dossier");
    fireEvent.click(screen.getByRole("button", { name: "Étape précédente" }));
    expect(screen.getByRole("button", { name: /En direct/ })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: /En direct/ }));
    expect(current()).toHaveTextContent("Relit le dossier");
  });

  it("tells the direction the player is reserved, without asking the API", () => {
    Object.assign(auth, { isAdmin: false, canWrite: false });
    renderPage();
    expect(screen.getByRole("heading", { name: "Player réservé" })).toBeInTheDocument();
    expect(api).not.toHaveBeenCalled();
  });

  it("explains a purged replay", async () => {
    vi.mocked(api).mockRejectedValue(Object.assign(new Error("Introuvable"), { status: 404 }));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(/durée de conservation/);
  });
});

describe("entry points on the computer use page", () => {
  function connection(extra: Partial<ConnectionOut>): ConnectionOut {
    return {
      id: 2,
      name: "Lits CH Sud",
      kind: "gestion_lits",
      site_id: 2,
      site_name: "CH Sud",
      url: "https://lits.exemple.fr",
      allowed_hosts: [],
      username: "lits",
      secret_set: true,
      secret_updated_at: null,
      playbook: "bedsoft",
      tasks: ["sync_movements"],
      source_system: null,
      interval_minutes: 15,
      active_from: null,
      active_to: null,
      days: null,
      agent_id: null,
      status: "active",
      last_run_at: null,
      next_run_at: null,
      last_outcome: null,
      last_error: null,
      pending_tasks: 0,
      needs_human: 0,
      can_control: true,
      can_edit: true,
      running_task_id: null,
      ...extra
    };
  }
  const run = (id: number, extra: object) => ({
    id,
    kind: "sync_movements",
    status: "done",
    attempts: 1,
    engine_used: "playbook",
    cost_usd: 0,
    error: null,
    request_id: null,
    created_at: new Date(T0).toISOString(),
    updated_at: new Date(T0).toISOString(),
    finished_at: new Date(T0).toISOString(),
    has_replay: false,
    steps_count: 0,
    ...extra
  });

  function mock(list: ConnectionOut[]) {
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "/agent/status") return { paused: false } as never;
      if (path === "/agent/workers") return [] as never;
      if (path === "/agent/connections") return list as never;
      if (path.endsWith("/runs?limit=20")) return [run(40, { has_replay: true, steps_count: 12 }), run(41, {})] as never;
      throw new Error(`unexpected ${path}`);
    });
  }

  it("offers « Regarder en direct » only while a task runs", async () => {
    mock([connection({ running_task_id: 55 }), connection({ id: 3, name: "Lits CH Nord" })]);
    wrap(<ComputerUsePage />);
    const running = await screen.findByRole("article", { name: "Lits CH Sud" });
    const link = within(running).getByRole("link", { name: /Regarder en direct/ });
    expect(link).toHaveAttribute("href", "/computer-use/passages/55");
    expect(link).toHaveTextContent("En direct");
    expect(within(screen.getByRole("article", { name: "Lits CH Nord" })).queryByRole("link", { name: /Regarder/ })).not.toBeInTheDocument();
  });

  it("offers « Revoir » only for runs with a replay", async () => {
    mock([connection({})]);
    wrap(<ComputerUsePage />);
    const card = await screen.findByRole("article", { name: "Lits CH Sud" });
    await userEvent.click(within(card).getByRole("button", { name: /Passages/ }));
    const runs = await within(card).findByRole("list", { name: "Derniers passages" });
    const links = within(runs).getAllByRole("link", { name: /Revoir/ });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/computer-use/passages/40");
    expect(links[0]).toHaveAccessibleName("Revoir ce passage (12 étapes)");
  });

  it("hides the player entries from the direction", async () => {
    Object.assign(auth, { isAdmin: false, canWrite: false });
    mock([connection({ running_task_id: 55, can_control: false, can_edit: false })]);
    wrap(<ComputerUsePage />);
    const card = await screen.findByRole("article", { name: "Lits CH Sud" });
    expect(within(card).queryByRole("link", { name: /Regarder/ })).not.toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: /Passages/ }));
    await within(card).findByRole("list", { name: "Derniers passages" });
    expect(within(card).queryByRole("link", { name: /Revoir/ })).not.toBeInTheDocument();
  });
});
