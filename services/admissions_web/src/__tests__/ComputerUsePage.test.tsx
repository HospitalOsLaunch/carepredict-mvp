import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import type { ConnectionOut, WorkerOut } from "../api/types_agent";
import { ComputerUsePage } from "../pages/ComputerUsePage";

vi.mock("../api/client", () => ({ api: vi.fn() }));
const auth = { isAdmin: true, canWrite: true };
vi.mock("../auth", () => ({ useAuth: () => auth }));
import { api } from "../api/client";

const recent = (minutes: number) => new Date(Date.now() + minutes * 60_000).toISOString();

const workers: WorkerOut[] = [
  {
    agent_id: "poste-accueil",
    site_id: 1,
    online: true,
    last_heartbeat_at: recent(-1),
    version: "2.4.0",
    engines: [
      { name: "playbook", configured: true, detail: null },
      { name: "closed_fast", configured: false, detail: "clé absente" }
    ],
    playbooks: [
      { name: "trajectoire", label: "Trajectoire régional", kind: "portail_orientation", tasks: ["sync_inbox", "reply_portal"] },
      { name: "bedsoft", label: "BedSoft", kind: "gestion_lits", tasks: ["sync_movements"] }
    ]
  },
  {
    agent_id: "poste-nuit",
    site_id: null,
    online: false,
    last_heartbeat_at: recent(-180),
    version: "2.3.1",
    engines: [],
    playbooks: [{ name: "trajectoire", label: "Trajectoire régional", kind: "portail_orientation", tasks: ["sync_inbox"] }]
  }
];

function connection(extra: Partial<ConnectionOut> = {}): ConnectionOut {
  return {
    id: 1,
    name: "Portail Nord",
    kind: "portail_orientation",
    site_id: 1,
    site_name: "SMR Les Tilleuls",
    url: "https://portail.exemple.fr",
    allowed_hosts: ["portail.exemple.fr", "sso.exemple.fr"],
    username: "smr.tilleuls",
    secret_set: true,
    secret_updated_at: "2026-10-30T09:00:00Z",
    playbook: "trajectoire",
    tasks: ["sync_inbox", "reply_portal"],
    source_system: null,
    interval_minutes: 15,
    active_from: "07:00",
    active_to: "20:00",
    days: [1, 2, 3, 4, 5],
    agent_id: null,
    status: "active",
    last_run_at: recent(-4),
    next_run_at: recent(11),
    last_outcome: "failure",
    last_error: "Écran de connexion inattendu après la saisie de l'identifiant",
    pending_tasks: 1,
    needs_human: 2,
    can_control: true,
    can_edit: true,
    running_task_id: null,
    ...extra
  };
}

const connections = [
  connection(),
  connection({
    id: 2,
    name: "Lits CH Sud",
    kind: "gestion_lits",
    site_name: "CH Sud",
    playbook: "bedsoft",
    tasks: ["sync_movements"],
    status: "arretee",
    last_error: null,
    last_outcome: null,
    needs_human: 0
  }),
  connection({ id: 3, name: "Portail Est", status: "en_pause", last_error: null, needs_human: 0 })
];

let paused = false;
let list: ConnectionOut[] = connections;
let workerList: WorkerOut[] = workers;

function mockApi() {
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit & { json?: unknown }) => {
    if (path === "/agent/status") return { paused, online: true } as never;
    if (path === "/agent/workers") return workerList as never;
    if (path === "/agent/connections" && !init?.method) return list as never;
    if (path === "/sites") return [{ id: 1, name: "SMR Les Tilleuls" }, { id: 2, name: "CH Sud" }] as never;
    if (path.endsWith("/runs?limit=20"))
      return [
        { id: 40, kind: "sync_inbox", status: "needs_human", attempts: 3, engine_used: "playbook", cost_usd: 0, error: "Page introuvable", request_id: null, created_at: recent(-30), updated_at: recent(-20), finished_at: null }
      ] as never;
    if (init?.method) return {} as never;
    throw new Error(`unexpected ${path}`);
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ComputerUsePage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const card = (name: string) => screen.findByRole("article", { name });
const calls = (method: string) =>
  vi.mocked(api).mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === method);
const lastBody = (method: string) => (calls(method).at(-1)?.[1] as { json: Record<string, unknown> }).json;

beforeEach(() => {
  vi.mocked(api).mockReset();
  Object.assign(auth, { isAdmin: true, canWrite: true });
  paused = false;
  list = connections;
  workerList = workers;
  mockApi();
});

describe("ComputerUsePage", () => {
  it("shows the workers and one card per connection", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "poste-accueil" })).toBeInTheDocument();
    expect(screen.getByText("En ligne")).toBeInTheDocument();
    expect(screen.getByText("Hors ligne")).toBeInTheDocument();
    expect(screen.getByText("v2.4.0")).toBeInTheDocument();
    expect(screen.getAllByText("BedSoft")[0]).toBeInTheDocument();
    expect(screen.getByText(/1 poste en ligne sur 2/)).toBeInTheDocument();

    const nord = await card("Portail Nord");
    expect(within(nord).getByText(/SMR Les Tilleuls · Portail d'orientation/)).toBeInTheDocument();
    expect(within(nord).getByText("Active")).toBeInTheDocument();
    expect(within(nord).getByText(/Écran de connexion inattendu/)).toBeInTheDocument();
    expect(within(nord).getByText("il y a 4 minutes")).toBeInTheDocument();
    expect(within(nord).getByText("en échec")).toBeInTheDocument();
    expect(within(nord).getByText(/de 07:00 à 20:00, lun\. mar\. mer\. jeu\. ven\./)).toBeInTheDocument();
    expect(within(await card("Lits CH Sud")).getByText(/Logiciel de gestion des lits/)).toBeInTheDocument();
    expect(within(await card("Lits CH Sud")).getByText("Arrêtée")).toBeInTheDocument();
    expect(within(await card("Portail Est")).getByText("En pause")).toBeInTheDocument();
  });

  it("calls the right endpoint for each command and announces it", async () => {
    renderPage();
    await userEvent.click(within(await card("Lits CH Sud")).getByRole("button", { name: "Démarrer" }));
    expect(api).toHaveBeenCalledWith("/agent/connections/2/start", { method: "POST" });
    expect(await screen.findByText(/« Lits CH Sud » est démarrée/)).toHaveAttribute("role", "status");

    await userEvent.click(within(await card("Portail Est")).getByRole("button", { name: "Reprendre" }));
    expect(api).toHaveBeenCalledWith("/agent/connections/3/resume", { method: "POST" });

    await userEvent.click(within(await card("Portail Nord")).getByRole("button", { name: "Relever maintenant" }));
    expect(api).toHaveBeenCalledWith("/agent/connections/1/sync", { method: "POST" });

    await userEvent.click(within(await card("Portail Nord")).getByRole("button", { name: "Mettre en pause" }));
    expect(api).not.toHaveBeenCalledWith("/agent/connections/1/pause", expect.anything());
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Mettre en pause « Portail Nord » ?");
    await userEvent.click(within(dialog).getByRole("button", { name: "Mettre en pause" }));
    expect(api).toHaveBeenCalledWith("/agent/connections/1/pause", { method: "POST" });
  });

  it("shows the new state before the server answers", async () => {
    renderPage();
    let release: () => void = () => undefined;
    vi.mocked(api).mockImplementationOnce(() => new Promise((resolve) => (release = () => resolve({} as never))));
    await userEvent.click(within(await card("Lits CH Sud")).getByRole("button", { name: "Démarrer" }));
    expect(await within(await card("Lits CH Sud")).findByText("Active")).toBeInTheDocument();
    release();
  });

  it("hides the commands of a connection the user may not control", async () => {
    list = [connection({ can_control: false, can_edit: false })];
    Object.assign(auth, { isAdmin: false, canWrite: true });
    renderPage();
    const nord = await card("Portail Nord");
    for (const name of ["Relever maintenant", "Mettre en pause", "Modifier"]) {
      expect(within(nord).queryByRole("button", { name })).not.toBeInTheDocument();
    }
  });

  it("gives the direction a read-only view", async () => {
    Object.assign(auth, { isAdmin: false, canWrite: false });
    list = connections.map((c) => ({ ...c, can_control: false, can_edit: false }));
    renderPage();
    await card("Portail Nord");
    for (const name of [/Démarrer/, /Reprendre/, /Relever/, /Mettre en pause/, /Modifier/, /Nouvelle connexion/, /Pause générale/]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("link", { name: /Routage/ })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Passages/ })).toHaveLength(3);
  });

  it("lists the runs of a connection on demand, with the tasks to resume", async () => {
    renderPage();
    const nord = await card("Portail Nord");
    expect(api).not.toHaveBeenCalledWith("/agent/connections/1/runs?limit=20");
    await userEvent.click(within(nord).getByRole("button", { name: /Passages/ }));
    const runs = await within(nord).findByRole("list", { name: "Derniers passages" });
    expect(runs).toHaveTextContent("Relever les demandes");
    expect(runs).toHaveTextContent("À reprendre");
    expect(runs).toHaveTextContent("Page introuvable");
    await userEvent.click(within(runs).getByRole("button", { name: /Relancer/ }));
    expect(api).toHaveBeenCalledWith("/agent/tasks/40/retry", { method: "POST" });
  });

  it("creates a connection without sending an empty password", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Nouvelle connexion/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Nom"), "Portail Ouest");
    await userEvent.selectOptions(within(dialog).getByLabelText("Établissement"), "2");
    await userEvent.type(within(dialog).getByLabelText("Adresse"), "https://ouest.exemple.fr");
    await userEvent.type(within(dialog).getByLabelText("Autres adresses autorisées"), "sso.exemple.fr, cdn.exemple.fr");
    await userEvent.type(within(dialog).getByLabelText("Identifiant"), "ouest");
    await userEvent.click(within(dialog).getByRole("button", { name: "samedi" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "dimanche" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Créer la connexion" }));

    expect(calls("POST")[0][0]).toBe("/agent/connections");
    const body = lastBody("POST");
    expect(body).toEqual({
      name: "Portail Ouest",
      kind: "portail_orientation",
      site_id: 2,
      url: "https://ouest.exemple.fr",
      allowed_hosts: ["sso.exemple.fr", "cdn.exemple.fr"],
      username: "ouest",
      playbook: "trajectoire",
      tasks: ["sync_inbox", "reply_portal"],
      source_system: null,
      interval_minutes: 15,
      active_from: null,
      active_to: null,
      days: [1, 2, 3, 4, 5],
      agent_id: null
    });
    expect(body).not.toHaveProperty("secret");
    expect(await screen.findByText(/« Portail Ouest » est créée/)).toBeInTheDocument();
  });

  it("sends the password only when one is typed", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Nouvelle connexion/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Nom"), "Portail Ouest");
    await userEvent.type(within(dialog).getByLabelText("Adresse"), "https://ouest.exemple.fr");
    await userEvent.type(within(dialog).getByLabelText("Mot de passe"), "s3cret!");
    await userEvent.click(within(dialog).getByRole("button", { name: "Créer la connexion" }));
    expect(lastBody("POST")).toMatchObject({ secret: "s3cret!" });
  });

  it("offers only the scripts and tasks of the chosen software", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Nouvelle connexion/ }));
    const dialog = await screen.findByRole("dialog");
    const script = within(dialog).getByLabelText("Script");
    expect(within(script).getAllByRole("option").map((o) => o.textContent)).toEqual(["Trajectoire régional"]);
    expect(within(dialog).getByLabelText("Reporter les réponses")).toBeChecked();

    await userEvent.selectOptions(within(dialog).getByLabelText("Logiciel lu"), "gestion_lits");
    expect(within(within(dialog).getByLabelText("Script")).getAllByRole("option").map((o) => o.textContent)).toEqual(["BedSoft"]);
    expect(within(dialog).queryByLabelText("Relever les demandes")).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("Relever les mouvements")).toBeChecked();
    expect(within(dialog).getByLabelText("Code de la source")).toBeInTheDocument();
  });

  it("falls back to a free script name with a warning when no worker reported one", async () => {
    workerList = [];
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Nouvelle connexion/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Script").tagName).toBe("INPUT");
    expect(within(dialog).getByText(/Aucun poste n'a encore signalé de script/)).toBeInTheDocument();
  });

  it("edits a connection: the password is never shown, replace sends secret", async () => {
    renderPage();
    await userEvent.click(within(await card("Portail Nord")).getByRole("button", { name: "Modifier" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Défini le/)).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/mot de passe/i)).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("Autres adresses autorisées")).toHaveValue("sso.exemple.fr");

    await userEvent.click(within(dialog).getByRole("button", { name: /Remplacer/ }));
    const input = within(dialog).getByLabelText("Nouveau mot de passe");
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("type", "password");
    await userEvent.type(input, "nouveau-secret");
    await userEvent.click(within(dialog).getByRole("button", { name: "Enregistrer" }));

    expect(calls("PATCH")[0][0]).toBe("/agent/connections/1");
    const body = lastBody("PATCH");
    expect(body).toMatchObject({ secret: "nouveau-secret", name: "Portail Nord", days: [1, 2, 3, 4, 5] });
    expect(body).not.toHaveProperty("clear_secret");
    expect(body).not.toHaveProperty("kind");
  });

  it("edits a connection: keeping the password sends no secret, clearing sends clear_secret", async () => {
    renderPage();
    await userEvent.click(within(await card("Portail Nord")).getByRole("button", { name: "Modifier" }));
    let dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
    expect(lastBody("PATCH")).not.toHaveProperty("secret");
    expect(lastBody("PATCH")).not.toHaveProperty("clear_secret");

    await userEvent.click(within(await card("Portail Nord")).getByRole("button", { name: "Modifier" }));
    dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Effacer le mot de passe" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
    expect(lastBody("PATCH")).toMatchObject({ clear_secret: true });
    expect(lastBody("PATCH")).not.toHaveProperty("secret");
  });

  it("archives a connection after confirmation", async () => {
    renderPage();
    await userEvent.click(within(await card("Portail Est")).getByRole("button", { name: "Modifier" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /Archiver/ }));
    expect(calls("DELETE")).toHaveLength(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Oui, archiver" }));
    expect(api).toHaveBeenCalledWith("/agent/connections/3", { method: "DELETE" });
  });

  it("suspends every command during the group pause", async () => {
    paused = true;
    renderPage();
    expect(await screen.findByText("Pause générale en cours")).toBeInTheDocument();
    const nord = await card("Portail Nord");
    expect(within(nord).getByText("En pause générale")).toBeInTheDocument();
    expect(within(nord).getByRole("button", { name: "Relever maintenant" })).toBeDisabled();
    expect(within(await card("Lits CH Sud")).getByRole("button", { name: "Démarrer" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /Lever la pause générale/ }));
    expect(api).toHaveBeenCalledWith("/agent/resume", { method: "POST" });
  });

  it("asks before the group pause", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Pause générale" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Mettre en pause" }));
    expect(api).toHaveBeenCalledWith("/agent/pause", { method: "POST" });
  });

  it("shows the API error instead of the connections", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "/agent/connections") throw new Error("Connexions indisponibles");
      if (path === "/agent/workers") return [] as never;
      return { paused: false } as never;
    });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Connexions indisponibles");
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });
});
