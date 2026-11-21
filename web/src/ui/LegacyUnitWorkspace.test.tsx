import { fireEvent, render, screen, within } from "@testing-library/react";
import { journal } from "../data/journal";
import { LegacyUnitWorkspace } from "./LegacyUnitWorkspace";

beforeEach(() => {
  window.localStorage.clear();
  journal.reset();
  window.history.replaceState(null, "", "/?situation=nominal#/");
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
});

it("keeps the same patient, resource, chosen alternative and decision record through the four tabs", async () => {
  const { rerender } = render(<LegacyUnitWorkspace view="unite" />);
  const first = await screen.findByRole("region", { name: "Demander le transport de P-0412" });
  const forecast = within(first).getByLabelText("Effet simulé").textContent;
  const time = screen.getByText("État à").textContent;
  expect(within(screen.getByRole("region", { name: "Libérer" })).getByLabelText("Étapes de sortie de P-0412")).toBeTruthy();
  expect(screen.getByRole("region", { name: "Lits" })).toBeTruthy();
  expect(screen.getByRole("region", { name: "Attribuer" })).toBeTruthy();
  expect(within(first).getByRole("link", { name: /Détail/ }).getAttribute("href")).toBe("#/action");
  fireEvent.click(within(first).getByRole("button", { name: "1 autre option utile" }));
  fireEvent.click(within(first).getByRole("button", { name: "Choisir plutôt" }));
  const alternative = "Prioriser le bionettoyage du lit L11";

  rerender(<LegacyUnitWorkspace view="action" />);
  const actions = await screen.findByRole("region", { name: "Demander le transport de P-0412" });
  expect(within(actions).getByText("Refusée : autre option préférée")).toBeTruthy();
  expect(within(actions).getByLabelText("Effet simulé").textContent).toBe(forecast);
  expect(screen.getByText("État à").textContent).toBe(time);
  const active = screen.getByRole("region", { name: /En cours de votre côté/ });
  expect(within(active).getByText(alternative)).toBeTruthy();
  rerender(<LegacyUnitWorkspace view="journal" />);
  const pending = screen.getByRole("region", { name: "À suivre" });
  const link = within(pending).getByRole("link", { name: new RegExp(alternative) });
  expect(link.getAttribute("href")).toMatch(/^#\/dossiers\/journal\//);
  fireEvent.click(link);
  const fiche = screen.getByRole("region", { name: alternative });
  expect(within(fiche).getByRole("heading", { name: alternative })).toBeTruthy();
  fireEvent.click(within(fiche).getByRole("link", { name: "Fermer la fiche" }));
  expect(screen.queryByRole("region", { name: alternative })).toBeNull();
  rerender(<LegacyUnitWorkspace view="donnees" />);
  expect(screen.getByRole("heading", { name: "Qualité des données" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "Unité" }).getAttribute("href")).toBe("#/");
  rerender(<LegacyUnitWorkspace view="unite" />);
  expect(within(screen.getByRole("region", { name: /En cours de votre côté/ })).getByText(alternative)).toBeTruthy();
});
