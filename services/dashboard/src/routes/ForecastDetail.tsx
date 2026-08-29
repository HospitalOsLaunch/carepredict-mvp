import { Link } from "react-router-dom";

import { useScenarioContext } from "../domain/ScenarioContext";
import { formatConfidence, formatDateTime, formatRiskLevel, PRESSURE_THRESHOLD_SIIPS } from "../domain/insights";

export function ForecastDetail() {
  const { insight, simulation } = useScenarioContext();
  const points = simulation.points;
  return (
    <section className="space-y-6" aria-labelledby="forecast-detail-title">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link to={`/insights/${insight.id}`} className="text-control text-brand-primary">← Retour à l'insight</Link>
          <h1 id="forecast-detail-title" className="text-screen mt-3 text-text-strong">Prévision détaillée</h1>
          <p className="text-caption mt-2">{insight.context.hospitalLabel} · {insight.context.serviceLabel} · horizon {insight.context.horizonHours}h</p>
        </div>
        <span className="rounded-full border border-border-subtle bg-bg-card px-3 py-2 text-badge text-text-muted">Scénario synthétique</span>
      </header>
      <div className="grid gap-4 sm:grid-cols-4">
        <ForecastMetric label="Pic prévu" value={`${insight.peakPressureSiips} SIIPS`} />
        <ForecastMetric label="Temps du pic" value="T+16h" />
        <ForecastMetric label="Heures en tension" value={`${insight.criticalHours} h`} />
        <ForecastMetric label="Confiance" value={formatConfidence(insight.confidence)} />
      </div>
      <article className="rounded-card border border-border-subtle bg-bg-card p-6 shadow-card" aria-labelledby="forecast-chart-title">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-card-label text-brand-primary">Pression SIIPS</p>
            <h2 id="forecast-chart-title" className="text-section mt-2 text-lg text-text-strong">Tension prévue · {insight.context.serviceLabel}</h2>
          </div>
          <span className="text-caption">Seuil critique : {PRESSURE_THRESHOLD_SIIPS} SIIPS</span>
        </div>
        <div className="mt-6 space-y-3" aria-label="Courbe de prévision SIIPS">
          {points.map((point) => <ForecastBar key={point.hour} hour={point.hour} value={point.baseline} />)}
        </div>
        <div className="mt-6 flex flex-wrap gap-5 text-caption"><span><i className="mr-2 inline-block h-2 w-2 rounded-full bg-status-critical" />Prévision</span><span>Fenêtre de risque : {formatDateTime(insight.riskWindowStart)}–{formatDateTime(insight.riskWindowEnd)}</span><span>Niveau : {formatRiskLevel(insight.riskLevel)}</span></div>
      </article>
      <details className="rounded-card border border-border-subtle bg-bg-card p-5 shadow-card"><summary className="cursor-pointer text-body-strong text-text-strong">Comment cette prévision est-elle calculée ?</summary><p className="text-caption mt-3">Le scénario de recherche utilise une fixture synthétique déterministe. Les détails techniques restent séparés de la décision.</p></details>
    </section>
  );
}

function ForecastMetric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-card border border-border-subtle bg-bg-card p-4 shadow-card"><p className="text-caption">{label}</p><p className="numeric-tabular mt-2 text-section text-text-strong">{value}</p></div>;
}

function ForecastBar({ hour, value }: { hour: number; value: number }) {
  const width = Math.min(100, Math.round((value / 2000) * 100));
  return <div className="flex items-center gap-3"><span className="numeric-tabular w-12 text-right text-caption">T+{hour}h</span><div className="h-8 flex-1 rounded-lg bg-gauge-track"><div className="flex h-full items-center rounded-lg bg-status-critical/80 px-3 text-badge text-white" style={{ width: `${width}%`, minWidth: "4rem" }}>{value} SIIPS</div></div></div>;
}
