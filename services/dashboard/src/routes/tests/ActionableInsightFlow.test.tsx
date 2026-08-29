import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import App from "../../App";
import { researchNavigationItems } from "../../app/navigation";
import { ScenarioProvider, useScenarioContext } from "../../domain/ScenarioContext";
import { classifyRiskLevel, formatRiskLevel, RESEARCH_INSIGHT, simulateDischargeScenario } from "../../domain/insights";
import { HCL_TARGET_PRODUCT_RESEARCH_SCENARIO as scenario, targetScenarioStateFor } from "../../research/hclTargetScenario";
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
        </Routes>
      </MemoryRouter>
    </ScenarioProvider>
  );
}

function ScenarioProbe() {
  const { decision, auditEvents, researchSessionId, selectedParameters, setParameter, acceptRecommendation, acceptModifiedScenario, refuseRecommendation, resetResearchScenario } = useScenarioContext();
  return <div><output data-testid="probe-decision">{decision?.decision ?? "none"}</output><output data-testid="probe-events">{auditEvents.length}</output><output data-testid="probe-session">{researchSessionId}</output><output data-testid="probe-selected">{selectedParameters.confirmed_discharges}</output><button type="button" onClick={() => setParameter("confirmed_discharges", 3)}>set-three</button><button type="button" onClick={acceptRecommendation}>accept</button><button type="button" onClick={acceptModifiedScenario}>accept-modified</button><button type="button" onClick={() => refuseRecommendation("Action déjà engagée")}>refuse</button><button type="button" onClick={() => refuseRecommendation("Action déjà engagée", "modified_scenario")}>refuse-modified</button><button type="button" onClick={resetResearchScenario}>reset</button></div>;
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
    expect(scenario.metricDefinitions.every((metric) => metric.provenance === "synthetic_research" && metric.researchCandidate)).toBe(true);
  });

  it("présente une Situation opérationnelle avec signaux, recommandation et trois décisions", () => {
    renderWorkflow();
    expect(screen.getByRole("heading", { name: "Situations" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Tension critique prévue de 16h à 20h" })).toBeInTheDocument();
    expect(screen.getByText("Occupation prévue au pic")).toBeInTheDocument();
    expect(screen.getByText("Lits disponibles au pic")).toBeInTheDocument();
    expect(screen.getByText("Flux net attendu")).toBeInTheDocument();
    expect(screen.getByText("Couverture prévue")).toBeInTheDocument();
    expect(screen.getByText("Charge en soins au pic")).toBeInTheDocument();
    expect(screen.getByText("Capacité d'aval")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Avancer 5 sorties confirmées avant 15h" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Exécuter$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Modifier$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Refuser$/ })).toBeInTheDocument();
    expect(screen.queryByText("Pression SIIPS")).not.toBeInTheDocument();
  });

  it("conserve le même contexte dans Situation, évolution et option", async () => {
    const user = userEvent.setup();
    renderWorkflow();
    await user.click(screen.getByRole("link", { name: /Voir l'évolution prévue/ }));
    expect(screen.getByText(/Urgences.*horizon 48 h/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Évolution prévue" })).toBeInTheDocument();
    expect(screen.getByText(/Urgences · 14 septembre · horizon 48 h/)).toBeInTheDocument();
  });

  it("valide une action humaine sans exécution hospitalière et reste terminale", async () => {
    const user = userEvent.setup();
    renderWorkflow();
    await user.click(screen.getByRole("button", { name: /^Exécuter$/ }));
    expect(screen.getByRole("dialog", { name: "Valider cette action" })).toBeInTheDocument();
    expect(screen.getByText(/aucune action n'est exécutée dans un système hospitalier/i)).toBeInTheDocument();
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

  it("préremplit, simule et explique les options 3, 5 et 7", async () => {
    const user = userEvent.setup();
    renderWorkflow(`/situations/${RESEARCH_INSIGHT.id}/modify`);
    const input = screen.getByRole("spinbutton", { name: "Sorties à avancer avant 15h" });
    expect(input).toHaveValue(5);
    expect(screen.getByText(/Votre option correspond à la recommandation/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^3$/ }));
    expect(screen.getByText(/effort opérationnel réduit de 2 sorties/)).toBeInTheDocument();
    expect(screen.getByText(/bénéfice attendu est aussi réduit/)).toBeInTheDocument();
    expect(screen.getAllByText("1690 SIIPS").length).toBeGreaterThan(0);
    expect(screen.getByText("93.1 %")).toBeInTheDocument();
    expect(screen.getByText("5", { selector: "td" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^7$/ }));
    expect(screen.getByText(/2 sorties supplémentaires/)).toBeInTheDocument();
    expect(screen.getByText(/bénéfice attendu augmente/)).toBeInTheDocument();
    expect(screen.getAllByText("1530 SIIPS").length).toBeGreaterThan(0);
    expect(screen.getByText("87.5 %")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "0 h" })).toBeInTheDocument();
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
    await user.click(screen.getByRole("button", { name: "set-three" }));
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

  it("enregistre séparément refus original et refus d'une option modifiée", async () => {
    const user = userEvent.setup();
    render(<ScenarioProvider><ScenarioProbe /></ScenarioProvider>);
    await user.click(screen.getByRole("button", { name: "set-three" }));
    await user.click(screen.getByRole("button", { name: "refuse" }));
    expect(screen.getByTestId("probe-selected")).toHaveTextContent("5");
    await user.click(screen.getByRole("button", { name: "reset" }));
    await user.click(screen.getByRole("button", { name: "set-three" }));
    await user.click(screen.getByRole("button", { name: "refuse-modified" }));
    expect(screen.getByTestId("probe-selected")).toHaveTextContent("3");
  });

  it("présente Actions comme file de travail et Historique comme journal en lecture seule", async () => {
    const user = userEvent.setup();
    render(<ScenarioProvider><MemoryRouter initialEntries={["/history"]}><Routes><Route path="/history" element={<><History /><ScenarioProbe /></>} /></Routes></MemoryRouter></ScenarioProvider>);
    await user.click(screen.getByRole("button", { name: "set-three" }));
    await user.click(screen.getByRole("button", { name: "accept-modified" }));
    expect(screen.getByRole("columnheader", { name: "Service" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Insight / tension" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Date / heure" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Recommandation initiale" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Scénario retenu" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Motif" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Statut" })).toBeInTheDocument();
    expect(screen.getAllByText("Modifiée puis validée").length).toBeGreaterThan(0);
    expect(screen.getByRole("combobox", { name: "Trier l'historique" })).toHaveValue("created_desc");
    await user.selectOptions(screen.getByRole("combobox", { name: "Trier l'historique" }), "risk_desc");
    expect(screen.getByRole("combobox", { name: "Trier l'historique" })).toHaveValue("risk_desc");
    await user.selectOptions(screen.getByRole("combobox", { name: "Risque initial" }), "critical");
    await user.click(screen.getByRole("tab", { name: "Refusées" }));
    expect(screen.getByText("Aucune décision ne correspond aux filtres.")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Modifiées" }));
    await user.click(screen.getByRole("row", { name: /Détail Modifiée puis validée/ }));
    expect(screen.getByRole("dialog", { name: "Modifiée puis validée" })).toBeInTheDocument();
    expect(screen.getByText("3 sorties confirmées avant 15h")).toBeInTheDocument();
    expect(screen.getByText("5 sorties confirmées avant 15h")).toBeInTheDocument();
  });

  it("classe l'historique par décision la plus récente et compose les filtres", async () => {
    const makeRow = (createdAt: string, decision: HistoryRow["decisionLabel"]): HistoryRow => ({
      record: {
        insightId: RESEARCH_INSIGHT.id,
        recommendationId: RESEARCH_INSIGHT.recommendation.id,
        researchSessionId: "research-session-test",
        decision: decision === "Refusée" ? "dismissed" : "accepted",
        decisionSource: decision === "Modifiée puis validée" ? "modified_scenario" : "recommendation",
        originalParameters: { confirmed_discharges: 5 },
        selectedParameters: { confirmed_discharges: decision === "Modifiée puis validée" ? 3 : 5 },
        createdAt,
        timestamp: createdAt
      },
      initialRisk: "critical",
      decisionLabel: decision,
      statusLabel: decision === "Refusée" ? "Refusée" : "Décidée",
      peakDelta: -100,
      hoursDelta: -2
    });
    const older = makeRow("2026-09-14T09:00:00.000Z", "Acceptée");
    const newer = makeRow("2026-09-14T10:00:00.000Z", "Modifiée puis validée");
    expect(sortHistoryRows([older, newer], "created_desc")[0]).toBe(newer);
    expect(sortHistoryRows([older, newer], "created_desc")[1]).toBe(older);

    const user = userEvent.setup();
    render(<ScenarioProvider><MemoryRouter initialEntries={["/history"]}><Routes><Route path="/history" element={<History />} /></Routes></MemoryRouter></ScenarioProvider>);
    await user.click(screen.getByRole("combobox", { name: "Statut" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Statut" }), "recorded");
    await user.selectOptions(screen.getByRole("combobox", { name: "Risque initial" }), "critical");
    expect(screen.getByRole("combobox", { name: "Statut" })).toHaveValue("recorded");
    expect(screen.getByRole("combobox", { name: "Risque initial" })).toHaveValue("critical");
  });

  it("garde la navigation de recherche cible et supprime les signaux live trompeurs", () => {
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
