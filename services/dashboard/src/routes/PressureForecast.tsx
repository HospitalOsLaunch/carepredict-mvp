import { RoutePlaceholder } from "./RoutePlaceholder";

export function PressureForecast() {
  return (
    <RoutePlaceholder
      title="Pressure Forecast"
      subtitle="Forecast route for multi-horizon pressure, unit heatmap and driver attribution."
      realData="/simulate/hospital-world can provide a single-service SIIPS trajectory when supplied history and actions."
      mockData="Multi-unit heatmap, pressure drivers, saturation thresholds and recommended actions."
    />
  );
}
