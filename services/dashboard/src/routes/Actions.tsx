import { Link } from "react-router-dom";

import { useScenarioContext } from "../domain/ScenarioContext";

const STATUS_LABELS = { proposed: "À examiner", accepted: "Validée", dismissed: "Refusée" } as const;

export function Actions() {
  const { insight, decision, auditEvents } = useScenarioContext();
  return (
    <section className="space-y-6" aria-labelledby="actions-title">
      <header><p className="text-card-label text-brand-primary">Suivi des décisions</p><h1 id="actions-title" className="text-screen mt-2 text-text-strong">Actions</h1><p className="text-caption mt-2">Ce que vous avez décidé, ce qui reste à examiner et ce qui a été refusé.</p></header>
      <div className="grid gap-4 md:grid-cols-3"><StatusCard label="À examiner" value={decision ? "0" : "1"} /><StatusCard label="Validée" value={decision?.decision === "accepted" ? "1" : "0"} /><StatusCard label="Refusée" value={decision?.decision === "dismissed" ? "1" : "0"} /></div>
      <article className="rounded-card border border-border-subtle bg-bg-card p-6 shadow-card"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-card-label text-brand-primary">Décision</p><h2 className="text-section mt-2 text-lg text-text-strong">{insight.recommendation.title}</h2><p className="text-caption mt-1">{insight.context.hospitalLabel} · {insight.context.serviceLabel}</p></div><span className="rounded-full border border-border-subtle px-3 py-1 text-badge text-text-muted">{decision ? STATUS_LABELS[decision.decision] : STATUS_LABELS.proposed}</span></div>{decision ? <div className="mt-5 rounded-lg bg-bg-app p-4 text-body-copy"><p>Décision : <strong>{decision.decision === "accepted" ? "scénario accepté" : "recommandation refusée"}</strong></p><p className="mt-1">Enregistrée le {new Date(decision.timestamp).toLocaleString("fr-FR")}</p><p className="mt-1">Recommandation initiale : {decision.originalParameters.confirmed_discharges ?? 0} sorties confirmées</p><p className="mt-1">Scénario choisi : {decision.selectedParameters.confirmed_discharges ?? 0} sorties confirmées</p>{decision.reason ? <p className="mt-1">Motif : {decision.reason}</p> : null}</div> : <Link to={`/insights/${insight.id}`} className="mt-5 inline-flex text-control text-brand-primary">Examiner l'insight →</Link>}</article>
      <article className="rounded-card border border-border-subtle bg-bg-card p-6 shadow-card" aria-labelledby="timeline-title"><h2 id="timeline-title" className="text-section text-text-strong">Historique de décision</h2>{auditEvents.length === 0 ? <p className="text-caption mt-4">Aucun événement enregistré pour le moment.</p> : <ol className="mt-4 space-y-3">{auditEvents.map((event, index) => <li key={`${event.timestamp}-${index}`} className="border-l-2 border-brand-primary/30 pl-4 text-body-copy"><p className="text-body-strong">{event.decision === "accepted" ? "Décision acceptée" : "Recommandation refusée"}</p><p className="text-caption">{new Date(event.timestamp).toLocaleString("fr-FR")}{event.reason ? ` · ${event.reason}` : ""}</p></li>)}</ol>}</article>
    </section>
  );
}

function StatusCard({ label, value }: { label: string; value: string }) { return <div className="rounded-card border border-border-subtle bg-bg-card p-5 shadow-card"><p className="text-caption">{label}</p><p className="numeric-tabular mt-2 text-hero text-text-strong">{value}</p></div>; }
