import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";

import type { RorExport } from "../api/types";
import { RorPage, TensionChip } from "../pages/RorPage";

vi.mock("../api/client", () => ({ api: vi.fn() }));
import { api } from "../api/client";

const sample: RorExport = {
  maquette: true,
  avertissement: "Maquette : rien n'est envoyé au ROR.",
  emetteur: "HospitalOS — Démo (maquette)",
  genere_le: "2026-10-25T08:30:00Z",
  date_situation: "2026-10-25",
  referentiels: [{ nom: "JDV_J188_TypeStatutCapacite_ROR", url: "https://example.org/j188" }],
  hypotheses: ["Lits disponibles = lits ouverts − présents − réservés."],
  non_suivi_dans_le_pilote: ["Disponibilité par genre non suivie."],
  unites: [
    {
      site_id: 1,
      etablissement: "SMR Les Tilleuls",
      finess_geographique: null,
      identifiant_unite_ror: null,
      mention: "geriatrie",
      libelle_unite: "SMR Gériatrie",
      capacites: [
        { statut: { code: "01", libelle: "Installé" }, nombre: 36, remarque: null },
        { statut: { code: "02", libelle: "Disponible" }, nombre: 3, remarque: null },
        { statut: { code: "03", libelle: "Occupé" }, nombre: 28, remarque: null },
        { statut: { code: "04", libelle: "Réservé" }, nombre: 1, remarque: null },
        { statut: { code: "05", libelle: "Fermé" }, nombre: 4, remarque: null },
        { statut: { code: "06", libelle: "Supplémentaire" }, nombre: null, remarque: "Non suivi." }
      ],
      fermetures: [{ type_fermeture: { code: "01", libelle: "Réactivable" }, nombre: 4, motif_interne: "personnel" }],
      previsionnel: [
        { echeance: "J+1", date: "2026-10-26", lits_disponibles_attendus: 4.2, fourchette_80: [2, 6] },
        { echeance: "J+7", date: "2026-11-01", lits_disponibles_attendus: 11, fourchette_80: [8, 14] }
      ],
      tension: { niveau: "tension", taux_disponibilite: 0.0833 },
      dernier_mouvement_saisi: "2026-10-25T06:30:00Z",
      a_completer: ["Identifiant ROR de l'unité"]
    }
  ]
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RorPage />
    </QueryClientProvider>
  );
}

describe("RorPage", () => {
  it("states it is a mock-up and shows each unit by ROR status", async () => {
    vi.mocked(api).mockResolvedValue(sample);
    renderPage();
    expect(await screen.findByRole("note")).toHaveTextContent(/rien n'est envoyé au ROR/);
    const row = screen.getByRole("row", { name: /SMR Gériatrie/ });
    expect(within(row).getByText("Tension")).toBeInTheDocument();
    expect(within(row).getByText("réactivable")).toBeInTheDocument();
    expect(within(row).getByText("il y a 2 h")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Prévu J+7" })).toBeInTheDocument();
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
