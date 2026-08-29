import { useState } from "react";
import { ArrowLeft, ArrowRight, Check, Minus, Plus, X } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { useScenarioContext } from "../domain/ScenarioContext";
import { classifyRiskLevel, formatConfidence, formatRiskLevel, simulateDischargeScenario } from "../domain/insights";
import { HCL_TARGET_PRODUCT_RESEARCH_SCENARIO as scenario } from "../research/hclTargetScenario";
import { ScenarioTrajectoryChart } from "../research/ScenarioTrajectoryChart";
import { REFUSAL_REASONS } from "./Insights";

export function ModifyInsight() {
  const navigate = useNavigate();
  const { insight, decision, selectedParameters, simulation, setParameter, acceptModifiedScenario, refuseRecommendation } = useScenarioContext();
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showRefusal, setShowRefusal] = useState(false);
  const [refusalReason, setRefusalReason] = useState("");
  const selected = selectedParameters.confirmed_discharges ?? scenario.recommendation.recommendedValue;
  const recommended = scenario.recommendation.recommendedValue;
  const recommendedSummary = simulateDischargeScenario(recommended).summary;
  const baselineSummary = simulateDischargeScenario(0).summary;
  const simulationExplanation = describeSimulation(selected, recommended, baselineSummary, recommendedSummary, simulation.summary);

  const updateSelected = (value: number) => setParameter(scenario.recommendation.parameterId, Math.max(scenario.recommendation.min, Math.min(scenario.recommendation.max, value)));

  return (
    <section className="mx-auto max-w-[1180px] space-y-8" aria-labelledby="modify-title">
      <header className="flex flex-wrap items-end justify-between gap-5 border-b border-border-subtle pb-6">
        <div>
          <Link to={`/situations/${insight.id}`} className="inline-flex items-center gap-2 text-control text-brand-primary"><ArrowLeft className="h-4 w-4" aria-hidden="true" /> Retour à la situation</Link>
          <p className="text-card-label mt-5 text-brand-primary">{scenario.serviceLabel} · {scenario.scenarioDateLabel}</p>
          <h1 id="modify-title" className="mt-2 text-3xl font-semibold tracking-tight text-text-strong">Tester une autre option</h1>
          <p className="mt-2 max-w-2xl text-body-copy">Ajustez l'action et comparez son effet sur la situation prévue.</p>
        </div>
        <span className="text-caption">Horizon {scenario.horizonHours} h</span>
      </header>

      <div className="grid gap-8 lg:grid-cols-[0.7fr_1.3fr]">
        <article className="border border-border-subtle bg-bg-card p-7 shadow-card">
          <p className="text-card-label text-brand-primary">Action proposée</p>
          <h2 className="mt-2 text-xl font-semibold text-text-strong">{scenario.recommendation.parameterLabel}</h2>
          <p className="mt-2 text-body-copy">HospitalOS recommande {recommended} sorties déjà confirmées.</p>
          <div className="mt-7 flex items-center gap-3">
            <button type="button" aria-label="Diminuer le nombre de sorties" disabled={Boolean(decision) || selected <= scenario.recommendation.min} onClick={() => updateSelected(selected - 1)} className="rounded-lg border border-border-subtle p-3 text-text-strong disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary"><Minus className="h-4 w-4" aria-hidden="true" /></button>
            <label className="text-caption"><span className="sr-only">Sorties à avancer avant 15h</span><input aria-label="Sorties à avancer avant 15h" type="number" min={scenario.recommendation.min} max={scenario.recommendation.max} step={1} value={selected} disabled={Boolean(decision)} onChange={(event) => updateSelected(Number(event.currentTarget.value))} className="h-14 w-24 rounded-lg border border-border-subtle px-3 text-center text-2xl font-semibold outline-none focus:border-brand-primary focus:ring-2 focus:ring-brand-primary/20 disabled:cursor-not-allowed disabled:bg-bg-app" /></label>
            <button type="button" aria-label="Augmenter le nombre de sorties" disabled={Boolean(decision) || selected >= scenario.recommendation.max} onClick={() => updateSelected(selected + 1)} className="rounded-lg border border-border-subtle p-3 text-text-strong disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary"><Plus className="h-4 w-4" aria-hidden="true" /></button>
            <span className="text-body-copy">patients</span>
          </div>
          <div className="mt-5 flex flex-wrap gap-2" aria-label="Options rapides"><QuickOption value={3} selected={selected} onSelect={updateSelected} /><QuickOption value={5} selected={selected} onSelect={updateSelected} recommended /><QuickOption value={7} selected={selected} onSelect={updateSelected} /></div>
          <div className="mt-6 border-l-2 border-brand-primary pl-4 text-body-copy" role="status" aria-live="polite">{simulationExplanation}</div>
          <details className="mt-6 border-t border-border-subtle pt-4" open={showAdvanced} onToggle={(event) => setShowAdvanced(event.currentTarget.open)}><summary className="cursor-pointer text-control text-brand-primary">Ajuster d'autres leviers</summary><p className="mt-3 text-caption">Les leviers staffing, lits temporaires et activité sont réservés aux scénarios dont les effets déterministes seront définis. Aucun levier non calculé n'est présenté ici.</p></details>
        </article>

        <article className="border border-border-subtle bg-bg-card p-7 shadow-card" aria-labelledby="simulation-title">
          <div className="flex flex-wrap items-end justify-between gap-4 border-b border-border-subtle pb-5"><div><p className="text-card-label text-brand-primary">Impact sur la situation prévue</p><h2 id="simulation-title" className="mt-2 text-xl font-semibold text-text-strong">La trajectoire change avec votre option</h2></div><span className="text-caption">{formatConfidence(insight.confidence)} confiance</span></div>
          <div className="mt-6"><ScenarioTrajectoryChart points={simulation.points} ariaLabel="Comparaison de la trajectoire actuelle, recommandée et personnalisée" /></div>
          <div className="mt-6 overflow-x-auto"><table className="w-full min-w-[620px] text-left text-body-copy"><caption className="sr-only">Comparaison des conséquences prévues</caption><thead className="border-b border-border-subtle text-caption"><tr><th className="py-3 pr-4 font-semibold">Conséquence</th><th className="px-3 py-3 font-semibold">Plan actuel</th><th className="px-3 py-3 font-semibold text-brand-primary">HospitalOS</th><th className="py-3 pl-3 font-semibold text-status-high">Votre option</th></tr></thead><tbody><ComparisonRow label="Temps en tension" before={`${baselineSummary.criticalHours} h`} recommended={`${recommendedSummary.criticalHours} h`} custom={`${simulation.summary.criticalHours} h`} /><ComparisonRow label="Niveau de risque" before={formatRiskLevel(classifyRiskLevel(baselineSummary.peak, baselineSummary.criticalHours))} recommended={formatRiskLevel(classifyRiskLevel(recommendedSummary.peak, recommendedSummary.criticalHours))} custom={formatRiskLevel(classifyRiskLevel(simulation.summary.peak, simulation.summary.criticalHours))} /><ComparisonRow label="Occupation au pic" before={`${baselineSummary.peakOccupancyPercent} %`} recommended={`${recommendedSummary.peakOccupancyPercent} %`} custom={`${simulation.summary.peakOccupancyPercent} %`} /><ComparisonRow label="Lits disponibles" before={`${baselineSummary.peakAvailableBeds}`} recommended={`${recommendedSummary.peakAvailableBeds}`} custom={`${simulation.summary.peakAvailableBeds}`} /><ComparisonRow label="Charge au pic" before={`${baselineSummary.peakSiips}`} recommended={`${recommendedSummary.peakSiips}`} custom={`${simulation.summary.peakSiips} SIIPS`} /><ComparisonRow label="Déficit staffing" before={`${Math.abs(baselineSummary.staffingGapPeak)} IDE`} recommended={`${Math.abs(recommendedSummary.staffingGapPeak)} IDE`} custom={`${Math.abs(simulation.summary.staffingGapPeak)} IDE`} /></tbody></table></div>
          <p className="mt-5 text-caption">Les sorties sont déjà confirmées dans le scénario. Le déficit de 2 IDE reste inchangé : cette action capacitaire ne le corrige pas.</p>
        </article>
      </div>

      {!decision ? <div className="flex flex-wrap justify-end gap-3"><button type="button" className="rounded-lg border border-border-subtle px-5 py-3 text-control text-text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={() => navigate(`/situations/${insight.id}/modify`)}>Continuer à modifier</button><button type="button" className="rounded-lg px-4 py-3 text-control text-status-critical focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-status-critical" onClick={() => setShowRefusal(true)}><X className="mr-2 inline h-4 w-4" aria-hidden="true" /> Refuser</button><button type="button" className="inline-flex items-center gap-2 rounded-lg bg-brand-primary px-5 py-3 text-control text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={() => { acceptModifiedScenario(); navigate("/actions"); }}><Check className="h-4 w-4" aria-hidden="true" /> Exécuter ce scénario</button></div> : <div className="border-l-2 border-brand-primary bg-brand-primary/5 p-4 text-body-copy" role="status">Décision terminale enregistrée : {decision.decision === "accepted" ? "option validée" : "recommandation refusée"}.</div>}

      {showRefusal ? <RefusalDialog reason={refusalReason} onReasonChange={setRefusalReason} onClose={() => { setShowRefusal(false); setRefusalReason(""); }} onConfirm={() => { refuseRecommendation(refusalReason, "modified_scenario"); setShowRefusal(false); navigate(`/situations/${insight.id}`); }} /> : null}
    </section>
  );
}

function QuickOption({ value, selected, onSelect, recommended = false }: { value: number; selected: number; onSelect: (value: number) => void; recommended?: boolean }) {
  return <button type="button" disabled={selected === value} onClick={() => onSelect(value)} className={`rounded-full border px-3 py-2 text-control focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary ${selected === value ? "border-brand-primary bg-brand-primary/10 text-brand-primary" : "border-border-subtle text-text-body"}`}>{value}{recommended ? " recommandé" : ""}</button>;
}

function ComparisonRow({ label, before, recommended, custom }: { label: string; before: string; recommended: string; custom: string }) {
  return <tr className="border-b border-border-subtle last:border-b-0"><th className="py-3 pr-4 font-medium text-text-body">{label}</th><td className="px-3 py-3 numeric-tabular text-text-muted">{before}</td><td className="px-3 py-3 numeric-tabular font-semibold text-brand-primary">{recommended}</td><td className="py-3 pl-3 numeric-tabular font-semibold text-status-high">{custom}</td></tr>;
}

function describeSimulation(selected: number, recommended: number, baseline: { peak: number; criticalHours: number; peakOccupancyPercent: number }, recommendedState: { peak: number; criticalHours: number }, custom: { peak: number; criticalHours: number; peakOccupancyPercent: number }): string {
  if (selected === recommended) return `Votre option correspond à la recommandation HospitalOS : ${custom.peakOccupancyPercent} % d'occupation au pic et ${custom.criticalHours} h de tension prévues.`;
  const difference = Math.abs(selected - recommended);
  const recommendedPeakBenefit = baseline.peak - recommendedState.peak;
  const customPeakBenefit = baseline.peak - custom.peak;
  const recommendedHoursBenefit = baseline.criticalHours - recommendedState.criticalHours;
  const customHoursBenefit = baseline.criticalHours - custom.criticalHours;
  if (selected < recommended) return `Votre option mobilise un effort opérationnel réduit de ${difference} sortie${difference > 1 ? "s" : ""}. Le bénéfice attendu est aussi réduit : −${customPeakBenefit} SIIPS et −${customHoursBenefit} h de tension, contre −${recommendedPeakBenefit} SIIPS et −${recommendedHoursBenefit} h avec la recommandation.`;
  return `Votre option mobilise ${difference} sortie${difference > 1 ? "s" : ""} supplémentaire${difference > 1 ? "s" : ""}. Le bénéfice attendu augmente : −${customPeakBenefit} SIIPS et −${customHoursBenefit} h de tension, contre −${recommendedPeakBenefit} SIIPS et −${recommendedHoursBenefit} h avec la recommandation.`;
}

function RefusalDialog({ reason, onReasonChange, onClose, onConfirm }: { reason: string; onReasonChange: (value: string) => void; onClose: () => void; onConfirm: () => void }) {
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-navy/40 p-4" role="presentation"><div className="w-full max-w-lg rounded-card border border-border-subtle bg-bg-card p-6 shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="modify-refusal-title"><h2 id="modify-refusal-title" className="text-xl font-semibold text-text-strong">Refuser la recommandation</h2><p className="mt-2 text-caption">Un motif est nécessaire pour enregistrer votre décision.</p><label className="mt-5 block text-body-copy"><span className="font-semibold text-text-strong">Motif du refus</span><select aria-label="Motif du refus" autoFocus className="mt-2 h-11 w-full rounded-lg border border-border-subtle bg-bg-card px-3 outline-none focus:border-brand-primary focus:ring-2 focus:ring-brand-primary/20" value={reason} onChange={(event) => onReasonChange(event.currentTarget.value)}><option value="">Sélectionner une raison</option>{REFUSAL_REASONS.map((item) => <option key={item} value={item}>{item}</option>)}</select></label><div className="mt-6 flex justify-end gap-3"><button type="button" className="rounded-lg border border-border-subtle px-4 py-2 text-control text-text-body" onClick={onClose}>Annuler</button><button type="button" disabled={!reason} className="rounded-lg bg-brand-primary px-4 py-2 text-control text-white disabled:cursor-not-allowed disabled:opacity-40" onClick={onConfirm}>Confirmer le refus</button></div></div></div>;
}
