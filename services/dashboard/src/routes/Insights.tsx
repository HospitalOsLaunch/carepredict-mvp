import { useState } from "react";
import { ArrowRight, Check, X } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { useScenarioContext } from "../domain/ScenarioContext";
import {
  classifyRiskLevel,
  formatConfidence,
  formatRiskLevel,
  simulateDischargeScenario,
  PRESSURE_THRESHOLD_SIIPS
} from "../domain/insights";
import {
  classifySiipsWorkload,
  formatWorkloadLevel,
  HCL_TARGET_PRODUCT_RESEARCH_SCENARIO as scenario
} from "../research/hclTargetScenario";
import { ScenarioTrajectoryChart } from "../research/ScenarioTrajectoryChart";

export const REFUSAL_REASONS = [
  "Ressources indisponibles",
  "Action non pertinente",
  "Action déjà engagée",
  "Contrainte organisationnelle",
  "Impact insuffisant",
  "Autre"
];

export function Situations() {
  const navigate = useNavigate();
  const { insight, simulation, decision, selectedUnit, horizonHours, acceptRecommendation, refuseRecommendation } = useScenarioContext();
  const baseline = simulateDischargeScenario(0).summary;
  const recommended = simulateDischargeScenario(scenario.recommendation.recommendedValue).summary;
  const risk = classifyRiskLevel(baseline.peak, baseline.criticalHours);
  const [dialog, setDialog] = useState<"execute" | "refuse" | null>(null);
  const [reason, setReason] = useState("");
  const workloadLevel = formatWorkloadLevel(classifySiipsWorkload(baseline.peakSiips));
  const hasActiveSituation = selectedUnit.id === "emergency" && horizonHours >= 12;

  const closeDialog = () => {
    setDialog(null);
    setReason("");
  };

  if (!hasActiveSituation) {
    return (
      <section className="mx-auto max-w-[1180px] space-y-8" aria-labelledby="situations-title">
        <header className="border-b border-border-subtle pb-6">
          <p className="text-card-label text-brand-primary">{selectedUnit.label.toUpperCase()} · HORIZON {horizonHours} H</p>
          <h1 id="situations-title" className="text-screen mt-3 text-3xl text-text-strong">Situations</h1>
        </header>
        <div className="border-y border-border-subtle bg-bg-card py-16 text-center">
          <h2 className="text-xl font-semibold text-text-strong">Aucune situation prioritaire sur l’horizon sélectionné.</h2>
          <p className="mx-auto mt-3 max-w-xl text-body-copy">Les signaux simulés ne dépassent pas les seuils de vigilance définis pour ce scénario.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="mx-auto max-w-[1180px] space-y-8" aria-labelledby="situations-title">
      <header className="flex flex-wrap items-end justify-between gap-6 border-b border-border-subtle pb-6">
        <div>
          <p className="text-card-label text-brand-primary">{scenario.serviceLabel.toUpperCase()} · {scenario.scenarioDateLabel.toUpperCase()}</p>
          <h1 id="situations-title" className="text-screen mt-3 text-3xl text-text-strong">Situations</h1>
          <p className="mt-2 text-body-copy">1 situation requiert votre attention</p>
        </div>
        <div className="text-right">
          <p className="text-card-label text-status-critical">État opérationnel</p>
          <p className="mt-2 text-body-strong text-text-strong">{scenario.serviceLabel} · fenêtre {scenario.riskWindow.start}–{scenario.riskWindow.end}</p>
        </div>
      </header>

      <article className="overflow-hidden border border-border-subtle bg-bg-card shadow-card" aria-labelledby="primary-situation-title">
        <div className="grid gap-8 border-b border-border-subtle bg-status-critical/[0.04] p-7 lg:grid-cols-[1fr_auto] lg:items-end">
          <div>
            <p className="text-card-label text-status-critical">Tension opérationnelle</p>
            <h2 id="primary-situation-title" className="mt-3 max-w-2xl text-3xl font-semibold tracking-tight text-text-strong">{insight.title}</h2>
            <p className="mt-3 text-body-copy">Pic attendu vers {scenario.expectedPeakTime}. La situation reste à décider par l'équipe.</p>
          </div>
          <div className="flex items-end gap-6 lg:text-right">
            <div><p className="text-card-label">Risque</p><p className="mt-2 text-xl font-semibold text-status-critical">{formatRiskLevel(risk)}</p></div>
            <div><p className="text-card-label">Confiance</p><p className="mt-2 text-xl font-semibold text-text-strong">{formatConfidence(insight.confidence)}</p></div>
          </div>
        </div>

        <div className="grid divide-y divide-border-subtle border-b border-border-subtle sm:grid-cols-4 sm:divide-x sm:divide-y-0">
          <PrimaryMetric label="Temps en tension" value={`${baseline.criticalHours} h`} />
          <PrimaryMetric label="Occupation prévue au pic" value={`${baseline.peakOccupancyPercent} %`} />
          <PrimaryMetric label="Lits disponibles au pic" value={`${baseline.peakAvailableBeds}`} suffix={` / ${scenario.bedCapacity}`} />
          <PrimaryMetric label="Charge en soins au pic" value={`${baseline.peakSiips}`} suffix=" SIIPS" detail={workloadLevel} />
        </div>

        <div className="border-b border-border-subtle p-7">
          <div className="grid gap-8 lg:grid-cols-[0.85fr_1.15fr]">
            <section aria-labelledby="associated-signals-title">
              <p id="associated-signals-title" className="text-card-label text-brand-primary">Signaux associés à la tension</p>
              <ul className="mt-4 space-y-3 text-body-copy">
                {insight.drivers.slice(0, 4).map((driver) => <li key={driver.id} className="border-l-2 border-brand-primary/50 pl-4"><span className="font-medium text-text-strong">{driver.label}</span><span className="mt-1 block text-caption">{driver.explanation}</span></li>)}
              </ul>
            </section>
            <RecommendationBlock baseline={baseline} recommended={recommended} recommendation={insight.recommendation} onExecute={() => setDialog("execute")} onModify={() => navigate(`/situations/${insight.id}/modify`)} onRefuse={() => setDialog("refuse")} decision={decision} />
          </div>
        </div>

        <div className="grid gap-8 p-7 lg:grid-cols-[1.3fr_0.7fr]">
          <div>
            <div className="flex items-end justify-between gap-4">
              <div><p className="text-card-label text-brand-primary">Évolution prévue</p><h3 className="mt-2 text-section text-lg text-text-strong">Trajectoire de tension · {scenario.serviceLabel}</h3></div>
              <span className="text-caption">Horizon {horizonHours} h</span>
            </div>
            <div className="mt-5"><ScenarioTrajectoryChart points={simulation.points} showCustom={false} ariaLabel="Trajectoire de tension opérationnelle et charge en soins" /></div>
          </div>
          <section className="border-l-0 border-border-subtle lg:border-l lg:pl-7" aria-labelledby="signals-title">
            <p id="signals-title" className="text-card-label text-brand-primary">Signaux opérationnels</p>
            <div className="mt-4 divide-y divide-border-subtle">
              <Signal label="Occupation prévue" value={`${baseline.peakOccupancyPercent} %`} detail={`${baseline.peakOccupiedBeds} / ${scenario.bedCapacity} lits`} />
              <Signal label="Lits disponibles" value={`${baseline.peakAvailableBeds} / ${scenario.bedCapacity}`} detail="au pic prévu" />
              <Signal label="Flux net attendu" value={`+${scenario.expectedArrivalsBeforePeak - scenario.expectedBaselineExitsBeforePeak} patients`} detail={`${scenario.expectedArrivalsBeforePeak} entrées · ${scenario.expectedBaselineExitsBeforePeak} sorties`} />
              <Signal label="Couverture prévue" value={`${Math.abs(baseline.staffingGapPeak)} IDE sous le besoin estimé`} detail="16h–20h" />
              <Signal label="Charge en soins" value={`${baseline.peakSiips} SIIPS`} detail={`${workloadLevel} · au pic prévu`} />
              <Signal label="Capacité d'aval" value={baseline.downstreamCapacity[0].toUpperCase() + baseline.downstreamCapacity.slice(1)} detail="signal à surveiller" />
            </div>
          </section>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-border-subtle px-7 py-4">
          <span className="text-caption">Scénario de recherche · données simulées</span>
          <Link className="inline-flex items-center gap-2 text-control text-brand-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" to={`/situations/${insight.id}/forecast`}>Voir l'évolution prévue <ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>
        </div>
      </article>

      {dialog ? <DecisionDialog mode={dialog} insight={insight} baseline={baseline} recommended={recommended} reason={reason} onReasonChange={setReason} onClose={closeDialog} onConfirm={() => { if (dialog === "execute") acceptRecommendation(); else if (reason) refuseRecommendation(reason); closeDialog(); }} canConfirm={dialog === "execute" || Boolean(reason)} /> : null}
    </section>
  );
}

export const Insights = Situations;

function PrimaryMetric({ label, value, suffix = "", detail }: { label: string; value: string; suffix?: string; detail?: string }) {
  return <div className="px-6 py-5 first:pl-7 last:pr-7"><p className="text-caption">{label}</p><p className="numeric-tabular mt-2 text-2xl font-semibold tracking-tight text-text-strong">{value}<span className="text-base font-normal text-text-muted">{suffix}</span></p>{detail ? <p className="mt-1 text-body-strong text-status-high" title="Niveau qualitatif utilisé dans ce scénario de recherche.">{detail}</p> : null}</div>;
}

function Signal({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="flex items-baseline justify-between gap-4 py-3 first:pt-0 last:pb-0"><span className="text-body-copy text-text-body">{label}</span><span className="text-right"><strong className="numeric-tabular block text-body-strong text-text-strong">{value}</strong><span className="text-caption">{detail}</span></span></div>;
}

function RecommendationBlock({ baseline, recommended, recommendation, onExecute, onModify, onRefuse, decision }: { baseline: ReturnType<typeof simulateDischargeScenario>["summary"]; recommended: ReturnType<typeof simulateDischargeScenario>["summary"]; recommendation: ReturnType<typeof useScenarioContext>["insight"]["recommendation"]; onExecute: () => void; onModify: () => void; onRefuse: () => void; decision: ReturnType<typeof useScenarioContext>["decision"] }) {
  return <section className="border-t-2 border-brand-primary pt-5" aria-labelledby="recommendation-title"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-card-label text-brand-primary">Action recommandée</p><h3 id="recommendation-title" className="mt-2 text-xl font-semibold text-text-strong">{recommendation.title}</h3><p className="mt-2 max-w-xl text-body-copy">Créer de la capacité avant la fenêtre de tension prévue. Les sorties sont déjà confirmées dans ce scénario.</p></div><span className="text-badge text-brand-primary">Faisabilité élevée · confiance élevée</span></div><div className="mt-5 grid grid-cols-2 gap-x-8 gap-y-3 border-y border-border-subtle py-4 sm:grid-cols-4"><Impact label="Tension" before={`${baseline.criticalHours} h`} after={`${recommended.criticalHours} h`} /><Impact label="Occupation" before={`${baseline.peakOccupancyPercent} %`} after={`${recommended.peakOccupancyPercent} %`} /><Impact label="Lits disponibles" before={`${baseline.peakAvailableBeds}`} after={`${recommended.peakAvailableBeds}`} /><Impact label="Charge en soins" before={`${baseline.peakSiips}`} after={`${recommended.peakSiips} SIIPS`} /></div><p className="mt-4 text-body-copy">Cette action réduit la tension capacitaire mais ne corrige pas le déficit de {Math.abs(baseline.staffingGapPeak)} IDE prévu.</p>{decision ? <div className="mt-5 rounded-lg bg-bg-app p-3 text-body-copy" role="status">{decision.decision === "accepted" ? "Action validée" : "Décision refusée"}{decision.reason ? ` · ${decision.reason}` : ""}</div> : <div className="mt-6 flex flex-wrap items-center gap-3" aria-label="Décider de l'action"><button type="button" className="inline-flex items-center gap-2 rounded-lg bg-brand-primary px-5 py-3 text-control text-white shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={onExecute}><Check className="h-4 w-4" aria-hidden="true" /> Exécuter</button><button type="button" className="rounded-lg border border-border-subtle px-5 py-3 text-control text-text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={onModify}>Modifier</button><button type="button" className="rounded-lg px-3 py-3 text-control text-status-critical focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-status-critical" onClick={onRefuse}>Refuser</button></div>}</section>;
}

function Impact({ label, before, after }: { label: string; before: string; after: string }) {
  return <div><p className="text-caption">{label}</p><p className="numeric-tabular mt-1 text-body-strong text-text-muted">{before} <span aria-hidden="true">→</span> <strong className="text-text-strong">{after}</strong></p></div>;
}

function DecisionDialog({ mode, insight, baseline, recommended, reason, onReasonChange, onClose, onConfirm, canConfirm }: { mode: "execute" | "refuse"; insight: ReturnType<typeof useScenarioContext>["insight"]; baseline: ReturnType<typeof simulateDischargeScenario>["summary"]; recommended: ReturnType<typeof simulateDischargeScenario>["summary"]; reason: string; onReasonChange: (value: string) => void; onClose: () => void; onConfirm: () => void; canConfirm: boolean }) {
  const isExecute = mode === "execute";
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-navy/40 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><div className="w-full max-w-lg rounded-card border border-border-subtle bg-bg-card p-6 shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="decision-dialog-title"><div className="flex items-start justify-between gap-4"><div><p className="text-card-label text-brand-primary">Décision humaine</p><h2 id="decision-dialog-title" className="mt-2 text-xl font-semibold text-text-strong">{isExecute ? "Valider cette action" : "Refuser la recommandation"}</h2></div><button type="button" aria-label="Fermer" autoFocus className="rounded-full p-2 text-text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={onClose}><X className="h-5 w-5" aria-hidden="true" /></button></div><div className="mt-5 space-y-2 border-y border-border-subtle py-4 text-body-copy"><p className="font-semibold text-text-strong">{insight.recommendation.title}</p><p>Service : {insight.context.serviceLabel}</p><p>Échéance : avant 15h</p><p>Conséquence attendue : {baseline.peakOccupancyPercent} % → {recommended.peakOccupancyPercent} % d'occupation · {baseline.criticalHours} h → {recommended.criticalHours} h en tension</p></div>{!isExecute ? <label className="mt-5 block text-body-copy"><span className="font-semibold text-text-strong">Motif du refus</span><select autoFocus className="mt-2 h-11 w-full rounded-lg border border-border-subtle bg-bg-card px-3 outline-none focus:border-brand-primary focus:ring-2 focus:ring-brand-primary/20" value={reason} onChange={(event) => onReasonChange(event.currentTarget.value)}><option value="">Sélectionner une raison</option>{REFUSAL_REASONS.map((item) => <option key={item} value={item}>{item}</option>)}</select></label> : null}<div className="mt-5 border-l-2 border-brand-primary pl-3 text-body-copy">Prototype de recherche : aucune action n'est exécutée dans un système hospitalier.</div><div className="mt-6 flex justify-end gap-3"><button type="button" className="rounded-lg border border-border-subtle px-4 py-2 text-control text-text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={onClose}>Annuler</button><button type="button" disabled={!canConfirm} className="rounded-lg bg-brand-primary px-4 py-2 text-control text-white disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={onConfirm}>{isExecute ? "Valider l'action" : "Confirmer le refus"}</button></div></div></div>;
}
