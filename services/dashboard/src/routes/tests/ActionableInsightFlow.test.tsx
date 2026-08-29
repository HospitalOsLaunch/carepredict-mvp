import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import App from "../../App";
import { formatHeaderDateTime } from "../../app/dateTime";
import { researchNavigationItems } from "../../app/navigation";
import { ScenarioProvider, useScenarioContext } from "../../domain/ScenarioContext";
import { classifyRiskLevel, formatRiskLevel, RESEARCH_INSIGHT, simulateDischargeScenario } from "../../domain/insights";
import {
  classifySiipsWorkload,
  formatWorkloadLevel,
  HCL_TARGET_PRODUCT_RESEARCH_SCENARIO as scenario,
  RESEARCH_HORIZONS,
  targetForecastFor,
  targetScenarioStateFor,
} from "../../research/hclTargetScenario";
import { formatSiipsTooltipValue } from "../../research/ScenarioTrajectoryChart";
import { Actions } from "../Actions";
import { ForecastDetail } from "../ForecastDetail";
import { History, sortHistoryRows, type HistoryRow } from "../History";
import { Situations } from "../Insights";
import { ModifyInsight } from "../ModifyInsight";

function renderWorkflow(initialEntry = "/situations") {
  return render(
    <ScenarioProvider>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/situations" element={<Situations />} />
          <Route path="/situations/:insightId" element={<Situations />} />
          <Route path="/situations/:insightId/forecast" element={<ForecastDetail />} />
          <Route path="/situations/:insightId/modify" element={<ModifyInsight />} />
          <Route path="/actions" element={<Actions />} />
          <Route path="/history" element={<History />} />
        </Routes>
      </MemoryRouter>
    </ScenarioProvider>,
  );
}

function ScenarioProbe() {
  const context = useScenarioContext();
  return <div>
    <output data-testid="probe-decision">{context.decision?.decision ?? "none"}</output>
    <output data-testid="probe-events">{context.auditEvents.length}</output>
    <output data-testid="probe-session">{context.researchSessionId}</output>
    <output data-testid="probe-selected">{context.selectedParameters.confirmed_discharges}</output>
    <output data-testid="probe-unit">{context.selectedUnitId}</output>
    <output data-testid="probe-horizon">{context.horizonHours}</output>
    <button type="button" onClick={() => context.setParameter("confirmed_discharges", 3)}>set-three</button>
    <button type="button" onClick={context.acceptRecommendation}>accept</button>
    <button type="button" onClick={context.acceptModifiedScenario}>accept-modified</button>
    <button type="button" onClick={() => context.refuseRecommendation("Action déjà engagée")}>refuse</button>
    <button type="button" onClick={() => context.refuseRecommendation("Action déjà engagée", "modified_scenario")}>refuse-modified</button>
    <button type="button" onClick={() => context.setSelectedUnit("pediatrics")}>pediatrics</button>
    <button type="button" onClick={() => context.setHorizonHours(12)}>horizon-12</button>
    <button type="button" onClick={context.resetResearchScenario}>reset</button>
  </div>;
}

describe("prototype produit cible HospitalOS", () => {
  it("centralise un scénario cohérent et ses dimensions opérationnelles", () => {
    const states = [scenario.states.baseline, scenario.states.recommended, scenario.states.custom3, scenario.states.custom7];
    for (const state of states) {
      expect(state.peakOccupiedBeds + state.peakAvailableBeds).toBe(scenario.bedCapacity);
      expect(state.peakOccupancyPercent).toBeCloseTo((state.peakOccupiedBeds / scenario.bedCapacity) * 100, 1);
    }
    expect(scenario.states.recommended.peakSiips).toBeLessThan(scenario.states.custom3.peakSiips);
    expect(scenario.states.custom3.peakSiips).toBeLessThan(scenario.states.baseline.peakSiips);
    expect(scenario.states.custom7.peakSiips).toBeLessThan(scenario.states.recommended.peakSiips);
    expect(scenario.states.recommended.criticalHours).toBeLessThan(scenario.states.custom3.criticalHours);
    expect(scenario.states.custom3.criticalHours).toBeLessThan(scenario.states.baseline.criticalHours);
    expect(scenario.states.custom7.criticalHours).toBe(0);
  });

  it("place les signaux et la recommandation avant l'évolution dans l'ordre DOM", () => {
    renderWorkflow();
    const bodyText = document.body.textContent ?? "";
    const associatedSignals = bodyText.indexOf("Signaux associés à la tension");
    const recommendation = bodyText.indexOf("Action recommandée");
    const evolution = bodyText.indexOf("Évolution prévue");
    expect(associatedSignals).toBeGreaterThan(-1);
    expect(recommendation).toBeGreaterThan(-1);
    expect(associatedSignals).toBeLessThan(evolution);
    expect(recommendation).toBeLessThan(evolution);
    expect(screen.getByRole("button", { name: /^Exécuter$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Modifier$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Refuser$/ })).toBeInTheDocument();
  });

  it("classe la charge SIIPS avec la fonction partagée et sans seuil clinique revendiqué", () => {
    expect(formatWorkloadLevel(classifySiipsWorkload(1810))).toBe("Très élevée");
    expect(formatWorkloadLevel(classifySiipsWorkload(1690))).toBe("Élevée");
    expect(formatWorkloadLevel(classifySiipsWorkload(1610))).toBe("Élevée");
    expect(formatWorkloadLevel(classifySiipsWorkload(1530))).toBe("Modérée");
    renderWorkflow();
    expect(screen.getByText("Très élevée", { selector: "p" })).toBeInTheDocument();
    expect(screen.getAllByText(/1810/).length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(/seuil HCL|seuil national SIIPS/i);
    expect(formatSiipsTooltipValue(1810)).toMatch(/1.810|1\s810/);
    expect(formatSiipsTooltipValue(1810)).toContain("SIIPS");
  });

  it("produit une trajectoire déterministe non vide pour tous les horizons", () => {
    expect(RESEARCH_HORIZONS).toEqual([6, 12, 18, 24, 48, 72]);
    for (const horizon of RESEARCH_HORIZONS) {
      const points = targetForecastFor(5, horizon);
      expect(points.length).toBeGreaterThan(1);
      expect(points[points.length - 1]?.elapsedHours).toBeLessThanOrEqual(horizon);
    }
    const seventyTwoHourPoints = targetForecastFor(5, 72);
    expect(seventyTwoHourPoints[seventyTwoHourPoints.length - 1]?.elapsedHours).toBe(72);
  });

  it("formate la date et l'heure françaises sans secondes", () => {
    const formatted = formatHeaderDateTime(new Date(2026, 7, 29, 23, 21, 49));
    expect(formatted).toContain("29 AOÛT 2026");
    expect(formatted).toContain("23:21");
    expect(formatted).not.toContain("49");
  });

  it("met unité et horizon dans le contexte, les conserve et les réinitialise explicitement", async () => {
    const user = userEvent.setup();
    render(<ScenarioProvider><ScenarioProbe /></ScenarioProvider>);
    await user.click(screen.getByRole("button", { name: "pediatrics" }));
    await user.click(screen.getByRole("button", { name: "horizon-12" }));
    expect(screen.getByTestId("probe-unit")).toHaveTextContent("pediatrics");
    expect(screen.getByTestId("probe-horizon")).toHaveTextContent("12");
    await user.click(screen.getByRole("button", { name: "reset" }));
    expect(screen.getByTestId("probe-unit")).toHaveTextContent("emergency");
    expect(screen.getByTestId("probe-horizon")).toHaveTextContent("48");
  });

  it("expose les contrôles du header et conserve le contexte lors de la navigation", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(screen.queryByText("Hôpital Démo")).not.toBeInTheDocument();
    const horizon = screen.getByRole("button", { name: "Horizon de prévision" });
    const unit = screen.getByRole("button", { name: "Unité hospitalière" });
    await user.click(horizon);
    expect(within(screen.getByRole("listbox", { name: "Horizon disponible" })).getAllByRole("option").map((option) => option.textContent)).toEqual(["6 h", "12 h", "18 h", "24 h", "48 h", "72 h"]);
    await user.click(screen.getByRole("option", { name: "12 h" }));
    await user.click(unit);
    await user.click(screen.getByRole("option", { name: "Pédiatrie" }));
    await user.click(screen.getByRole("link", { name: "Actions" }));
    expect(screen.getByRole("button", { name: "Horizon de prévision" })).toHaveTextContent("12 h");
    expect(screen.getByRole("button", { name: "Unité hospitalière" })).toHaveTextContent("Pédiatrie");
  });

  it("affiche un état de recherche neutre pour une unité sans fixture dédiée", async () => {
    const user = userEvent.setup();
    render(<ScenarioProvider><MemoryRouter><ScenarioProbe /><Situations /></MemoryRouter></ScenarioProvider>);
    await user.click(screen.getByRole("button", { name: "pediatrics" }));
    expect(screen.getByRole("heading", { name: "Aucune situation prioritaire sur l’horizon sélectionné." })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Exécuter$/ })).not.toBeInTheDocument();
  });

  it("conserve le même contexte dans Situation, évolution et option", async () => {
    const user = userEvent.setup();
    renderWorkflow();
    await user.click(screen.getByRole("link", { name: /Voir l'évolution prévue/ }));
    expect(screen.getByText(/Urgences.*horizon 48 h/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Évolution prévue" })).toBeInTheDocument();
  });

  it("valide une action humaine sans exécution hospitalière et reste terminale", async () => {
    const user = userEvent.setup();
    renderWorkflow();
    await user.click(screen.getByRole("button", { name: /^Exécuter$/ }));
    expect(screen.getByRole("dialog", { name: "Valider cette action" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Valider l'action" }));
    expect(screen.getByRole("status")).toHaveTextContent("Action validée");
    expect(screen.queryByRole("button", { name: /^Exécuter$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Modifier$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Refuser$/ })).not.toBeInTheDocument();
  });

  it("refuse avec un motif et conserve la tension active", async () => {
    const user = userEvent.setup();
    renderWorkflow();
    await user.click(screen.getByRole("button", { name: /^Refuser$/ }));
    const confirm = screen.getByRole("button", { name: "Confirmer le refus" });
    expect(confirm).toBeDisabled();
    await user.selectOptions(screen.getByRole("combobox", { name: "Motif du refus" }), "Ressources indisponibles");
    await user.click(confirm);
    expect(screen.getByRole("heading", { name: "Tension critique prévue de 16h à 20h" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Décision refusée");
  });

  it("préremplit et simule les options 3, 5 et 7", async () => {
    const user = userEvent.setup();
    renderWorkflow(`/situations/${RESEARCH_INSIGHT.id}/modify`);
    expect(screen.getByRole("spinbutton", { name: "Sorties à avancer avant 15h" })).toHaveValue(5);
    await user.click(screen.getByRole("button", { name: /^3$/ }));
    expect(screen.getByText(/effort opérationnel réduit de 2 sorties/)).toBeInTheDocument();
    expect(screen.getAllByText("1690 SIIPS").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: /^7$/ }));
    expect(screen.getByText(/bénéfice attendu augmente/)).toBeInTheDocument();
    expect(screen.getAllByText("1530 SIIPS").length).toBeGreaterThan(0);
    expect(screen.getByText("Modérée")).toBeInTheDocument();
  });

  it("utilise la classification de risque partagée", () => {
    expect(formatRiskLevel(classifyRiskLevel(1810, 6))).toBe("Critique");
    expect(formatRiskLevel(classifyRiskLevel(1690, 4))).toBe("Élevée");
    expect(formatRiskLevel(classifyRiskLevel(1610, 1))).toBe("Élevée");
    expect(formatRiskLevel(classifyRiskLevel(1530, 0))).toBe("Modérée");
  });

  it("isole les sessions et empêche les décisions dupliquées ou contradictoires", async () => {
    const user = userEvent.setup();
    render(<ScenarioProvider><ScenarioProbe /></ScenarioProvider>);
    const firstSession = screen.getByTestId("probe-session").textContent;
    await user.click(screen.getByRole("button", { name: "accept" }));
    await user.click(screen.getByRole("button", { name: "accept" }));
    await user.click(screen.getByRole("button", { name: "refuse" }));
    expect(screen.getByTestId("probe-decision")).toHaveTextContent("accepted");
    expect(screen.getByTestId("probe-events")).toHaveTextContent("1");
    await user.click(screen.getByRole("button", { name: "reset" }));
    expect(screen.getByTestId("probe-decision")).toHaveTextContent("none");
    expect(screen.getByTestId("probe-events")).toHaveTextContent("0");
    expect(screen.getByTestId("probe-selected")).toHaveTextContent("5");
    expect(screen.getByTestId("probe-session").textContent).not.toBe(firstSession);
  });

  it("présente seulement les filtres primaires puis révèle période et filtres avancés", async () => {
    const user = userEvent.setup();
    renderWorkflow("/history");
    const searchField = screen.getByLabelText("Rechercher une situation ou une action");
    const searchLabel = screen.getByText("Rechercher une situation ou une action", { selector: "span" });
    expect(searchLabel).toHaveAttribute("data-floating", "false");
    await user.click(searchField);
    expect(searchLabel).toHaveAttribute("data-floating", "true");
    await user.type(searchField, "tension");
    await user.tab();
    expect(searchLabel).toHaveAttribute("data-floating", "true");
    expect(screen.getByRole("button", { name: /Période/ })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Unité" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Décision" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Risque initial" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Période/ }));
    expect(screen.getByLabelText("Du")).toBeInTheDocument();
    expect(screen.getByLabelText("Au")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Plus de filtres/ }));
    expect(screen.getByRole("dialog", { name: "Filtres avancés" })).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Risque initial" }), "critical");
    await user.click(screen.getByRole("button", { name: "Afficher les résultats" }));
    expect(screen.getByRole("button", { name: /Plus de filtres · 1/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Plus de filtres/ }));
    await user.click(screen.getByRole("button", { name: "Réinitialiser" }));
    await user.click(screen.getByRole("button", { name: "Afficher les résultats" }));
    expect(screen.getByRole("button", { name: /Plus de filtres$/ })).toBeInTheDocument();
  });

  it("classe l'historique par date et conserve les paramètres modifiés", () => {
    const makeRow = (createdAt: string, decisionLabel: HistoryRow["decisionLabel"]): HistoryRow => ({
      record: {
        insightId: RESEARCH_INSIGHT.id,
        recommendationId: RESEARCH_INSIGHT.recommendation.id,
        researchSessionId: "research-session-test",
        unitId: "emergency",
        horizonHours: 48,
        decision: decisionLabel === "Refusée" ? "dismissed" : "accepted",
        decisionSource: decisionLabel === "Modifiée puis validée" ? "modified_scenario" : "recommendation",
        originalParameters: { confirmed_discharges: 5 },
        selectedParameters: { confirmed_discharges: decisionLabel === "Modifiée puis validée" ? 3 : 5 },
        createdAt,
        timestamp: createdAt,
      },
      initialRisk: "critical",
      decisionLabel,
      peakDelta: -100,
      hoursDelta: -2,
    });
    const older = makeRow("2026-09-14T09:00:00.000Z", "Acceptée");
    const newer = makeRow("2026-09-14T10:00:00.000Z", "Modifiée puis validée");
    expect(sortHistoryRows([older, newer], "created_desc")).toEqual([newer, older]);
    expect(sortHistoryRows([older, newer], "created_asc")).toEqual([older, newer]);
    expect(newer.record.originalParameters).toEqual({ confirmed_discharges: 5 });
    expect(newer.record.selectedParameters).toEqual({ confirmed_discharges: 3 });
  });

  it("rend chaque onglet Actions interactif, y compris vide", async () => {
    const user = userEvent.setup();
    renderWorkflow("/actions");
    const pending = screen.getByRole("tab", { name: "À traiter 1" });
    const inProgress = screen.getByRole("tab", { name: "En cours 0" });
    const done = screen.getByRole("tab", { name: "Terminées 0" });
    expect(pending).toHaveAttribute("aria-selected", "true");
    await user.click(inProgress);
    expect(screen.getByRole("heading", { name: "Aucune action en cours" })).toBeInTheDocument();
    await user.click(done);
    expect(screen.getByRole("heading", { name: "Aucune action terminée" })).toBeInTheDocument();
    await user.click(pending);
    expect(screen.getByRole("heading", { name: RESEARCH_INSIGHT.recommendation.title })).toBeInTheDocument();
    pending.focus();
    await user.keyboard("{ArrowRight}");
    expect(inProgress).toHaveFocus();
  });

  it("garde la navigation cible et supprime les signaux live trompeurs", () => {
    expect(researchNavigationItems.map((item) => item.label)).toEqual(["Situations", "Actions", "Historique"]);
    render(<App />);
    const body = document.body.textContent ?? "";
    expect(body).toContain("Prototype de recherche");
    expect(body).not.toMatch(/LIVE|REAL|Cityview Medical Center|Sarah Johnson|Operating gain|Legacy TFT|Beds|Staffing|Patient Flow|Insights/);
  });

  it("construit les états de simulation de façon déterministe", () => {
    expect(simulateDischargeScenario(3).summary).toMatchObject({ peak: 1690, peakOccupiedBeds: 67, peakAvailableBeds: 5, peakOccupancyPercent: 93.1, criticalHours: 4 });
    expect(simulateDischargeScenario(5).summary).toMatchObject({ peak: 1610, peakOccupiedBeds: 65, peakAvailableBeds: 7, peakOccupancyPercent: 90.3, criticalHours: 1 });
    expect(simulateDischargeScenario(7).summary).toMatchObject({ peak: 1530, peakOccupiedBeds: 63, peakAvailableBeds: 9, peakOccupancyPercent: 87.5, criticalHours: 0 });
    expect(targetScenarioStateFor(5)).toEqual(scenario.states.recommended);
  });
});
