import { useState } from "react";
import { Link } from "react-router-dom";

import { useScenarioContext } from "../domain/ScenarioContext";
import { simulateDischargeScenario } from "../domain/insights";
import { HCL_TARGET_PRODUCT_RESEARCH_SCENARIO as scenario } from "../research/hclTargetScenario";

type ActionTab = "pending" | "in_progress" | "done";

const EMPTY_STATES: Record<ActionTab, { title: string; body: string }> = {
  pending: {
    title: "Aucune action à traiter",
    body: "Aucune décision ne nécessite d’action pour le moment.",
  },
  in_progress: {
    title: "Aucune action en cours",
    body: "Les actions validées apparaîtront ici lorsqu’elles seront engagées.",
  },
  done: {
    title: "Aucune action terminée",
    body: "Les actions clôturées apparaîtront ici.",
  },
};

export function Actions() {
  const { insight, decision, selectedUnit, horizonHours } = useScenarioContext();
  const [activeTab, setActiveTab] = useState<ActionTab>("pending");
  const baseline = simulateDischargeScenario(0, horizonHours).summary;
  const selected = simulateDischargeScenario(
    decision?.selectedParameters.confirmed_discharges ?? scenario.recommendation.recommendedValue,
    horizonHours,
  ).summary;
  const hasActiveSituation = selectedUnit.id === "emergency" && horizonHours >= 12;
  const counts: Record<ActionTab, number> = {
    pending: hasActiveSituation && !decision ? 1 : 0,
    in_progress: 0,
    done: 0,
  };
  const pendingLabel = counts.pending === 1 ? "1 action à traiter" : "Aucune action à traiter";

  return (
    <section className="mx-auto max-w-[1180px] space-y-8" aria-labelledby="actions-title">
      <header className="flex flex-wrap items-end justify-between gap-5 border-b border-border-subtle pb-6">
        <div><p className="text-card-label text-brand-primary">File d'actions</p><h1 id="actions-title" className="mt-2 text-3xl font-semibold tracking-tight text-text-strong">Actions</h1><p className="mt-2 text-body-copy">{pendingLabel}</p></div>
        <span className="text-caption">{selectedUnit.label} · horizon {horizonHours} h</span>
      </header>

      <div className="flex gap-6 overflow-x-auto border-b border-border-subtle" role="tablist" aria-label="État des actions">
        <ActionTabButton id="pending" label="À traiter" count={counts.pending} active={activeTab === "pending"} onSelect={setActiveTab} />
        <ActionTabButton id="in_progress" label="En cours" count={counts.in_progress} active={activeTab === "in_progress"} onSelect={setActiveTab} />
        <ActionTabButton id="done" label="Terminées" count={counts.done} active={activeTab === "done"} onSelect={setActiveTab} />
      </div>

      <div id={`actions-panel-${activeTab}`} role="tabpanel" aria-labelledby={`actions-tab-${activeTab}`} tabIndex={0}>
        {activeTab === "pending" && counts.pending > 0 ? <PendingAction insight={insight} baseline={baseline} selected={selected} /> : <ActionEmptyState tab={activeTab} />}
      </div>

      <section aria-labelledby="action-timeline-title">
        <div className="flex items-end justify-between border-b border-border-subtle pb-3"><h2 id="action-timeline-title" className="text-xl font-semibold text-text-strong">Journal de décision</h2><span className="text-caption">lecture seule</span></div>
        {decision ? <div className="border-b border-border-subtle py-4 text-body-copy"><p className="font-medium text-text-strong">{decision.decision === "accepted" ? "Action validée" : "Recommandation refusée"}</p><p className="mt-1 text-caption">{new Date(decision.timestamp).toLocaleString("fr-FR")}{decision.reason ? ` · ${decision.reason}` : ""}</p></div> : <p className="py-5 text-caption">Aucune décision enregistrée pour le moment.</p>}
      </section>
    </section>
  );
}

function ActionTabButton({ id, label, count, active, onSelect }: { id: ActionTab; label: string; count: number; active: boolean; onSelect: (id: ActionTab) => void }) {
  return <button type="button" id={`actions-tab-${id}`} role="tab" aria-selected={active} aria-controls={`actions-panel-${id}`} tabIndex={active ? 0 : -1} onClick={() => onSelect(id)} onKeyDown={(event) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const order: ActionTab[] = ["pending", "in_progress", "done"];
    const offset = event.key === "ArrowRight" ? 1 : -1;
    const next = order[(order.indexOf(id) + offset + order.length) % order.length];
    document.getElementById(`actions-tab-${next}`)?.focus();
    onSelect(next);
  }} className={`whitespace-nowrap border-b-2 px-1 pb-3 text-control focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary ${active ? "border-brand-primary text-brand-primary" : "border-transparent text-text-muted"}`}>{label} <span className="numeric-tabular">{count}</span></button>;
}

function PendingAction({ insight, baseline, selected }: { insight: ReturnType<typeof useScenarioContext>["insight"]; baseline: ReturnType<typeof simulateDischargeScenario>["summary"]; selected: ReturnType<typeof simulateDischargeScenario>["summary"] }) {
  return <article className="border border-border-subtle bg-bg-card p-7 shadow-card" aria-labelledby="action-item-title"><div className="flex flex-wrap items-start justify-between gap-5 border-b border-border-subtle pb-5"><div><p className="text-card-label text-brand-primary">À traiter</p><h2 id="action-item-title" className="mt-2 text-xl font-semibold text-text-strong">{insight.recommendation.title}</h2><p className="mt-2 text-body-copy">{insight.context.serviceLabel} · échéance avant 15h</p></div><span className="rounded-full border border-brand-primary/30 px-3 py-1 text-badge text-brand-primary">À traiter</span></div><div className="mt-6 grid gap-6 sm:grid-cols-3"><ActionImpact label="Occupation au pic" before={`${baseline.peakOccupancyPercent} %`} after={`${selected.peakOccupancyPercent} %`} /><ActionImpact label="Temps en tension" before={`${baseline.criticalHours} h`} after={`${selected.criticalHours} h`} /><ActionImpact label="Lits disponibles" before={`${baseline.peakAvailableBeds}`} after={`${selected.peakAvailableBeds}`} /></div><p className="mt-6 border-t border-border-subtle pt-5 text-caption">Prototype : validation enregistrée sans exécution hospitalière.</p><Link to={`/situations/${insight.id}`} className="mt-5 inline-flex text-control text-brand-primary">Revoir la situation →</Link></article>;
}

function ActionEmptyState({ tab }: { tab: ActionTab }) {
  const state = EMPTY_STATES[tab];
  return <div className="border border-border-subtle bg-bg-card px-6 py-12 text-center" role="status"><h2 className="text-lg font-semibold text-text-strong">{state.title}</h2><p className="mt-2 text-body-copy">{state.body}</p></div>;
}

function ActionImpact({ label, before, after }: { label: string; before: string; after: string }) { return <div><p className="text-caption">{label}</p><p className="numeric-tabular mt-2 text-lg font-semibold text-text-strong">{before} <span className="text-text-muted" aria-hidden="true">→</span> <span className="text-brand-primary">{after}</span></p></div>; }
