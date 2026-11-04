import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import type { AgentPolicy, AgentStatus, EnginePolicy } from "../api/types";
import type { WorkerOut } from "../api/types_agent";
import { changes, readiness, routeSentence } from "../lib/engines";
import { EnginesSection } from "../pages/AgentEngines";

vi.mock("../api/client", () => ({ api: vi.fn() }));
import { api } from "../api/client";

const engine = (label: string, kind: EnginePolicy["kind"], extra: Partial<EnginePolicy> = {}): EnginePolicy => ({
  label,
  kind,
  enabled: false,
  model: null,
  open_weights: kind === "openai_compatible",
  identifiable_data_allowed: false,
  identifiable_basis: null,
  identifiable_reference: null,
  input_usd_per_mtok: 0,
  output_usd_per_mtok: 0,
  usd_per_hour: 0,
  min_calibration: kind === "openai_compatible" ? 0.9 : null,
  ...extra
});

function policy(): AgentPolicy {
  return {
    engines: {
      playbook: engine("Script déterministe (Playwright)", "playbook", { enabled: true, identifiable_data_allowed: true }),
      open_light: engine("Open source léger (Holo4-35B-A3B, auto-hébergé)", "openai_compatible", { model: "Hcompany/Holo4-35B-A3B" }),
      open_heavy: engine("Open source puissant (MiMo-V2.6-Flash, auto-hébergé)", "openai_compatible"),
      closed_fast: engine("Claude Sonnet 5.5 (computer use)", "anthropic", { model: "claude-sonnet-5-5", input_usd_per_mtok: 2, output_usd_per_mtok: 10 }),
      closed_best: engine("Claude Opus 5.5 (computer use)", "anthropic", { model: "claude-opus-5-5", input_usd_per_mtok: 4, output_usd_per_mtok: 20 })
    },
    routes: {
      sync_inbox: ["playbook", "open_light", "closed_fast"],
      reply_portal: ["playbook", "open_heavy", "closed_best"],
      sync_movements: ["playbook"]
    },
    daily_budget_usd: 20,
    task_budget_usd: { sync_inbox: 0.5, reply_portal: 1 },
    sync_interval_minutes: 10,
    max_attempts: 3,
    write_requires_verification: true
  };
}

const worker = (configured: string[], online = true): WorkerOut => ({
  agent_id: "poste-smr-1",
  site_id: null,
  online,
  last_heartbeat_at: "2026-11-04T10:00:00Z",
  version: "0.2.0",
  engines: ["playbook", "open_light", "open_heavy", "closed_fast", "closed_best"].map((name) => ({
    name,
    configured: configured.includes(name),
    detail: configured.includes(name) ? null : name.startsWith("closed") ? "ANTHROPIC_API_KEY absente" : "point d'accès non renseigné"
  })),
  playbooks: [
    { name: "demo_portal", label: "Portail", kind: "portail_orientation", tasks: ["sync_inbox", "reply_portal"] },
    { name: "demo_bedsoft", label: "Lits", kind: "gestion_lits", tasks: ["sync_movements"] }
  ]
});

const ctx = { calibrations: {}, spent_today_usd: 0 };

describe("what the agent will do with each engine", () => {
  it("gives the router's reason, and the fix, for an engine that will be skipped", () => {
    const p = policy();
    const workers = [worker(["playbook"])];
    expect(readiness("playbook", "sync_inbox", p, workers, ctx)).toEqual({ ready: true });
    expect(readiness("closed_fast", "sync_inbox", p, workers, ctx)).toMatchObject({ ready: false, reason: "désactivé" });

    p.engines.closed_fast.enabled = true;
    expect(readiness("closed_fast", "sync_inbox", p, workers, ctx)).toMatchObject({
      reason: "non configuré sur les postes",
      fix: "Sur le poste : ANTHROPIC_API_KEY."
    });
    const withKey = [worker(["playbook", "closed_fast", "open_light"])];
    expect(readiness("closed_fast", "sync_inbox", p, withKey, ctx)).toMatchObject({ reason: "pas autorisé à voir des données identifiantes" });

    p.engines.closed_fast.identifiable_data_allowed = true;
    expect(readiness("closed_fast", "sync_inbox", p, withKey, ctx)).toEqual({ ready: true });
    expect(readiness("closed_fast", "sync_movements", p, withKey, ctx)).toMatchObject({ reason: "relève des mouvements réservée au script" });
    expect(readiness("closed_fast", "sync_inbox", p, withKey, { ...ctx, spent_today_usd: 20 })).toMatchObject({ reason: "plafond du jour atteint" });
    expect(readiness("closed_fast", "sync_inbox", p, [worker(["closed_fast"], false)], ctx)).toMatchObject({ reason: "aucun poste en ligne" });

    p.engines.open_light = { ...p.engines.open_light, enabled: true, identifiable_data_allowed: true };
    expect(readiness("open_light", "sync_inbox", p, withKey, ctx)).toMatchObject({ reason: "jamais calibré" });
    const calibrated = { ...ctx, calibrations: { open_light: { model: "m", hit_rate: 0.82, trials: 20, at: "", convention: null } } };
    expect(readiness("open_light", "sync_inbox", p, withKey, calibrated)).toMatchObject({ reason: "calibration insuffisante (82 % < 90 %)" });
  });

  it("says in one sentence what will run for each task", () => {
    const p = policy();
    expect(routeSentence("sync_inbox", p, [worker(["playbook"])], ctx)).toBe("Le script seulement.");
    p.engines.closed_fast = { ...p.engines.closed_fast, enabled: true, identifiable_data_allowed: true, identifiable_basis: "contrat" };
    expect(routeSentence("sync_inbox", p, [worker(["playbook", "closed_fast"])], ctx)).toBe("Le script, puis Claude Sonnet 5.5 si l'écran a changé.");
    expect(routeSentence("sync_inbox", p, [], ctx)).toBe("Rien ne tournera : aucun moteur de cette route n'est prêt.");
  });

  it("lists every change in plain words", () => {
    const saved = policy();
    const draft = policy();
    draft.engines.closed_fast = { ...draft.engines.closed_fast, enabled: true, identifiable_data_allowed: true, identifiable_basis: "hds" };
    draft.routes.reply_portal = ["playbook", "closed_best"];
    draft.daily_budget_usd = 5;
    expect(changes(saved, draft)).toEqual([
      "Claude Sonnet 5.5 : activé",
      "Claude Sonnet 5.5 : peut voir des données identifiantes (hébergement certifié HDS)",
      "Reporter la réponse sur le portail : Le script → Claude Opus 5.5",
      "Plafond du jour : 5,00 $"
    ]);
  });
});

function renderSection(canEdit: boolean, p = policy(), workers = [worker(["playbook"])]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const status = { policy: p, calibrations: {}, spent_today_usd: 0.4, spend_30d: [{ engine: "playbook", attempts: 12, successes: 12, cost_usd: 0 }] } as Pick<
    AgentStatus,
    "policy" | "calibrations" | "spent_today_usd" | "spend_30d"
  >;
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <EnginesSection status={status} workers={workers} loading={false} canEdit={canEdit} />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("EnginesSection", () => {
  beforeEach(() => vi.mocked(api).mockReset());

  it("shows each task's route, each engine's state on the workers, and is read-only for the teams", () => {
    renderSection(false);
    expect(screen.getByTestId("route-sentence-sync_inbox")).toHaveTextContent("Le script seulement.");
    expect(screen.getByTestId("route-sentence-sync_movements")).toHaveTextContent("Le script seulement.");
    const sonnet = screen.getByRole("listitem", { name: "Claude Sonnet 5.5 (computer use)" });
    expect(within(sonnet).getByText(/ANTHROPIC_API_KEY absente/)).toBeInTheDocument();
    expect(within(sonnet).getByText("Désactivé")).toBeInTheDocument();
    expect(within(sonnet).getByRole("switch", { name: "Activé" })).toBeDisabled();
    expect(screen.getByText(/réglé par l'administrateur du groupe/)).toBeInTheDocument();
    // Movements stay with the script: no engine to add there.
    const movements = screen.getByRole("article", { name: "Relever les mouvements du logiciel de lits" });
    expect(within(movements).queryByLabelText("Ajouter un moteur")).not.toBeInTheDocument();
    expect(within(movements).getByText(/aucun modèle ne sait encore lire cet écran/)).toBeInTheDocument();
  });

  it("asks on what basis a model may see identifiable screens, then saves it with the rest", async () => {
    vi.mocked(api).mockImplementation((async (_path: string, init?: { json?: AgentPolicy }) => init?.json) as never);
    renderSection(true);
    const sonnet = screen.getByRole("listitem", { name: "Claude Sonnet 5.5 (computer use)" });
    await userEvent.click(within(sonnet).getByRole("switch", { name: "Activé" }));
    await userEvent.click(within(sonnet).getByRole("switch", { name: "Peut voir des écrans avec des données identifiantes" }));

    const dialog = await screen.findByRole("dialog");
    const authorize = within(dialog).getByRole("button", { name: "Autoriser" });
    expect(authorize).toBeDisabled();
    await userEvent.click(within(dialog).getByLabelText("Contrat couvrant les données de santé"));
    expect(authorize).toBeDisabled(); // the contract's reference is required
    await userEvent.type(within(dialog).getByLabelText("Référence du contrat ou de l'avenant"), "CT-2026-14");
    await userEvent.click(authorize);

    const bar = screen.getByRole("region", { name: "Changements à enregistrer" });
    expect(within(bar).getByText("2 changements pas encore enregistrés")).toBeInTheDocument();
    expect(within(bar).getByText("Claude Sonnet 5.5 : peut voir des données identifiantes (contrat couvrant les données de santé)")).toBeInTheDocument();
    expect(api).not.toHaveBeenCalled(); // nothing applied before « Enregistrer »

    await userEvent.click(within(bar).getByRole("button", { name: "Enregistrer" }));
    const [path, init] = vi.mocked(api).mock.calls[0] as [string, { method: string; json: AgentPolicy }];
    expect(path).toBe("/agent/policy");
    expect(init.method).toBe("PUT");
    expect(init.json.engines.closed_fast).toMatchObject({
      enabled: true,
      identifiable_data_allowed: true,
      identifiable_basis: "contrat",
      identifiable_reference: "CT-2026-14"
    });
    expect(await screen.findByText(/Enregistré : 2 changements/)).toBeInTheDocument();
  });

  it("applies a preset to the order only, and cancels back to what is saved", async () => {
    renderSection(true);
    await userEvent.click(screen.getByRole("button", { name: "Fiabilité" }));
    const bar = screen.getByRole("region", { name: "Changements à enregistrer" });
    expect(within(bar).getByText("Relever les demandes du portail : Le script → Claude Sonnet 5.5 → Claude Opus 5.5")).toBeInTheDocument();
    // The engines are not switched on behind the administrator's back.
    expect(within(bar).queryByText(/activé/)).not.toBeInTheDocument();
    const inbox = screen.getByRole("article", { name: "Relever les demandes du portail" });
    expect(within(inbox).getAllByText("désactivé").length).toBeGreaterThan(0);

    await userEvent.click(within(bar).getByRole("button", { name: "Annuler" }));
    expect(screen.queryByRole("region", { name: "Changements à enregistrer" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Économie" })).toHaveAttribute("aria-pressed", "true");
  });
});
