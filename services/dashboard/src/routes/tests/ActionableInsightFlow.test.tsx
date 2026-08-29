import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import App from "../../App";
import { researchNavigationItems } from "../../app/navigation";
import { ScenarioProvider, useScenarioContext } from "../../domain/ScenarioContext";
import { classifyRiskLevel, formatRiskLevel, formatRiskWindow, RESEARCH_INSIGHT, simulateDischargeScenario } from "../../domain/insights";
import { Actions } from "../Actions";
import { ForecastDetail } from "../ForecastDetail";
import { History } from "../History";
import { Insights } from "../Insights";
import { ModifyInsight } from "../ModifyInsight";

function renderWorkflow(initialEntry = "/insights") {
  return render(
    <ScenarioProvider>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/insights" element={<Insights />} />
          <Route path="/insights/:insightId" element={<Insights />} />
          <Route path="/insights/:insightId/forecast" element={<ForecastDetail />} />
          <Route path="/insights/:insightId/modify" element={<ModifyInsight />} />
          <Route path="/actions" element={<Actions />} />
        </Routes>
      </MemoryRouter>
    </ScenarioProvider>
  );
}

function ScenarioProbe() {
  const { decision, auditEvents, researchSessionId, selectedParameters, setParameter, acceptRecommendation, acceptModifiedScenario, refuseRecommendation, resetResearchScenario } = useScenarioContext();
  return (
    <div>
      <output data-testid="probe-decision">{decision?.decision ?? "none"}</output>
      <output data-testid="probe-events">{auditEvents.length}</output>
      <output data-testid="probe-session">{researchSessionId}</output>
      <output data-testid="probe-selected">{selectedParameters.confirmed_discharges}</output>
      <button type="button" onClick={() => setParameter("confirmed_discharges", 3)}>set-three</button>
      <button type="button" onClick={acceptRecommendation}>accept</button>
      <button type="button" onClick={acceptModifiedScenario}>accept-modified</button>
      <button type="button" onClick={() => refuseRecommendation("Action déjà en cours")}>refuse</button>
      <button type="button" onClick={() => refuseRecommendation("Action déjà en cours", "modified_scenario")}>refuse-modified</button>
      <button type="button" onClick={resetResearchScenario}>reset</button>
    </div>
  );
}

function RiskProbe() {
  return (
    <div>
      {([[1810, 6], [1690, 4], [1610, 1], [1530, 0]] as const).map(([peak, hours]) => (
        <span key={`${peak}-${hours}`} data-testid={`risk-${peak}`}>{formatRiskLevel(classifyRiskLevel(peak, hours))}</span>
      ))}
    </div>
  );
}

describe("actionable insight usability flow", () => {
  it("renders one insight with a tension, recommendation and exactly three decision actions", () => {
    renderWorkflow();

    expect(screen.getByRole("heading", { name: "Tension prévue aux Urgences" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Prioriser 5 sorties confirmées avant 15h" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Exécuter$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Modifier$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Refuser$/ })).toBeInTheDocument();
  });

  it("keeps the same scenario context in forecast and modify details", async () => {
    const user = userEvent.setup();
    const view = renderWorkflow();

    await user.click(screen.getByRole("link", { name: /Voir la prévision détaillée/ }));
    expect(screen.getByText(/Hôpital Démo.*Urgences.*horizon 48h/)).toBeInTheDocument();
    expect(screen.getByText(/Scénario synthétique/)).toBeInTheDocument();

    view.unmount();
    renderWorkflow(`/insights/${RESEARCH_INSIGHT.id}/modify`);
    expect(screen.getByTestId("scenario-context")).toHaveTextContent("Hôpital Démo");
    expect(screen.getByTestId("scenario-context")).toHaveTextContent("Urgences");
    expect(screen.getByRole("spinbutton", { name: "Sorties confirmées avant 15h" })).toHaveValue(5);
  });

  it("executes the recommendation as a recorded human decision", async () => {
    const user = userEvent.setup();
    renderWorkflow();

    await user.click(screen.getByRole("button", { name: /^Exécuter$/ }));
    expect(screen.getByRole("dialog", { name: "Confirmer l'action" })).toBeInTheDocument();
    expect(screen.getByText(/Aucune action n'est exécutée dans un système hospitalier/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirmer l'exécution" }));
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent("Action validée");
    expect(screen.queryByRole("button", { name: /^Exécuter$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Modifier$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Refuser$/ })).not.toBeInTheDocument();
  });

  it("requires a refusal reason and keeps the unresolved insight visible", async () => {
    const user = userEvent.setup();
    renderWorkflow();

    await user.click(screen.getByRole("button", { name: /^Refuser$/ }));
    const confirm = screen.getByRole("button", { name: "Confirmer le refus" });
    expect(confirm).toBeDisabled();
    await user.selectOptions(screen.getByRole("combobox"), "Ressources indisponibles");
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    expect(screen.getByRole("heading", { name: "Tension prévue aux Urgences" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Recommandation refusée");
    expect(screen.getByRole("status")).toHaveTextContent("Ressources indisponibles");
  });

  it("prefills and records a modified scenario with a deterministic impact", async () => {
    const user = userEvent.setup();
    renderWorkflow(`/insights/${RESEARCH_INSIGHT.id}/modify`);

    const input = screen.getByRole("spinbutton", { name: "Sorties confirmées avant 15h" });
    await user.clear(input);
    await user.type(input, "3");
    expect(screen.getByText(/effort opérationnel est réduit/)).toBeInTheDocument();
    expect(screen.getAllByText("1690 SIIPS").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: /Exécuter ce scénario/ }));
    expect(screen.getByRole("heading", { name: "Actions" })).toBeInTheDocument();
    expect(screen.getByText(/scénario accepté/)).toBeInTheDocument();
    expect(screen.getByText(/sorties confirmées avant 15h/)).toBeInTheDocument();
  });

  it("requires a reason when refusing from the modified scenario", async () => {
    const user = userEvent.setup();
    renderWorkflow(`/insights/${RESEARCH_INSIGHT.id}/modify`);

    await user.click(screen.getByRole("button", { name: /^Refuser$/ }));
    const confirm = screen.getByRole("button", { name: "Confirmer le refus" });
    expect(confirm).toBeDisabled();
    await user.selectOptions(screen.getByRole("combobox"), "Action déjà en cours");
    await user.click(confirm);
    expect(screen.getByRole("heading", { name: "Tension prévue aux Urgences" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Action déjà en cours");
  });

  it("keeps the research scenario internally coherent", () => {
    const baseline = simulateDischargeScenario(0).summary;
    const recommended = simulateDischargeScenario(5).summary;
    const custom = simulateDischargeScenario(3).summary;

    expect(baseline.peak).toBeGreaterThan(1600);
    expect(baseline.criticalHours).toBeGreaterThan(0);
    expect(recommended.peak).toBeLessThan(baseline.peak);
    expect(recommended.criticalHours).toBeLessThan(baseline.criticalHours);
    expect(recommended.peak).toBeLessThan(custom.peak);
    expect(custom.peak).toBeLessThan(baseline.peak);
    expect(recommended.criticalHours).toBeLessThan(custom.criticalHours);
    expect(custom.criticalHours).toBeLessThan(baseline.criticalHours);
  });

  it("uses one risk classification for the boundary scenarios and tells the truth about the fixed date", () => {
    render(<RiskProbe />);
    expect(screen.getByTestId("risk-1810")).toHaveTextContent("Critique");
    expect(screen.getByTestId("risk-1690")).toHaveTextContent("Élevée");
    expect(screen.getByTestId("risk-1610")).toHaveTextContent("Élevée");
    expect(screen.getByTestId("risk-1530")).toHaveTextContent("Modérée");
    expect(formatRiskWindow(RESEARCH_INSIGHT.riskWindowStart, RESEARCH_INSIGHT.riskWindowEnd)).toBe("14 septembre · 16h–20h");
  });

  it("enforces terminal, idempotent decisions and isolates a reset research session", async () => {
    const user = userEvent.setup();
    render(<ScenarioProvider><ScenarioProbe /></ScenarioProvider>);
    const firstSession = screen.getByTestId("probe-session").textContent;

    await user.click(screen.getByRole("button", { name: "set-three" }));
    expect(screen.getByTestId("probe-selected")).toHaveTextContent("3");
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

  it("does not attach a stale modified value to an original refusal", async () => {
    const user = userEvent.setup();
    render(<ScenarioProvider><ScenarioProbe /></ScenarioProvider>);

    await user.click(screen.getByRole("button", { name: "set-three" }));
    await user.click(screen.getByRole("button", { name: "refuse" }));
    expect(screen.getByTestId("probe-decision")).toHaveTextContent("dismissed");
    expect(screen.getByTestId("probe-selected")).toHaveTextContent("5");

    await user.click(screen.getByRole("button", { name: "reset" }));
    await user.click(screen.getByRole("button", { name: "set-three" }));
    await user.click(screen.getByRole("button", { name: "refuse-modified" }));
    expect(screen.getByTestId("probe-selected")).toHaveTextContent("3");
  });

  it("explains lower and higher custom effort from deterministic simulation values", async () => {
    const user = userEvent.setup();
    const view = renderWorkflow(`/insights/${RESEARCH_INSIGHT.id}/modify`);
    const input = screen.getByRole("spinbutton", { name: "Sorties confirmées avant 15h" });
    await user.clear(input);
    await user.type(input, "3");
    expect(screen.getByText(/effort opérationnel est réduit ; le bénéfice attendu est aussi moindre/)).toBeInTheDocument();
    view.unmount();

    renderWorkflow(`/insights/${RESEARCH_INSIGHT.id}/modify`);
    const higherInput = screen.getByRole("spinbutton", { name: "Sorties confirmées avant 15h" });
    await user.clear(higherInput);
    await user.type(higherInput, "7");
    expect(screen.getByText(/effort opérationnel augmente ; le bénéfice attendu augmente aussi/)).toBeInTheDocument();
  });

  it("renders a read-only decision table with composed filters, sorting and full modified detail", async () => {
    const user = userEvent.setup();
    render(
      <ScenarioProvider>
        <MemoryRouter initialEntries={["/history"]}>
          <Routes><Route path="/history" element={<><History /><ScenarioProbe /></>} /></Routes>
        </MemoryRouter>
      </ScenarioProvider>
    );

    await user.click(screen.getByRole("button", { name: "set-three" }));
    await user.click(screen.getByRole("button", { name: "accept-modified" }));
    expect(screen.getByRole("columnheader", { name: "Date / heure" })).toBeInTheDocument();
    expect(screen.getAllByText("Modifiée puis validée").length).toBeGreaterThan(0);
    expect(screen.getByRole("combobox", { name: "Trier l'historique" })).toHaveValue("created_desc");

    await user.selectOptions(screen.getByRole("combobox", { name: "Trier l'historique" }), "risk_desc");
    expect(screen.getByRole("combobox", { name: "Trier l'historique" })).toHaveValue("risk_desc");
    await user.selectOptions(screen.getByRole("combobox", { name: "Type de décision" }), "modified");
    await user.selectOptions(screen.getByRole("combobox", { name: "Statut" }), "validated");
    expect(screen.getAllByText("Modifiée puis validée").length).toBeGreaterThan(0);
    await user.selectOptions(screen.getByRole("combobox", { name: "Type de décision" }), "refused");
    expect(screen.getByText("Aucune décision ne correspond aux filtres.")).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Type de décision" }), "modified");
    await user.click(screen.getByRole("row", { name: /Détail Modifiée puis validée/ }));
    expect(screen.getByRole("dialog", { name: "Modifiée puis validée" })).toBeInTheDocument();
    expect(screen.getByText("3 sorties confirmées avant 15h")).toBeInTheDocument();
    expect(screen.getByText("5 sorties confirmées avant 15h")).toBeInTheDocument();
  });

  it("uses only the research navigation and removes live-facing labels", () => {
    expect(researchNavigationItems.map((item) => item.label)).toEqual(["Insights", "Actions", "Historique"]);
    render(<App />);
    const body = document.body.textContent ?? "";
    expect(body).toContain("MODE ÉTUDE UTILISATEUR");
    expect(body).toContain("Hôpital Démo");
    expect(body).not.toMatch(/LIVE|REAL|Cityview Medical Center|Sarah Johnson|Operating gain|Legacy TFT|Beds|Staffing|Patient Flow/);
  });
});
