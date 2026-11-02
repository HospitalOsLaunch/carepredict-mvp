import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { RorExport, RorOutboxEntry, RorUnite } from "../api/types_liscop";
import { forecastLevel, freshnessBars, RorPage, TensionChip } from "../pages/RorPage";

vi.mock("../api/client", () => ({ api: vi.fn() }));
const auth = { isAdmin: true };
vi.mock("../auth", () => ({ useAuth: () => auth }));
import { api } from "../api/client";

const status = (code: string, libelle: string) => ({ code, libelle });

function unit(extra: Partial<RorUnite> = {}): RorUnite {
  return {
    site_id: 1,
    etablissement: "CH Deux-Rivières",
    finess_geographique: null,
    pool_id: 7,
    identifiant_unite_ror: null,
    mention: "medecine_polyvalente",
    libelle_unite: "Médecine polyvalente",
    type_unite: "medecine",
    discipline: "medecine",
    capacites: [{ statut: status("02", "Disponible"), nombre: 5, remarque: null }],
    fermetures: [{ type_fermeture: status("01", "Réactivable"), nombre: 3, motif_interne: "personnel" }],
    disponibles_par_genre: { femme: 1, homme: 2, indetermine: 2, total: 5, isolement: 1, niveau: "lit" },
    operationnel: { en_service: 27, reactivables: 3, supplementaires: 2 },
    reserves_crise_sse: 4,
    previsionnel: [
      {
        echeance: "J+1",
        date: "2026-10-26",
        temporalite: status("03", "Prévisionnel 24 heures"),
        moyenne: 4.2,
        fourchette_80: [2, 7],
        p_tension: 0.62,
        p_critique: 0.1
      }
    ],
    previsionnel_nature: {
      nature: "disponibles_attendus",
      libelle: "Disponibles attendus",
      modele: "engine-1",
      date_de_calcul: "2026-10-25",
      calcule_le: "2026-10-25T04:00:00Z"
    },
    tension: { niveau: "tension", taux_disponibilite: 0.1667 },
    fraicheur: { le: "2026-10-25T06:30:00Z", source: "lit", libelle: "changement de statut d'un lit", age_heures: 2 },
    dernier_mouvement_saisi: "2026-10-25T06:30:00Z",
    ror_capacites: [],
    a_completer: ["Identifiant ROR de l'unité"],
    ...extra
  };
}

const sample: RorExport = {
  maquette: true,
  avertissement: "Maquette : rien n'est envoyé au ROR.",
  emetteur: "HospitalOS — Démo (maquette)",
  genere_le: "2026-10-25T08:30:00Z",
  date_situation: "2026-10-25",
  synthetique: true,
  prevision: { id: 3, date_de_calcul: "2026-10-25", calcule_le: "2026-10-25T04:00:00Z", modele: "engine-1", perimee: false },
  referentiels: [{ nom: "JDV_J188_TypeStatutCapacite_ROR", url: "https://example.org/j188" }],
  hypotheses: ["Disponibles = lits utilisables."],
  non_suivi_dans_le_pilote: ["Identifiant ROR de chaque unité."],
  unites: [
    unit(),
    unit({
      pool_id: 8,
      libelle_unite: "SMR Gériatrie",
      identifiant_unite_ror: "UO-1",
      disponibles_par_genre: { femme: null, homme: null, indetermine: null, total: 0, isolement: null, niveau: "unite" },
      previsionnel_nature: { nature: "liberes_non_promis", libelle: "Libérés", modele: null, date_de_calcul: null, calcule_le: null },
      tension: { niveau: "critique", taux_disponibilite: 0 },
      fraicheur: null
    })
  ]
};

const sent: RorOutboxEntry = {
  id: 12,
  cree_le: "2026-10-25T08:31:00Z",
  type: "ror_capacity",
  statut: "simulated",
  empreinte_sha256: "ab".repeat(32),
  unites: 2,
  prepare_par: "Admin Démo",
  contenu: null
};

function mockApi(history: RorOutboxEntry[] = []) {
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === "/ror/export") return sample;
    if (path === "/ror/outbox" && init?.method === "POST") return sent;
    if (path === "/ror/outbox") return history;
    if (path.startsWith("/oru/indicators")) return "﻿Date;Site\r\n";
    throw new Error(`unexpected ${path}`);
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RorPage />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.mocked(api).mockReset();
  auth.isAdmin = true;
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
});

describe("RorPage", () => {
  it("shows each unit like LISCOP: gender, forecast, operational, crisis, tension, freshness", async () => {
    mockApi();
    renderPage();
    expect(await screen.findByRole("note")).toHaveTextContent(/rien n'est envoyé au ROR/);
    const table = screen.getByRole("table");
    const row = within(table).getByRole("row", { name: /Médecine polyvalente/ });
    const cells = within(row).getAllByRole("cell").map((c) => c.textContent);
    expect(cells.slice(0, 4)).toEqual(["1", "2", "2", "5"]);
    expect(within(row).getByText(/risque de tension/).parentElement).toHaveTextContent("risque de tension 62 %");
    expect(within(row).getByText("2 à 7")).toBeInTheDocument();
    expect(cells).toContain("27");
    expect(cells).toContain("4");
    expect(within(row).getByText("Tension")).toBeInTheDocument();
    expect(within(row).getByRole("img", { name: /Fraîcheur 3 sur 4/ })).toBeInTheDocument();
    expect(within(row).getByText("à rattacher")).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "J+7" })).toBeInTheDocument();
  });

  it("labels the discharge fallback and units without a bed plan", async () => {
    mockApi();
    renderPage();
    const row = await within(await screen.findByRole("table")).findByRole("row", { name: /SMR Gériatrie/ });
    expect(within(row).getByText("libérés")).toBeInTheDocument();
    expect(within(row).getByText(/sans plan des lits/)).toBeInTheDocument();
    expect(within(row).getByText("UO-1")).toBeInTheDocument();
    expect(within(row).getByText("inconnue")).toBeInTheDocument();
  });

  it("prepares a simulated send for administrators and lists the history", async () => {
    mockApi([sent]);
    renderPage();
    const button = await screen.findByRole("button", { name: /Préparer un envoi \(simulation\)/ });
    expect(await screen.findByRole("list", { name: /Historique des envois simulés/ })).toHaveTextContent("Admin Démo");
    await userEvent.click(button);
    expect(await screen.findByRole("status")).toHaveTextContent(/n° 12 préparé \(2 unités\), non transmis/);
    expect(api).toHaveBeenCalledWith("/ror/outbox", { method: "POST" });
  });

  it("hides the send queue from other roles", async () => {
    auth.isAdmin = false;
    mockApi();
    renderPage();
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: /Préparer un envoi/ })).not.toBeInTheDocument();
    expect(api).not.toHaveBeenCalledWith("/ror/outbox");
  });

  it("downloads the ORU indicators for the chosen period as CSV", async () => {
    mockApi();
    renderPage();
    await screen.findByRole("table");
    const from = screen.getByLabelText("Du");
    await userEvent.clear(from);
    await userEvent.type(from, "2026-09-01");
    await userEvent.click(screen.getByRole("button", { name: "CSV" }));
    const calls = vi.mocked(api).mock.calls.map((c) => c[0]);
    expect(calls.some((p) => p.startsWith("/oru/indicators?start=2026-09-01&") && p.endsWith("format=csv"))).toBe(true);
    expect(URL.createObjectURL).toHaveBeenCalled();
  });
});

describe("helpers", () => {
  it("maps the age of the data to LISCOP-like signal bars", () => {
    expect([0.5, 2, 6, 20, 30, null].map((h) => freshnessBars(h))).toEqual([4, 3, 2, 1, 0, 0]);
  });

  it("takes the most likely level of a forecast day", () => {
    const p = unit().previsionnel[0];
    expect(forecastLevel(p)).toBe("tension");
    expect(forecastLevel({ ...p, p_critique: 0.7 })).toBe("critique");
    expect(forecastLevel({ ...p, p_tension: 0.1 })).toBe("normal");
  });
});

describe("TensionChip", () => {
  it("labels the three LISCOP levels", () => {
    render(
      <>
        <TensionChip level="normal" rate={0.3} />
        <TensionChip level="critique" rate={0} />
      </>
    );
    expect(screen.getByText("Normal")).toBeInTheDocument();
    expect(screen.getByText("Critique")).toBeInTheDocument();
  });
});
