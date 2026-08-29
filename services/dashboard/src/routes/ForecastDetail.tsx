import { Link } from "react-router-dom";

import { useScenarioContext } from "../domain/ScenarioContext";
import { classifyRiskLevel, formatConfidence, formatRiskLevel, simulateDischargeScenario } from "../domain/insights";
import { HCL_TARGET_PRODUCT_RESEARCH_SCENARIO as scenario } from "../research/hclTargetScenario";
import { ScenarioTrajectoryChart } from "../research/ScenarioTrajectoryChart";

export function ForecastDetail() {
  const { insight, simulation, selectedUnit, horizonHours } = useScenarioContext();
  const baseline = simulateDischargeScenario(0).summary;
  const horizonPeak = simulation.points.reduce<(typeof simulation.points)[number] | undefined>((peak, point) => !peak || point.baseline > peak.baseline ? point : peak, undefined);
  const horizonCriticalHours = horizonHours >= 12 ? baseline.criticalHours : 0;
  const risk = classifyRiskLevel(horizonPeak?.baseline ?? baseline.peak, horizonCriticalHours);

  if (selectedUnit.id !== "emergency") {
    return <section className="mx-auto max-w-[1180px] space-y-8"><Link to="/situations" className="text-control text-brand-primary">← Retour aux situations</Link><div className="border-y border-border-subtle bg-bg-card py-16 text-center"><h1 className="text-xl font-semibold text-text-strong">Aucune évolution prioritaire pour {selectedUnit.label}.</h1><p className="mt-3 text-body-copy">Les signaux simulés restent dans la zone de vigilance normale sur {horizonHours} h.</p></div></section>;
  }
  return (
    <section className="mx-auto max-w-[1180px] space-y-8" aria-labelledby="forecast-detail-title">
      <header className="flex flex-wrap items-end justify-between gap-6 border-b border-border-subtle pb-6">
        <div>
          <Link to={`/situations/${insight.id}`} className="text-control text-brand-primary">← Retour à la situation</Link>
          <p className="text-card-label mt-5 text-brand-primary">{selectedUnit.label} · {scenario.scenarioDateLabel} · horizon {horizonHours} h</p>
          <h1 id="forecast-detail-title" className="mt-2 text-3xl font-semibold tracking-tight text-text-strong">Évolution prévue</h1>
        </div>
        <span className="text-caption">{simulation.points.length} points déterministes</span>
      </header>

      <div className="grid divide-y divide-border-subtle border-y border-border-subtle sm:grid-cols-4 sm:divide-x sm:divide-y-0">
        <ForecastMetric label="Fenêtre critique" value={horizonHours >= 12 ? "16h–20h" : "Hors horizon"} />
        <ForecastMetric label="Pic sur l'horizon" value={horizonPeak?.timeLabel ?? scenario.referenceTime} />
        <ForecastMetric label="Temps en tension" value={`${horizonCriticalHours} h`} />
        <ForecastMetric label="Confiance" value={formatConfidence(insight.confidence)} />
      </div>

      <article className="border border-border-subtle bg-bg-card p-7 shadow-card" aria-labelledby="forecast-chart-title">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border-subtle pb-5">
          <div><p className="text-card-label text-brand-primary">Trajectoire opérationnelle</p><h2 id="forecast-chart-title" className="mt-2 text-xl font-semibold text-text-strong">Tension future · {scenario.serviceLabel}</h2></div>
          <div className="text-right"><p className="text-card-label">Risque</p><p className="mt-2 text-body-strong text-status-critical">{formatRiskLevel(risk)}</p></div>
        </div>
        <div className="mt-6"><ScenarioTrajectoryChart points={simulation.points} showCustom={false} ariaLabel="Évolution prévue de la tension opérationnelle" /></div>
        <p className="mt-4 text-caption">Le seuil de 1 600 SIIPS est un seuil du scénario de recherche, pas une valeur hospitalière universelle.</p>
      </article>

      <section aria-labelledby="forecast-signals-title">
        <div className="flex items-end justify-between border-b border-border-subtle pb-3"><div><p className="text-card-label text-brand-primary">État au pic</p><h2 id="forecast-signals-title" className="mt-2 text-xl font-semibold text-text-strong">Signaux opérationnels</h2></div><span className="text-caption">estimations du scénario</span></div>
        <div className="grid divide-y divide-border-subtle sm:grid-cols-2 sm:divide-x sm:divide-y-0 lg:grid-cols-4">
          <ForecastMetric label="Occupation au pic" value={`${baseline.peakOccupancyPercent} %`} />
          <ForecastMetric label="Lits disponibles au pic" value={`${baseline.peakAvailableBeds} / ${scenario.bedCapacity}`} />
          <ForecastMetric label="Flux net avant le pic" value={`+${scenario.expectedArrivalsBeforePeak - scenario.expectedBaselineExitsBeforePeak} patients`} />
          <ForecastMetric label="Charge en soins au pic" value={`${baseline.peakSiips} SIIPS`} />
        </div>
      </section>

      <details className="border-t border-border-subtle pt-5"><summary className="cursor-pointer text-body-strong text-text-strong">Comment cette évolution est-elle construite ?</summary><p className="mt-3 max-w-2xl text-body-copy">Les trajectoires sont produites à partir d'un scénario de recherche déterministe. Les zones d'incertitude indiquent une plage estimée, pas une garantie de résultat.</p></details>
    </section>
  );
}

function ForecastMetric({ label, value }: { label: string; value: string }) {
  return <div className="px-5 py-5 first:pl-0 last:pr-0"><p className="text-caption">{label}</p><p className="numeric-tabular mt-2 text-xl font-semibold tracking-tight text-text-strong">{value}</p></div>;
}
