import { RoutePlaceholder } from "./RoutePlaceholder";

export function OrEd() {
  return (
    <RoutePlaceholder
      title="OR / ED Command Center"
      subtitle="Operating room and emergency department command route."
      realData="No OR/ED endpoint exists today."
      mockData="OR schedule, ED arrivals, boarding, bottlenecks and coordinated actions."
    />
  );
}
