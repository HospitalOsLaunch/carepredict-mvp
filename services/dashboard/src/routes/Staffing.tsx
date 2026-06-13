import { RoutePlaceholder } from "./RoutePlaceholder";

export function Staffing() {
  return (
    <RoutePlaceholder
      title="Staffing"
      subtitle="Coverage and redeployment route for staffing huddles."
      realData="No staffing dashboard endpoint exists today."
      mockData="FTE requirements, coverage matrix, fatigue risk, float pool and reallocation actions."
    />
  );
}
