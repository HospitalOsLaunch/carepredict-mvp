import { RoutePlaceholder } from "./RoutePlaceholder";

export function Simulation() {
  return (
    <RoutePlaceholder
      title="Simulation"
      subtitle="Counterfactual scenario builder route; this is the first v2 screen planned for real backend wiring."
      realData="POST /simulate/hospital-world with SimulationRequest and SimulationResponse."
      mockData="Scenario ranking, operational impact summaries and baseline cards until the full screen lands."
    />
  );
}
