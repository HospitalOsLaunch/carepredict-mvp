import { useMemo, useState } from "react";

import type { ChartPoint, ServiceOption } from "../api/types";
import { ChargeChart } from "../components/ChargeChart";
import { ConfidenceLegend } from "../components/ConfidenceLegend";
import { CurrentVsPredicted } from "../components/CurrentVsPredicted";
import { ServiceSelector } from "../components/ServiceSelector";
import { TopFeatures } from "../components/TopFeatures";
import { usePrediction } from "../hooks/usePrediction";
import "../styles/app.css";

const SERVICES: ServiceOption[] = [
  { id: "urg-001", label: "Urgences", hospitalId: "hosp-001", specialty: "Urgences", currentCharge: 62 },
  { id: "card-001", label: "Cardiologie", hospitalId: "hosp-001", specialty: "Cardiologie", currentCharge: 54 },
  {
    id: "med-001",
    label: "Médecine interne",
    hospitalId: "hosp-001",
    specialty: "Médecine",
    currentCharge: 49
  }
];

export function LegacyDashboard() {
  const [selectedServiceId, setSelectedServiceId] = useState(SERVICES[0].id);
  const selectedService = SERVICES.find((service) => service.id === selectedServiceId) ?? SERVICES[0];
  const timestamp = useMemo(() => new Date().toISOString(), [selectedServiceId]);
  const request = {
    service_id: selectedService.id,
    hospital_id: selectedService.hospitalId,
    timestamp,
    planned_interventions: [
      { type: "discharge" as const, scheduled_at: addHours(timestamp, 3), count: 3 },
      { type: "surgery" as const, scheduled_at: addHours(timestamp, 6), count: 2 }
    ]
  };
  const prediction = usePrediction(request);

  const chartData = useMemo(
    () =>
      buildChartData(
        timestamp,
        selectedService.currentCharge,
        prediction.data?.value,
        prediction.data?.lower_90,
        prediction.data?.upper_90
      ),
    [prediction.data, selectedService.currentCharge, timestamp]
  );

  return (
    <main className="dashboard-shell">
      <header className="dashboard-header">
        <div>
          <span className="brand-mark">Hospitalos</span>
          <h1>CarePredict Legacy</h1>
        </div>
        <label className="field compact">
          <span>Établissement</span>
          <select value="hosp-001" onChange={() => undefined}>
            <option value="hosp-001">Hospitalos Paris Nord</option>
          </select>
        </label>
      </header>

      <section className="toolbar">
        <ServiceSelector services={SERVICES} selectedServiceId={selectedServiceId} onChange={setSelectedServiceId} />
        <span className="service-meta">{selectedService.specialty}</span>
      </section>

      {prediction.isPending ? <div className="skeleton" aria-label="Chargement" /> : null}
      {prediction.isError ? <div className="error-panel">Impossible de récupérer la prédiction.</div> : null}
      {prediction.data ? (
        <>
          <CurrentVsPredicted current={selectedService.currentCharge} predicted={prediction.data.value} />
          <ChargeChart data={chartData} />
          <div className="insight-grid">
            <ConfidenceLegend coverage={prediction.data.coverage} />
            <TopFeatures features={prediction.data.attention_weights.top_features} />
          </div>
        </>
      ) : null}
    </main>
  );
}

function buildChartData(
  timestamp: string,
  current: number,
  predicted?: number,
  lower?: number,
  upper?: number
): ChartPoint[] {
  const now = new Date(timestamp);
  const history: ChartPoint[] = Array.from({ length: 24 }, (_, index) => {
    const date = new Date(now.getTime() - (23 - index) * 60 * 60 * 1000);
    return {
      timestamp: date.toISOString(),
      historical: current - 4 + Math.sin(index / 3) * 3
    };
  });
  const future: ChartPoint[] = Array.from({ length: 12 }, (_, index) => {
    const date = new Date(now.getTime() + (index + 1) * 60 * 60 * 1000);
    const ratio = (index + 1) / 12;
    return {
      timestamp: date.toISOString(),
      predicted: predicted === undefined ? undefined : current + (predicted - current) * ratio,
      lower_90: lower,
      upper_90: upper
    };
  });
  return [...history, ...future];
}

function addHours(timestamp: string, hours: number): string {
  const date = new Date(timestamp);
  date.setHours(date.getHours() + hours);
  return date.toISOString();
}
