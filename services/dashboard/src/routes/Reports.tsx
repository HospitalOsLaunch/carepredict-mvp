import { RoutePlaceholder } from "./RoutePlaceholder";

export function Reports() {
  return (
    <RoutePlaceholder
      title="Reports"
      subtitle="Operational reporting route for historical trends and exports."
      realData="No report-generation endpoint exists today."
      mockData="Trend cards, report downloads, benchmark trends and scheduled delivery table."
    />
  );
}
