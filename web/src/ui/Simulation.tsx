import type { Simulation } from "../data/useSimulation";
import type { CommandReceipt } from "../api/simulator";
import { actionTitle, explain } from "../domain/labels";
import { clock, longClock } from "../domain/view";
import { ComparisonPanel } from "./Comparison";

const STATUS: Record<CommandReceipt["status"], string> = {
  accepted: "Acceptée, traitement en cours",
  refusal_recorded: "Refus enregistré, lecture en cours",
  executed: "Action appliquée dans le scénario",
  refused: "Refus pris en compte",
  failed: "Échec : les conditions physiques ont changé",
};

export function SimulationPanel({ simulation }: { simulation: Simulation }) {
  const { view, store, control, decide, refresh } = simulation;
  const disabled = store.busy || !!store.error || !view;
  const plan = view?.episode?.assessment.plan;
  const last = view?.commands.at(-1);
  return (
    <>
    <section className="simulation-panel" aria-label="Piloter le scénario">
      <div className="simulation-panel__heading">
        <div>
          <span className="demobar__tag">Hôpital simulé · 3 lits</span>
          <h2>Une unité qui évolue avec vos décisions</h2>
          <p>Au départ, un patient attend un lit avec oxygène. Une seule équipe nettoie les lits.</p>
        </div>
        <div className="simulation-panel__clock" aria-live="off">
          <strong>{view ? clock(view.now) : "—"}</strong>
          <span>{view?.completed ? "Séance terminée" : view?.speed ? `Lecture ×${view.speed}` : "En pause"}</span>
        </div>
      </div>
      <div className="simulation-panel__controls">
        <button className="btn" disabled={disabled || view?.completed} onClick={() => control(view?.speed ? "pause" : "play")}>
          {view?.speed ? "Pause" : "Lire ×60"}
        </button>
        <button className="btn" disabled={disabled || !!view?.speed || view?.completed} onClick={() => control("advance", 60)}>+1 minute</button>
        <button className="btn" disabled={disabled || !!view?.speed || view?.completed} onClick={() => control("advance", 300)}>+5 minutes</button>
        <button className="btn btn--quiet" disabled={store.busy} onClick={refresh}>Actualiser</button>
        <button className="btn btn--quiet" disabled={disabled} onClick={() => control("reset")}>Recommencer</button>
      </div>
      <div className="simulation-panel__decision">
        <h3>{view?.completed ? "Résultat de cette séance" : plan ? actionTitle(plan.selected) : "Évaluer l'unité avant de choisir"}</h3>
        {view?.snapshot.issues.length ? <p role="status">{view.snapshot.issues.map(explain).join(" · ")}</p> : null}
        {!view?.completed ? (
          <>
            <p>Les propositions utilisent les observations reçues. La disponibilité des lits est déclarée avec retard.</p>
            <div className="simulation-panel__controls">
              <button className="btn" disabled={disabled} onClick={store.evaluate}>Évaluer le scénario</button>
              <button className="btn btn--primary" disabled={disabled || !view?.can_apply} onClick={() => decide(true)}>Appliquer dans le scénario</button>
              <button className="btn" disabled={disabled || !view?.can_apply} onClick={() => decide(false)}>Refuser dans le scénario</button>
            </div>
            {last ? <p className="simulation-panel__receipt" role="status">{STATUS[last.status]}. Un acquittement ne signifie pas que le lit est prêt.</p> : null}
          </>
        ) : view.evaluation ? (
          <p><strong>{view.evaluation.waiting_patient_minutes.toFixed(1)} minutes-patients d'attente cumulée</strong> · {view.evaluation.waiting_at_end} encore en attente · {view.evaluation.admitted_at_end} hospitalisés · {view.evaluation.departed} départ(s). Mesure de ce scénario fictif, sans comparaison d'efficacité.</p>
        ) : null}
      </div>
      <details>
        <summary>Tester une panne ou terminer la séance</summary>
        <div className="simulation-panel__controls">
          <button className="btn" disabled={disabled || view?.completed} onClick={() => control(view?.feed_enabled ? "disconnect" : "reconnect")}>
            {view?.feed_enabled ? "Couper le flux simulé" : "Rétablir le flux simulé"}
          </button>
          <button className="btn" disabled={disabled || view?.completed} onClick={() => control("finish")}>Terminer et mesurer</button>
        </div>
        <p>Recommencer reproduit les mêmes aléas. Les actions ne concernent que cette séance fictive.</p>
      </details>
    </section>
    <ComparisonPanel />
    </>
  );
}

export function SimulationJournal({ simulation }: { simulation: Simulation }) {
  return (
    <section className="simulation-panel" aria-label="Journal du scénario">
      <h1>Décisions dans le scénario</h1>
      <p>Réponses du simulateur. L'installation du patient se vérifie dans les observations de l'unité.</p>
      {!simulation.view?.commands.length ? <p>Aucune décision dans cette séance.</p> : (
        <ol>{simulation.view.commands.map((c) => <li key={c.request_id}>
          <strong>{STATUS[c.status]}</strong> · {longClock(c.outcome_at ?? c.at)} · {c.processing_seconds} s de traitement
        </li>)}</ol>
      )}
    </section>
  );
}
