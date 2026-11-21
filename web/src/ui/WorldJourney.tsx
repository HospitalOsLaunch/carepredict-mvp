import type { WmSession } from "../api/worldModel";
import type { PlanAction } from "../api/worldPlans";
import { n, objectives, time } from "../domain/worldModel";
import { BookIcon, Check, Clock, Info } from "./icons";

const statusName: Record<WmSession["phase"], string> = {
  planning: "Décision à prendre", confirmed: "Affectation validée en simulation",
  awaiting_report: "Relevé en attente", review: "Relevé publié",
};
const journalName = {
  opened: "Parcours ouvert", confirmed: "Choix validé en simulation",
  awaiting_report: "Relevé de 16 h encore en attente", report_received: "Relevé de 16 h publié",
};

function Clockline({ session }: { session: WmSession }) {
  const step = session.phase === "planning" || session.phase === "confirmed" ? 1 : 2;
  return <ol className="wm-clockline" aria-label="Chronologie du parcours">
    {[
      { at: 8, label: "Planning de référence" },
      { at: session.decision_hour, label: "Décision simulée" },
      { at: session.target_hour, label: session.phase === "awaiting_report" ? "Relevé attendu" : "Relevé de la file" },
    ].map((point, i) => <li key={point.at} className={i === step ? "is-now" : i < step ? "is-past" : ""} aria-current={i === step ? "step" : undefined}>
      <span className="wm-clockline__dot" aria-hidden="true">{i < step ? <Check size={14} /> : <Clock size={15} />}</span>
      <span><strong>{time(point.at)}</strong><span>{point.label}</span></span>
    </li>)}
  </ol>;
}

export function JourneyClock({ session, busy }: { session: WmSession; busy: string | null }) {
  return <>
    <Clockline session={session} />
    <div className="wm-phase" role="status">
      <span className="wm-status"><i aria-hidden="true" />{session.confirmed_plan && session.phase === "confirmed" ? "Plan validé en simulation" : statusName[session.phase]}</span>
      <span>Horloge simulée <strong>{time(session.hour)}</strong></span>
      {busy === "load" && <span>Actualisation…</span>}
    </div>
  </>;
}

export function ContextCards({ session }: { session: WmSession }) {
  return <>
    <section className="wm-card wm-side-card">
          <div className="wm-side-head"><Clock /><h2>Planning de 8 h</h2></div>
          {session.morning_plan.length ? <ul className="wm-plan">{session.morning_plan.map((item, i) => <li key={i}>{item}</li>)}</ul> :
            <p>Aucune affectation inscrite au planning de référence.</p>}
        </section>
        <section className="wm-card wm-side-card">
          <div className="wm-side-head"><Info /><h2>Disponibilité des données</h2></div>
          <p>{session.context.feed === "full" ? "Les deux composantes de la file sont attendues pour chaque unité." :
            session.context.feed === "partial" ? "Certains relevés d’unité peuvent rester incomplets. La file totale exige les deux composantes de chaque unité." :
            `La file est mesurée à 16 h. Dans ce contexte, le relevé est publié à ${time(session.publication_hour)}.`}</p>
          <p className="wm-model-version">Version du modèle <span>{session.model_version}</span></p>
        </section>
  </>;
}

export function WorldJournal({ session, actions = [] }: { session: WmSession; actions?: PlanAction[] }) {
  return <section className="wm-card wm-journal" aria-label="Journal du parcours">
    <div className="wm-side-head"><BookIcon /><h2>Journal du parcours</h2></div>
    <ol>{session.journal.map((entry,i) => {
      const option = session.options.find((o) => o.id === entry.option_id);
      const plan = session.confirmed_plan;
      return <li key={i}><span className="wm-journal__at">{time(entry.hour)}</span><div className="wm-journal__entry"><strong>{journalName[entry.event]}</strong>{option && <small>{option.label}</small>}
        {plan && entry.event === "confirmed" && <>
          <small>{plan.action_ids.length ? `Plan composé · ${plan.action_ids.length} intervention${plan.action_ids.length === 1 ? "" : "s"} · ${n(plan.cost_eur)} €` : "Planning horaire de référence"}</small>
          {plan.action_ids.length > 0 && <ul className="jp-journal-actions">{plan.action_ids.map((id) => {
            const action = actions.find((a) => a.id === id);
            return <li key={id}>{action ? `${action.label} · ${action.quantity} ${action.unit} · ${time(action.start_hour)}–${time(action.end_hour)}` : id}</li>;
          })}</ul>}
        </>}
        {entry.event === "confirmed" && <small>{session.decision_objective
          ? `Critère enregistré · ${objectives[session.decision_objective].label}` : "Critère de comparaison non renseigné"}</small>}
      </div></li>;
    })}</ol>
  </section>;
}
