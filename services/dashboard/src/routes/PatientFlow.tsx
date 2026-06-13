import { RoutePlaceholder } from "./RoutePlaceholder";

export function PatientFlow() {
  return (
    <RoutePlaceholder
      title="Patient Flow"
      subtitle="ED-to-discharge throughput route."
      realData="No patient-flow endpoint exists today."
      mockData="Flow funnel, bottlenecks, discharge opportunities and throughput trends."
    />
  );
}
