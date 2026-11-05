import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Availability, Bed, BedBoard } from "../api/types_liscop";
import { BedBoardPage, shortBedLabel } from "../pages/BedBoardPage";

vi.mock("../api/client", () => ({ api: vi.fn() }));
const auth = { canWrite: true, user: { site_id: null } };
vi.mock("../auth", () => ({ useAuth: () => auth }));
import { api } from "../api/client";

function bed(id: number, room: string, status: Bed["status"], extra: Partial<Bed> = {}): Bed {
  return {
    id,
    label: room,
    room,
    sex_constraint: "X",
    isolation: false,
    status,
    status_reason: null,
    occupant_sex: null,
    accepts: ["F", "M"],
    usable: status === "libre",
    updated_at: "2026-10-25T08:00:00Z",
    ...extra
  };
}

const availability: Availability = {
  installed: 5,
  occupied: 1,
  reserved: 0,
  cleaning: 1,
  blocked: 1,
  closed: 1,
  usable: 2,
  female: 0,
  male: 1,
  either: 1,
  isolation: 1,
  sex_conflict: 0,
  extra_beds: 0,
  crisis_reserved_beds: 0,
  tension: { level: "normal", availability_rate: 0.4 }
};

const board: BedBoard = {
  generated_at: "2026-10-25T08:30:00Z",
  sites: [
    {
      site_id: 1,
      site_name: "CH Deux-Rivières",
      availability,
      units: [
        {
          pool_id: 10,
          code: "cardiologie",
          label: "Cardiologie",
          unit_type: "medecine",
          discipline: "medecine",
          availability,
          rooms: [
            { room: "2301", beds: [bed(1, "2301", "libre", { isolation: true })] },
            {
              room: "2302",
              beds: [
                bed(2, "2302", "occupe", { label: "2302A", occupant_sex: "M", accepts: [] }),
                bed(3, "2302", "libre", { label: "2302B", accepts: ["M"] })
              ]
            },
            { room: "2303", beds: [bed(4, "2303", "a_nettoyer")] },
            { room: "2304", beds: [bed(5, "2304", "bloque", { status_reason: "Panne" })] }
          ]
        }
      ]
    }
  ]
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BedBoardPage />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  auth.canWrite = true;
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation((path: string) => Promise.resolve(path === "/beds" ? board : {}) as never);
});

describe("BedBoardPage", () => {
  it("keeps its title while the beds load, shows their shape, and announces the wait once", async () => {
    let arrive: (b: BedBoard) => void = () => undefined;
    vi.mocked(api).mockImplementation(((path: string) =>
      path === "/beds" ? new Promise<BedBoard>((resolve) => (arrive = resolve)) : Promise.resolve({})) as never);
    renderPage();

    expect(screen.getByRole("heading", { level: 1, name: "Plan des lits" })).toBeInTheDocument();
    const wait = screen.getByRole("status");
    expect(wait).toHaveAttribute("aria-busy", "true");
    expect(wait).toHaveTextContent("Chargement du plan des lits…");
    expect(screen.getAllByRole("status")).toHaveLength(1);

    arrive(board);
    await screen.findByRole("region", { name: "Cardiologie" });
    expect(screen.queryByTestId("skeleton")).not.toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("shows the availability KPIs and each bed with its status and sex", async () => {
    renderPage();

    await screen.findByRole("region", { name: "Cardiologie" });
    const kpis = screen.getByLabelText("Disponibilités");
    expect(within(kpis).getByText("lits utilisables maintenant")).toBeInTheDocument();
    expect(within(kpis).getByLabelText("1 pour un homme")).toBeInTheDocument();
    const unit = screen.getByRole("region", { name: "Cardiologie" });
    expect(within(unit).getByRole("button", { name: /Lit 2302B · Libre · peut accueillir : homme seulement/ })).toBeInTheDocument();
    expect(within(unit).getByRole("button", { name: /Lit 2301 · Libre .* chambre d'isolement/ })).toBeInTheDocument();
    expect(screen.queryByText(/patient_ref|encounter/)).not.toBeInTheDocument();
  });

  it("remembers the cadre's unit on this device, and forgets one that no longer exists", async () => {
    localStorage.clear();
    const first = renderPage();
    await screen.findByRole("region", { name: "Cardiologie" });
    await userEvent.selectOptions(screen.getByLabelText("Unité"), "10");
    first.unmount();

    const second = renderPage();
    await screen.findByRole("region", { name: "Cardiologie" });
    expect(screen.getByLabelText("Unité")).toHaveValue("10");
    second.unmount();

    localStorage.setItem("hospitalos.plan-des-lits", JSON.stringify({ siteId: "all", poolId: 999 }));
    renderPage();
    await screen.findByRole("region", { name: "Cardiologie" });
    expect(screen.getByLabelText("Unité")).toHaveValue("all");
    localStorage.clear();
  });

  it("shows the bed letter in a shared room, the room number being above: never a cut « 230… »", async () => {
    renderPage();
    const unit = await screen.findByRole("region", { name: "Cardiologie" });
    const a = within(unit).getByRole("button", { name: /Lit 2302A/ });
    const b = within(unit).getByRole("button", { name: /Lit 2302B/ });
    expect(within(a).getByText("A")).toBeInTheDocument();
    expect(within(b).getByText("B")).toBeInTheDocument();
    expect(within(b).queryByText("2302B")).not.toBeInTheDocument();
    // A single room keeps its full label, and the spoken name always says the whole bed.
    expect(within(within(unit).getByRole("button", { name: /Lit 2301 · Libre/ })).getByText("2301")).toBeInTheDocument();
    expect(shortBedLabel("2316 B", "2316", true)).toBe("B");
    expect(shortBedLabel("Fenêtre", "2316", true)).toBe("Fenêtre"); // not prefixed by the room
    expect(shortBedLabel("2316", "2316", true)).toBe("2316");
  });

  it("filters beds by status", async () => {
    renderPage();
    await screen.findByRole("region", { name: "Cardiologie" });

    await userEvent.click(screen.getByRole("button", { name: "À nettoyer", pressed: false }));

    const unit = screen.getByRole("region", { name: "Cardiologie" });
    expect(within(unit).getAllByRole("button")).toHaveLength(1);
    expect(within(unit).getByRole("button", { name: /Lit 2303 · À nettoyer/ })).toBeInTheDocument();
  });

  it("marks a bed cleaned after confirmation in the dialog", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Lit 2303 · À nettoyer/ }));

    await userEvent.click(screen.getByRole("button", { name: "Marquer nettoyé" }));

    expect(api).toHaveBeenCalledWith("/beds/4", { method: "PATCH", json: { action: "nettoye" } });
  });

  it("asks for a coded reason before blocking a bed, with an optional short note", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Lit 2301 · Libre/ }));
    await userEvent.click(screen.getByRole("button", { name: "Bloquer" }));
    const confirm = screen.getByRole("button", { name: "Confirmer le blocage" });
    expect(confirm).toBeDisabled();
    expect(screen.getByLabelText("Précision (facultatif)")).toHaveAttribute("maxLength", "80");

    await userEvent.selectOptions(screen.getByLabelText("Motif du blocage"), "Équipement en panne");
    await userEvent.type(screen.getByLabelText("Précision (facultatif)"), "Fuite d'eau");
    await userEvent.click(confirm);

    expect(api).toHaveBeenCalledWith("/beds/1", {
      method: "PATCH",
      json: { action: "bloquer", reason: "equipement", note: "Fuite d'eau" }
    });
  });

  it("shows a cleaned bed as free at once, before the API answers, then confirms it", async () => {
    let answer: (value: unknown) => void = () => undefined;
    vi.mocked(api).mockImplementation(((path: string, init?: { method?: string }) =>
      init?.method === "PATCH"
        ? new Promise((resolve) => (answer = resolve))
        : Promise.resolve(path === "/beds" ? board : {})) as never);
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Lit 2303 · À nettoyer/ }));
    await userEvent.click(screen.getByRole("button", { name: "Marquer nettoyé" }));

    // The dialog is gone and the tile already says « Libre », marked as being saved.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const tile = screen.getByRole("button", { name: /Lit 2303 · Libre.*enregistrement en cours/ });
    expect(tile).toHaveAttribute("aria-busy", "true");
    const boardFetches = () => vi.mocked(api).mock.calls.filter(([path]) => path === "/beds").length;
    const before = boardFetches();

    answer({});
    await waitFor(() => expect(boardFetches()).toBeGreaterThan(before)); // the counts follow the API
    await waitFor(() => expect(screen.getByRole("button", { name: /Lit 2303/ })).not.toHaveAttribute("aria-busy"));
  });

  it("puts the bed back and says why when the API refuses the action", async () => {
    vi.mocked(api).mockImplementation(((path: string, init?: { method?: string }) =>
      init?.method === "PATCH"
        ? Promise.reject(new Error("Action impossible dans l'état actuel du lit"))
        : Promise.resolve(path === "/beds" ? board : {})) as never);
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Lit 2303 · À nettoyer/ }));
    await userEvent.click(screen.getByRole("button", { name: "Marquer nettoyé" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Lit 2303 : Action impossible dans l'état actuel du lit. Il a repris son état."
    );
    expect(screen.getByRole("button", { name: /Lit 2303 · À nettoyer/ })).not.toHaveAttribute("aria-busy");
    await userEvent.click(screen.getByRole("button", { name: "Compris" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("blocks without a note when none is given", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Lit 2301 · Libre/ }));
    await userEvent.click(screen.getByRole("button", { name: "Bloquer" }));

    await userEvent.selectOptions(screen.getByLabelText("Motif du blocage"), "travaux");
    await userEvent.click(screen.getByRole("button", { name: "Confirmer le blocage" }));

    expect(api).toHaveBeenCalledWith("/beds/1", { method: "PATCH", json: { action: "bloquer", reason: "travaux" } });
  });

  it("never offers to free an occupied bed", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Lit 2302A · Occupé/ }));

    expect(screen.getByText(/il se libère à la sortie/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Marquer nettoyé|Débloquer|Réserver/ })).not.toBeInTheDocument();
  });

  it("is read-only for the direction", async () => {
    auth.canWrite = false;
    renderPage();
    const unit = await screen.findByRole("region", { name: "Cardiologie" });

    expect(within(unit).queryAllByRole("button")).toHaveLength(0);
    expect(within(unit).getAllByTitle(/Lit /)).toHaveLength(5);
  });
});
