import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import App from "../../App";
import { researchNavigationItems } from "../../app/navigation";
import { ScenarioProvider } from "../../domain/ScenarioContext";
import { RESEARCH_INSIGHT, simulateDischargeScenario } from "../../domain/insights";
import { Actions } from "../Actions";
import { ForecastDetail } from "../ForecastDetail";
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
    expect(screen.getByText(/La simulation est recalculée pour 3 sorties/)).toBeInTheDocument();
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

  it("uses only the research navigation and removes live-facing labels", () => {
    expect(researchNavigationItems.map((item) => item.label)).toEqual(["Insights", "Actions", "Historique"]);
    render(<App />);
    const body = document.body.textContent ?? "";
    expect(body).toContain("MODE ÉTUDE UTILISATEUR");
    expect(body).toContain("Hôpital Démo");
    expect(body).not.toMatch(/LIVE|REAL|Cityview Medical Center|Sarah Johnson|Operating gain|Legacy TFT|Beds|Staffing|Patient Flow/);
  });
});
