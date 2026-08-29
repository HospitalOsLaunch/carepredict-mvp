import { useState } from "react";
import { ArrowRight, Check, ChevronRight, Clock3, ShieldAlert, X } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { useScenarioContext } from "../domain/ScenarioContext";
import {
  formatConfidence,
  formatDateTime,
  formatRiskLevel,
  PRESSURE_THRESHOLD_SIIPS
} from "../domain/insights";

const REFUSAL_REASONS = [
  "Ressources indisponibles",
  "Action non pertinente",
  "Action déjà en cours",
  "Contrainte organisationnelle",
  "Impact jugé insuffisant",
  "Autre"
];

export function Insights() {
  const navigate = useNavigate();
  const { insight, decision, acceptRecommendation, refuseRecommendation } = useScenarioContext();
  const [dialog, setDialog] = useState<"execute" | "refuse" | null>(null);
  const [reason, setReason] = useState("");

  const closeDialog = () => {
    setDialog(null);
    setReason("");
  };

  return (
    <section className="space-y-6" aria-labelledby="insights-title">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-card-label text-brand-primary">Décision opérationnelle</p>
          <h1 id="insights-title" className="text-screen mt-2 text-text-strong">Insights</h1>
          <p className="text-caption mt-2 max-w-2xl">Ce qui mérite votre attention, pourquoi, et la décision que vous pouvez prendre.</p>
        </div>
        <div className="rounded-full border border-border-subtle bg-bg-card px-4 py-2 text-body-copy shadow-card">
          {insight.context.hospitalLabel} · {insight.context.serviceLabel}
        </div>
      </header>

      <article className="overflow-hidden rounded-card border border-border-subtle bg-bg-card shadow-card" aria-labelledby="primary-insight-title">
        <div className="border-b border-border-subtle bg-status-critical/5 px-6 py-5">
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div>
              <p className="text-card-label text-status-critical">Tension</p>
              <h2 id="primary-insight-title" className="text-section mt-2 text-xl text-text-strong">{insight.title}</h2>
              <p className="text-body-copy mt-2 flex items-center gap-2">
                <Clock3 className="h-4 w-4 text-brand-primary" aria-hidden="true" />
                Aujourd'hui · {formatDateTime(insight.riskWindowStart)}–{formatDateTime(insight.riskWindowEnd)}
              </p>
            </div>
            <div className="rounded-full border border-status-critical/30 bg-white px-3 py-2 text-badge text-status-critical">
              {formatRiskLevel(insight.riskLevel)}
            </div>
          </div>
          <div className="mt-6 grid gap-4 sm:grid-cols-4">
            <Metric label="Pic prévu" value={`${insight.peakPressureSiips} SIIPS`} />
            <Metric label="Seuil critique" value={`${PRESSURE_THRESHOLD_SIIPS} SIIPS`} />
            <Metric label="Heures en tension" value={`${insight.criticalHours} h`} />
            <Metric label="Confiance" value={formatConfidence(insight.confidence)} />
          </div>
        </div>

        <div className="grid gap-6 p-6 lg:grid-cols-[0.9fr_1.1fr]">
          <section aria-labelledby="drivers-title">
            <p id="drivers-title" className="text-card-label text-brand-primary">Pourquoi ?</p>
            <div className="mt-4 space-y-3">
              {insight.drivers.slice(0, 3).map((driver) => (
                <div key={driver.id} className="rounded-xl border border-border-subtle bg-bg-app p-4">
                  <p className="text-body-strong text-text-strong">{driver.label}</p>
                  <p className="text-caption mt-1">{driver.explanation}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-xl border border-brand-primary/30 bg-brand-primary/5 p-5" aria-labelledby="recommendation-title">
            <p id="recommendation-title" className="text-card-label text-brand-primary">Recommandation</p>
            <h3 className="text-section mt-2 text-lg text-text-strong">{insight.recommendation.title}</h3>
            <p className="text-body-copy mt-2">{insight.recommendation.rationale}</p>
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              <Metric label="Impact attendu" value="−200 SIIPS" tone="good" />
              <Metric label="Faisabilité" value="Élevée" tone="good" />
              <Metric label="Confiance" value={formatConfidence(insight.recommendation.confidence)} />
            </div>
            {decision ? (
              <div className={`mt-5 rounded-lg border p-3 text-body-copy ${decision.decision === "accepted" ? "border-status-good/30 bg-status-good/10 text-status-good" : "border-status-elevated/30 bg-status-elevated/10 text-text-body"}`} role="status">
                {decision.decision === "accepted" ? "Action validée" : "Recommandation refusée"}
                {decision.reason ? ` · ${decision.reason}` : ""}
              </div>
            ) : null}
            <div className="mt-6 flex flex-wrap gap-3" aria-label="Actions de décision">
              <button type="button" className="inline-flex items-center gap-2 rounded-lg bg-brand-primary px-4 py-3 text-control text-white shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={() => setDialog("execute")}>
                <Check className="h-4 w-4" aria-hidden="true" /> Exécuter
              </button>
              <button type="button" className="inline-flex items-center gap-2 rounded-lg border border-border-subtle bg-bg-card px-4 py-3 text-control text-text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={() => navigate(`/insights/${insight.id}/modify`)}>
                Modifier
              </button>
              <button type="button" className="inline-flex items-center gap-2 rounded-lg border border-status-critical/30 px-4 py-3 text-control text-status-critical focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-status-critical" onClick={() => setDialog("refuse")}>
                <X className="h-4 w-4" aria-hidden="true" /> Refuser
              </button>
            </div>
          </section>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle px-6 py-4">
          <span className="text-caption">Scénario {insight.context.scenarioId} · données synthétiques</span>
          <Link className="inline-flex items-center gap-1 text-control text-brand-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" to={`/insights/${insight.id}/forecast`}>Voir la prévision détaillée <ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>
        </div>
      </article>

      {dialog ? (
        <DecisionDialog
          mode={dialog}
          reason={reason}
          onReasonChange={setReason}
          onClose={closeDialog}
          onConfirm={() => {
            if (dialog === "execute") acceptRecommendation();
            else if (reason) refuseRecommendation(reason);
            closeDialog();
          }}
          canConfirm={dialog === "execute" || Boolean(reason)}
        />
      ) : null}
    </section>
  );
}

function Metric({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "good" }) {
  return (
    <div>
      <p className="text-caption">{label}</p>
      <p className={`numeric-tabular mt-1 text-body-strong ${tone === "good" ? "text-status-good" : "text-text-strong"}`}>{value}</p>
    </div>
  );
}

function DecisionDialog({
  mode,
  reason,
  onReasonChange,
  onClose,
  onConfirm,
  canConfirm
}: {
  mode: "execute" | "refuse";
  reason: string;
  onReasonChange: (value: string) => void;
  onClose: () => void;
  onConfirm: () => void;
  canConfirm: boolean;
}) {
  const isExecute = mode === "execute";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-navy/40 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="w-full max-w-lg rounded-card border border-border-subtle bg-bg-card p-6 shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="decision-dialog-title">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-card-label text-brand-primary">Décision humaine</p>
            <h2 id="decision-dialog-title" className="text-section mt-2 text-xl text-text-strong">{isExecute ? "Confirmer l'action" : "Refuser la recommandation"}</h2>
          </div>
          <button type="button" aria-label="Fermer" autoFocus={isExecute} className="rounded-full p-2 text-text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={onClose}><X className="h-5 w-5" aria-hidden="true" /></button>
        </div>
        <div className="mt-5 space-y-3 rounded-xl bg-bg-app p-4 text-body-copy">
          <p className="text-body-strong text-text-strong">Prioriser 5 sorties confirmées avant 15h</p>
          <p>Service : Urgences</p>
          <p>Objectif : réduire la tension prévue entre 16h et 20h</p>
          <p>Impact attendu : −200 SIIPS · Confiance : Élevée</p>
        </div>
        {!isExecute ? (
          <label className="mt-5 block text-body-copy">
            <span className="text-body-strong text-text-strong">Pourquoi refusez-vous cette recommandation ?</span>
            <select autoFocus={!isExecute} className="mt-2 h-11 w-full rounded-lg border border-border-subtle bg-bg-card px-3 outline-none focus:border-brand-primary focus:ring-2 focus:ring-brand-primary/20" value={reason} onChange={(event) => onReasonChange(event.currentTarget.value)}>
              <option value="">Sélectionner une raison</option>
              {REFUSAL_REASONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        ) : null}
        <div className="mt-6 rounded-lg border border-brand-primary/20 bg-brand-primary/5 p-3 text-body-copy" role="note">
          <ShieldAlert className="mr-2 inline h-4 w-4 text-brand-primary" aria-hidden="true" />
          Mode étude : HospitalOS enregistre votre décision. Aucune action n'est exécutée dans un système hospitalier.
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <button type="button" className="rounded-lg border border-border-subtle px-4 py-2 text-control text-text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={onClose}>Annuler</button>
          <button type="button" disabled={!canConfirm} className="rounded-lg bg-brand-primary px-4 py-2 text-control text-white disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={onConfirm}>{isExecute ? "Confirmer l'exécution" : "Confirmer le refus"}</button>
        </div>
      </div>
    </div>
  );
}

export { REFUSAL_REASONS };
