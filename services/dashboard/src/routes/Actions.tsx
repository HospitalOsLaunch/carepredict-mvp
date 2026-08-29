import { Link } from "react-router-dom";

import { useScenarioContext } from "../domain/ScenarioContext";
import { simulateDischargeScenario } from "../domain/insights";
import { HCL_TARGET_PRODUCT_RESEARCH_SCENARIO as scenario } from "../research/hclTargetScenario";

export function Actions() {
  const { insight, decision } = useScenarioContext();
  const baseline = simulateDischargeScenario(0).summary;
  const selected = simulateDischargeScenario(decision?.selectedParameters.confirmed_discharges ?? scenario.recommendation.recommendedValue).summary;
  const isRefused = decision?.decision === "dismissed";
  const isAccepted = decision?.decision === "accepted";
  const actionStatus = isRefused ? "Refusée" : isAccepted ? "Validée" : "À examiner";
  return (
    <section className="mx-auto max-w-[1180px] space-y-8" aria-labelledby="actions-title">
      <header className="flex flex-wrap items-end justify-between gap-5 border-b border-border-subtle pb-6"><div><p className="text-card-label text-brand-primary">File d'actions</p><h1 id="actions-title" className="mt-2 text-3xl font-semibold tracking-tight text-text-strong">Actions</h1><p className="mt-2 text-body-copy">{isRefused ? "1 action refusée" : isAccepted ? "1 action validée" : "1 action à examiner"}</p></div><span className="text-caption">{scenario.serviceLabel} · {scenario.scenarioDateLabel}</span></header>
      <div className="flex gap-6 border-b border-border-subtle" role="tablist" aria-label="État des actions"><Tab label="À traiter" active={!decision} /><Tab label="En cours" /><Tab label="Terminées" active={Boolean(decision)} /></div>
      {isRefused ? <div className="border-l-2 border-status-critical bg-status-critical/5 p-5 text-body-copy" role="status">La recommandation a été refusée. La tension de la situation reste visible dans Situations.</div> : null}
      <article className="border border-border-subtle bg-bg-card p-7 shadow-card" aria-labelledby="action-item-title"><div className="flex flex-wrap items-start justify-between gap-5 border-b border-border-subtle pb-5"><div><p className="text-card-label text-brand-primary">{actionStatus}</p><h2 id="action-item-title" className="mt-2 text-xl font-semibold text-text-strong">{insight.recommendation.title}</h2><p className="mt-2 text-body-copy">{scenario.serviceLabel} · échéance avant 15h</p></div><span className="rounded-full border border-brand-primary/30 px-3 py-1 text-badge text-brand-primary">{actionStatus}</span></div><div className="mt-6 grid gap-6 sm:grid-cols-3"><ActionImpact label="Occupation au pic" before={`${baseline.peakOccupancyPercent} %`} after={`${selected.peakOccupancyPercent} %`} /><ActionImpact label="Temps en tension" before={`${baseline.criticalHours} h`} after={`${selected.criticalHours} h`} /><ActionImpact label="Lits disponibles" before={`${baseline.peakAvailableBeds}`} after={`${selected.peakAvailableBeds}`} /></div><p className="mt-6 border-t border-border-subtle pt-5 text-body-copy">Dans ce prototype de recherche, une validation enregistre une décision humaine ; elle ne déclenche aucune action hospitalière.</p><Link to={`/situations/${insight.id}`} className="mt-5 inline-flex text-control text-brand-primary">Revoir la situation →</Link></article>
      <section aria-labelledby="action-timeline-title"><div className="flex items-end justify-between border-b border-border-subtle pb-3"><h2 id="action-timeline-title" className="text-xl font-semibold text-text-strong">Journal de décision</h2><span className="text-caption">lecture seule</span></div>{decision ? <div className="border-b border-border-subtle py-4 text-body-copy"><p className="font-medium text-text-strong">{decision.decision === "accepted" ? "Action validée" : "Recommandation refusée"}</p><p className="mt-1 text-caption">{new Date(decision.timestamp).toLocaleString("fr-FR")}{decision.reason ? ` · ${decision.reason}` : ""}</p></div> : <p className="py-5 text-caption">Aucune décision enregistrée pour le moment.</p>}</section>
    </section>
  );
}

function Tab({ label, active = false }: { label: string; active?: boolean }) { return <button type="button" role="tab" aria-selected={active} className={`border-b-2 px-1 pb-3 text-control ${active ? "border-brand-primary text-brand-primary" : "border-transparent text-text-muted"}`}>{label}</button>; }
function ActionImpact({ label, before, after }: { label: string; before: string; after: string }) { return <div><p className="text-caption">{label}</p><p className="numeric-tabular mt-2 text-lg font-semibold text-text-strong">{before} <span className="text-text-muted" aria-hidden="true">→</span> <span className="text-brand-primary">{after}</span></p></div>; }
