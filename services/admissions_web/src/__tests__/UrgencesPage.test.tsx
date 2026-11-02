import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { BoardingSeries, EdCensus, TensionDeclaration, TensionStatus } from "../api/types_liscop";
import { UrgencesPage } from "../pages/UrgencesPage";

vi.mock("../api/client", () => ({ api: vi.fn() }));
const auth = { canWrite: true, user: { site_id: null } };
vi.mock("../auth", () => ({ useAuth: () => auth }));
import { api } from "../api/client";

class NoResize {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= NoResize as unknown as typeof ResizeObserver;

const census: EdCensus = {
  site_id: 1,
  site_name: "CH Deux-Rivières",
  ed_sites: [{ id: 1, name: "CH Deux-Rivières" }],
  now: { at: "2026-10-25T08:30:00Z", present: 42, waiting_bed: 9, longest_wait_hours: 14.2, hosted_elsewhere: 3 },
  today_10h: {
    day: "2026-10-25",
    at: "2026-10-25T09:00:00Z",
    reached: false,
    boarding: 6,
    computed_boarding: 6,
    source: "calcul"
  },
  latest_declaration: null,
  definitions: ["Lits brancards à 10 h : définition HospitalOS, à valider avec l'ARS."]
};

const series: BoardingSeries = {
  site_id: 1,
  days: [
    { day: "2026-10-23", present: 38, waiting_bed: 7, boarding: 4, hosted_elsewhere: 1, source: "calcul", computed_boarding: 4 },
    { day: "2026-10-24", present: 40, waiting_bed: 8, boarding: 5, hosted_elsewhere: 2, source: "declaration", computed_boarding: 3 }
  ]
};

const active: TensionDeclaration = {
  id: 7,
  site_id: 1,
  kind: "het",
  level: "niveau_1",
  started_at: "2026-10-25T06:00:00Z",
  ended_at: null,
  declared_by: "Gestion des lits (démo)",
  comment: null
};

const status: TensionStatus = {
  generated_at: "2026-10-25T08:30:00Z",
  units: [
    { site_id: 1, site_name: "CH Deux-Rivières", pool_id: 2, code: "cardiologie", label: "Cardiologie", discipline: "medecine", installed: 28, usable: 0, tension: { level: "critique", availability_rate: 0 } },
    { site_id: 1, site_name: "CH Deux-Rivières", pool_id: 3, code: "reanimation", label: "Réanimation", discipline: "soins_critiques", installed: 12, usable: 4, tension: { level: "normal", availability_rate: 0.33 } }
  ],
  aid: {
    site_id: 1,
    level: "het_suggere",
    label: "Déclaration HET à envisager",
    criteria: [
      { code: "boarding_10h", label: "Lits brancards à 10 h", value: 5, threshold: 5, triggered: true },
      { code: "waiting_bed", label: "Patients en attente de lit", value: 9, threshold: 10, triggered: false },
      { code: "longest_wait_hours", label: "Attente de lit la plus longue (heures)", value: 14.2, threshold: 12, triggered: true },
      { code: "critical_units_share", label: "Part des unités MCO en niveau critique", value: 0.5, threshold: 0.25, triggered: true }
    ],
    notice: "Aide à la décision : la déclaration reste une décision de la direction."
  },
  active_declarations: [active]
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <UrgencesPage />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  auth.canWrite = true;
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(((path: string) => {
    if (path.startsWith("/ed/census")) return Promise.resolve(census);
    if (path.startsWith("/ed/boarding")) return Promise.resolve(series);
    if (path.startsWith("/ed/snapshots")) return Promise.resolve([]);
    if (path.startsWith("/tension/status")) return Promise.resolve(status);
    if (path.startsWith("/tension/declarations")) return Promise.resolve([active]);
    return Promise.resolve({});
  }) as never);
});

describe("UrgencesPage", () => {
  it("shows the live census with a provisional boarding before 10:00", async () => {
    renderPage();

    const cards = await screen.findByRole("region", { name: /Recensement/ });
    expect(within(cards).getByText("42")).toBeInTheDocument();
    expect(within(cards).getByText("lits brancards à 10 h aujourd'hui")).toBeInTheDocument();
    expect(within(cards).getByText(/Provisoire/)).toBeInTheDocument();
    expect(within(cards).getByText(/Attente la plus longue : 14 h/)).toBeInTheDocument();
  });

  it("lists the HET criteria with values and says the decision stays human", async () => {
    renderPage();

    const aid = await screen.findByRole("region", { name: "Aide à la décision HET" });
    expect(within(aid).getByText("Déclaration HET à envisager")).toBeInTheDocument();
    expect(within(aid).getByText("50 % (seuil 25 %)")).toBeInTheDocument();
    expect(within(aid).getAllByLabelText("critère atteint")).toHaveLength(3);
    expect(within(aid).getByRole("note")).toHaveTextContent("la déclaration reste une décision de la direction");
  });

  it("lists units from the most critical with the LISCOP legend", async () => {
    renderPage();

    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Cardiologie");
    expect(within(rows[1]).getByText("Critique")).toBeInTheDocument();
    expect(screen.getByText(/Légende LISCOP/)).toBeInTheDocument();
  });

  it("records a manual census declaration", async () => {
    renderPage();
    const form = await screen.findByRole("region", { name: "Déclaration manuelle du recensement" });

    await userEvent.type(within(form).getByLabelText("Présents"), "40");
    await userEvent.type(within(form).getByLabelText("En attente de lit"), "8");
    await userEvent.type(within(form).getByLabelText("Lits brancards"), "5");
    await userEvent.click(within(form).getByRole("button", { name: "Déclarer maintenant" }));

    expect(api).toHaveBeenCalledWith("/ed/snapshots", {
      method: "POST",
      json: { site_id: 1, present: 40, waiting_bed: 8, boarding: 5, hosted_elsewhere: 0 }
    });
  });

  it("closes an active declaration after confirmation", async () => {
    renderPage();
    const section = await screen.findByRole("region", { name: "Déclarations HET et Plan blanc" });
    expect(within(section).getByText("Hôpital en tension · Niveau 1")).toBeInTheDocument();

    await userEvent.click(within(section).getByRole("button", { name: "Clôturer" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirmer la clôture" }));

    expect(api).toHaveBeenCalledWith("/tension/declarations/7", expect.objectContaining({ method: "PATCH" }));
  });

  it("shows the API error instead of the census", async () => {
    vi.mocked(api).mockRejectedValue(new Error("Recensement indisponible"));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Recensement indisponible");
    expect(screen.queryByRole("region", { name: /Recensement/ })).not.toBeInTheDocument();
  });

  it("hides write actions for read-only roles", async () => {
    auth.canWrite = false;
    renderPage();
    await screen.findByRole("region", { name: "Aide à la décision HET" });

    expect(screen.queryByRole("button", { name: "Enregistrer une déclaration" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Déclarer maintenant" })).not.toBeInTheDocument();
    expect(screen.getByText("Lecture seule pour votre rôle.")).toBeInTheDocument();
  });
});
