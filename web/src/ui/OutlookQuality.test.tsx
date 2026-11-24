import { render, screen, within } from "@testing-library/react";
import type { Plan } from "../api/types";
import geriatric from "../fixtures/scenario-geriatrie.json";
import nominal from "../fixtures/scenario-nominal.json";
import { OutlookQuality } from "./OutlookQuality";

it("traces each shadow census to its receipt and omits the panel without a cohort", () => {
  const plan = geriatric.plan as unknown as Plan;
  const { rerender } = render(<OutlookQuality plan={plan} />);
  const panel = screen.getByTestId("flow-shadow");
  expect(within(panel).getByText(/classement des actions utilise le moteur de référence/i)).toBeTruthy();
  for (const [i, w] of plan.shadow_flow!.entries()) {
    const value = panel.querySelector(`[data-src="${plan.plan_id}#/shadow_flow/${i}/mean_occupied"]`);
    expect(value?.getAttribute("data-raw")).toBe(JSON.stringify(w.mean_occupied));
  }
  rerender(<OutlookQuality plan={nominal.plan as unknown as Plan} />);
  expect(screen.queryByTestId("flow-shadow")).toBeNull();
});
