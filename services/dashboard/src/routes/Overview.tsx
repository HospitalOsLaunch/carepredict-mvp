import { RoutePlaceholder } from "./RoutePlaceholder";

export function Overview() {
  return (
    <RoutePlaceholder
      title="Operational Pressure Forecast"
      subtitle="Executive overview route reserved for the HospitalOS command-center composition."
      realData="Health/readiness only today; v2 Overview must not consume the legacy /predict/charge endpoint."
      mockData="Hospital pressure score, unit pressure table, operational KPIs and recommended action cards."
    />
  );
}
