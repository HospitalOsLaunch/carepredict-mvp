import { useState } from "react";
import { ArrowRight, Check, X } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { useScenarioContext } from "../domain/ScenarioContext";
import { formatConfidence, formatRiskLevel, simulateDischargeScenario } from "../domain/insights";
import { REFUSAL_REASONS } from "./Insights";

export function ModifyInsight() {
  const navigate = useNavigate();
  const { insight, selectedParameters, simulation, setParameter, acceptModifiedScenario, refuseRecommendation } = useScenarioContext();
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showRefusal, setShowRefusal] = useState(false);
  const [refusalReason, setRefusalReason] = useState("");
  const selected = selectedParameters.confirmed_discharges ?? 0;
  const recommendedSummary = simulateDischargeScenario(5).summary;
  const customSummary = simulation.summary;
  const baselineSummary = simulateDischargeScenario(0).summary;

  return (
    <section className="space-y-6" aria-labelledby="modify-title">
      <header>
        <Link to={`/insights/${insight.id}`} className="text-control text-brand-primary">← Retour à l'insight</Link>
        <h1 id="modify-title" className="text-screen mt-3 text-text-strong">Modifier la recommandation</h1>
        <p className="text-caption mt-2" data-testid="scenario-context">{insight.context.hospitalLabel} · {insight.context.serviceLabel} · horizon {insight.context.horizonHours}h</p>
        <p className="text-caption mt-1">Ajustez le scénario proposé et visualisez immédiatement son impact sur la pression SIIPS.</p>
      </header>
      <div className="grid gap-6 lg:grid-cols-[0.75fr_1.25fr]">
        <article className="rounded-card border border-brand-primary/30 bg-bg-card p-6 shadow-card">
          <p className="text-card-label text-brand-primary">Recommandation HospitalOS</p>
          <h2 className="text-section mt-2 text-lg text-text-strong">Sorties confirmées avant 15h</h2>
          <label className="mt-6 block text-body-copy" htmlFor="confirmed-discharges"><span className="text-body-strong text-text-strong">Votre scénario</span><div className="mt-2 flex items-center gap-3"><input id="confirmed-discharges" aria-label="Sorties confirmées avant 15h" type="number" min={0} max={8} step={1} value={selected} onChange={(event) => setParameter("confirmed_discharges", Number(event.currentTarget.value))} className="h-12 w-28 rounded-lg border border-border-subtle px-3 text-center text-lg outline-none focus:border-brand-primary focus:ring-2 focus:ring-brand-primary/20" /><span className="text-caption">patients</span></div></label>
          <p className="text-caption mt-3">Valeur recommandée : <strong className="text-text-strong">5 patients</strong></p>
          <div className="mt-6 rounded-lg border border-brand-primary/20 bg-brand-primary/5 p-3 text-body-copy" role="status" aria-live="polite">La simulation est recalculée pour {selected} sortie{selected > 1 ? "s" : ""}.</div>
          <button type="button" className="mt-6 inline-flex items-center gap-2 text-control text-brand-primary" onClick={() => setShowAdvanced((value) => !value)}>Modifier d'autres paramètres <ArrowRight className="h-4 w-4" aria-hidden="true" /></button>
          {showAdvanced ? <p className="text-caption mt-2">Les autres leviers restent disponibles dans le simulateur avancé lorsqu'ils sont pris en charge par le scénario.</p> : null}
        </article>
        <article className="rounded-card border border-border-subtle bg-bg-card p-6 shadow-card" aria-labelledby="comparison-title">
          <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-card-label text-brand-primary">Impact simulé</p><h2 id="comparison-title" className="text-section mt-2 text-lg text-text-strong">Plan actuel vs recommandation vs votre scénario</h2></div><span className="text-badge text-status-good">{formatConfidence(insight.confidence)} confiance</span></div>
          <div className="mt-6 grid gap-3 md:grid-cols-3"><Comparison label="Plan actuel" summary={baselineSummary} /><Comparison label="Recommandation" summary={recommendedSummary} tone="recommended" /><Comparison label="Votre scénario" summary={customSummary} tone="custom" /></div>
          <div className="mt-6 space-y-3" aria-label="Comparaison des courbes de pression"><ComparisonBar label="Plan actuel" value={baselineSummary.peak} color="bg-status-critical" /><ComparisonBar label="Recommandation" value={recommendedSummary.peak} color="bg-brand-primary" /><ComparisonBar label="Votre scénario" value={customSummary.peak} color="bg-status-high" /></div>
          <p className="text-caption mt-5">Le scénario recommandé réduit la pression sans promettre une amélioration totale. Votre scénario conserve la même échelle SIIPS.</p>
        </article>
      </div>
      <div className="flex flex-wrap justify-end gap-3">
        <button type="button" className="rounded-lg border border-border-subtle px-4 py-3 text-control text-text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={() => navigate(`/insights/${insight.id}/modify`)}>Continuer à modifier</button>
        <button type="button" className="inline-flex items-center gap-2 rounded-lg border border-status-critical/30 px-4 py-3 text-control text-status-critical focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-status-critical" onClick={() => setShowRefusal(true)}><X className="h-4 w-4" aria-hidden="true" /> Refuser</button>
        <button type="button" className="inline-flex items-center gap-2 rounded-lg bg-brand-primary px-4 py-3 text-control text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={() => { acceptModifiedScenario(); navigate("/actions"); }}><Check className="h-4 w-4" aria-hidden="true" /> Exécuter ce scénario</button>
      </div>
      {showRefusal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-navy/40 p-4" role="presentation">
          <div className="w-full max-w-lg rounded-card border border-border-subtle bg-bg-card p-6 shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="modify-refusal-title">
            <h2 id="modify-refusal-title" className="text-section text-xl text-text-strong">Refuser la recommandation</h2>
            <p className="text-caption mt-2">Un motif est nécessaire pour enregistrer votre décision.</p>
            <label className="mt-5 block text-body-copy" htmlFor="modify-refusal-reason">
              <span className="text-body-strong text-text-strong">Motif du refus</span>
              <select id="modify-refusal-reason" autoFocus className="mt-2 h-11 w-full rounded-lg border border-border-subtle bg-bg-card px-3 outline-none focus:border-brand-primary focus:ring-2 focus:ring-brand-primary/20" value={refusalReason} onChange={(event) => setRefusalReason(event.currentTarget.value)}>
                <option value="">Sélectionner une raison</option>
                {REFUSAL_REASONS.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <div className="mt-6 flex justify-end gap-3">
              <button type="button" className="rounded-lg border border-border-subtle px-4 py-2 text-control text-text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={() => { setShowRefusal(false); setRefusalReason(""); }}>Annuler</button>
              <button type="button" disabled={!refusalReason} className="rounded-lg bg-brand-primary px-4 py-2 text-control text-white disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={() => { refuseRecommendation(refusalReason); setShowRefusal(false); navigate(`/insights/${insight.id}`); }}>Confirmer le refus</button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function Comparison({ label, summary, tone }: { label: string; summary: { peak: number; criticalHours: number }; tone?: "recommended" | "custom" }) {
  return <div className={`rounded-xl border p-4 ${tone === "recommended" ? "border-brand-primary/30 bg-brand-primary/5" : tone === "custom" ? "border-status-high/30 bg-status-high/5" : "border-border-subtle bg-bg-app"}`}><p className="text-caption">{label}</p><p className="numeric-tabular mt-2 text-section text-text-strong">{summary.peak} SIIPS</p><p className="text-caption mt-1">{summary.criticalHours} h en tension · {formatRiskLevel(summary.peak > 1600 ? "critical" : "high")}</p></div>;
}

function ComparisonBar({ label, value, color }: { label: string; value: number; color: string }) {
  return <div className="flex items-center gap-3"><span className="w-28 text-caption">{label}</span><div className="h-3 flex-1 rounded-full bg-gauge-track"><div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(100, (value / 2000) * 100)}%` }} /></div><span className="numeric-tabular w-20 text-right text-caption">{value} SIIPS</span></div>;
}
