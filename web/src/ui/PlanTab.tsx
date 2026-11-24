import { actionTitle } from "../domain/labels";
import { type Assessment, clock, steps, waitText } from "../domain/view";
import { bundleTitle } from "../data/journal";
import { Illu } from "./illustrations";
import { source } from "./unitSource";

export type Focal = "maintenant" | "12h" | "24h" | "3j" | "7j";

export const FOCALS: Array<{ id: Focal; label: string; hint: string }> = [
  { id: "maintenant", label: "Maintenant", hint: "action prioritaire" },
  { id: "12h", label: "12 h", hint: "la garde" },
  { id: "24h", label: "24 h", hint: "jusqu'à demain" },
  { id: "3j", label: "3 jours", hint: "perspective" },
  { id: "7j", label: "7 jours", hint: "perspective" },
];

export function readFocal(param: string | null): Focal {
  return FOCALS.some((f) => f.id === param) ? (param as Focal) : "24h";
}

function FocalBar({ focal }: { focal: Focal }) {
  return (
    <nav className="focals" aria-label="Horizon du plan" data-testid="focals">
      {FOCALS.map((f) => (
        <a
          key={f.id}
          href={`#/plan/${f.id}`}
          className={`focals__item${f.id === "3j" || f.id === "7j" ? " focals__item--far" : ""}`}
          aria-current={f.id === focal ? "true" : undefined}
          data-testid={`focal-${f.id}`}
        >
          <b>{f.label}</b>
          <small>{f.hint}</small>
        </a>
      ))}
    </nav>
  );
}

export function PlanTab({ focal, a, unitName }: { focal: Focal; a: Assessment | null; unitName: string }) {
  const plan = a?.plan;
  const far = focal === "3j" || focal === "7j";
  const duration = { maintenant: plan?.horizon_minutes, "12h": 720, "24h": 1440, "3j": 4320, "7j": 10080 }[focal];
  const index = plan?.windows?.findIndex(w => w.minutes === duration) ?? -1;
  const win = plan?.windows?.[index];
  const prefix = `/windows/${index}`;
  const todo = plan?.decision === "recommend" ? steps(plan) : [];
  return <>
    <FocalBar focal={focal} />
    <div className="ds-page" data-plan-id={plan?.plan_id} data-unit={plan?.unit_id}
      data-testid={focal === "maintenant" ? "focal-now" : "unit-plan"}>
      <header className="page-head"><h1><Illu name="key" size={56} />
        {FOCALS.find(f => f.id === focal)?.label} · {unitName}</h1>
        {plan && <p>Évaluation de l’unité à <time {...source(plan,"/created_at")}>{clock(plan.created_at)}</time>.</p>}
      </header>
      {far && !win ? <section className="panel" data-testid="ds-perspective">
        <h2>Perspective, non planifiée</h2><p>La planification à cet horizon attend la qualification des sources et des prévisions.</p>
        <a href="#/donnees" className="linkbtn">Voir les contrôles de l’unité</a>
      </section> : !plan || !win ? <section className="panel"><h2>{!a ? "Chargement de l’unité" : "Évaluation indisponible à cet horizon"}</h2>
        <a href="#/donnees">Consulter les données de l’unité</a></section> :
      <section className="panel proposal" data-testid="unit-evaluation">
        <div className="proposal__main"><div className="ds-stack">
          <h2>{todo.length ? bundleTitle(todo) : "Rien à lancer maintenant"}</h2>
          {todo.length > 0 && <ul className="steps">{todo.map((action,i) => {
            const offer = a?.state.schedules?.flatMap(s => s.offers).find(o => o.option.option_id === action.slot_id)?.option;
            const booking = a?.state.schedules?.flatMap(s => s.admissions).find(b => b.request.request_id === action.slot_id);
            return <li key={i} className="steps__item" {...source(plan,plan.bundle?.length ? `/bundle/${i}` : "/selected")}>
              {actionTitle(action)}
              {offer && <small>{offer.skill} · {clock(offer.start)}–{clock(offer.end)}{offer.lending_unit && ` · prêt de ${offer.lending_unit}`}</small>}
              {booking && <small>Accueil prévu de {clock(booking.window_start)} à {clock(booking.window_end)}</small>}
            </li>;
          })}</ul>}
          <p data-testid="window-until">Attente cumulée jusqu’à <b {...source(plan,prefix+"/until")}>{clock(win.until)}</b></p>
          <dl className="kv-strip">
            {([["Sans action","baseline_wait"],["Avec le plan","selected_wait"],["Attente évitée","saved_wait"]] as const).map(([label,key]) =>
              <div className="kv" key={key}><dt>{label}</dt><dd className="num" {...source(plan,prefix+"/"+key)}>
                {win[key] < 0 ? "−" : ""}{waitText(win[key])}</dd></div>)}
          </dl>
          <a className="btn btn--primary" href="#/">Examiner la décision sur la page unité</a>
        </div></div>
      </section>}
    </div>
  </>;
}
