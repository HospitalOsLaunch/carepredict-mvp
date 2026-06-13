import { RoutePlaceholder } from "./RoutePlaceholder";

export function Beds() {
  return (
    <RoutePlaceholder
      title="Beds"
      subtitle="Capacity management route for occupancy, blockers, admissions and discharge readiness."
      realData="No bed-management endpoint exists today."
      mockData="Occupancy KPIs, bed status by unit, incoming queue, bottlenecks and discharge readiness."
    />
  );
}
