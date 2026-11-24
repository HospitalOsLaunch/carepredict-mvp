import { actionTitle } from "../domain/labels";
import { type Assessment, bedElsewhere, duration, gainOf, steps, waitText } from "../domain/view";
import { bundleTitle } from "../data/journal";
import { DecisionPlan } from "./DecisionPlan";
import { Illu } from "./illustrations";

// One Plan tab, several focal lengths (user feedback: « un plan à 7 j, 2 j, 3 j, demi-journée »).
// The engines plan up to 24 h, by design: the focal never stretches a plan beyond what was
// computed. « Maintenant » = the unit engine's priority action (combination included); 12 h and
// 24 h = the 24-hour plan, read through a window; 3 and 7 days = a perspective, explicitly not
// planned. See DESIGN.md « Plan : focales ».

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

function NowFocal({ a, unitName }: { a: Assessment | null; unitName: string }) {
  if (!a) return <div className="skeleton" aria-busy="true" aria-label="Chargement de l'unité" />;
  const plan = a.plan;
  const unit = a.state.units[0]?.id ?? "";
  const todo = plan && plan.decision === "recommend" ? steps(plan) : [];
  const where = (x: (typeof todo)[number]) => bedElsewhere(a.state, x, unit);
  const gain = plan && plan.decision === "recommend" ? gainOf(plan) : null;
  const marg = plan?.bundle_marginal_minutes ?? [];
  return (
    <div className="ds-page" data-testid="focal-now">
      <header className="page-head">
        <h1>
          <Illu name="key" size={64} />
          Maintenant · {unitName}
        </h1>
        <p>
          L'action à lancer tout de suite dans l'unité, calculée par le planificateur de l'unité : transport,
          bionettoyage, réservation de lit, seuls ou combinés. Renforts et entrées programmées se préparent sur les
          focales 12 h et 24 h.
        </p>
      </header>
      <section className="panel proposal" aria-labelledby="now-title">
        <div className="proposal__band">
          <span className="proposal__kind">
            {todo.length > 1 ? `Action prioritaire · ${todo.length} gestes ensemble` : "Action prioritaire"}
          </span>
        </div>
        <div className="proposal__main">
          <div className="ds-stack">
            {todo.length ? (
              <>
                <h2 id="now-title" className="proposal__title">
                  {todo.length > 1 ? bundleTitle(todo, where) : actionTitle(todo[0]!, where(todo[0]!))}
                </h2>
                {todo.length > 1 ? (
                  <ol className="steps">
                    {todo.map((s, i) => (
                      <li key={i} className="steps__item">
                        <span className="steps__text">{actionTitle(s, where(s))}</span>
                        {marg[i] != null ? <span className="steps__gain num">−{waitText(marg[i]!)}</span> : null}
                      </li>
                    ))}
                  </ol>
                ) : null}
                {gain ? (
                  <p className="effect__line">
                    <b>−{waitText(gain.saved)} d'attente</b> pour les patients à placer d'ici {gain.until}, sur{" "}
                    {duration(gain.windowMinutes)} simulées (sans rien faire : {waitText(gain.before)}).
                  </p>
                ) : null}
              </>
            ) : (
              <h2 id="now-title" className="proposal__title">
                {plan?.decision === "no_change"
                  ? "Rien à lancer maintenant"
                  : "Pas d'action proposée : des données sont à vérifier"}
              </h2>
            )}
          </div>
        </div>
        <div className="proposal__actions">
          <a className="btn btn--primary" href="#/">
            Décider sur la page unité
          </a>
        </div>
      </section>
    </div>
  );
}

export function PlanTab({ focal, a, unitName }: { focal: Focal; a: Assessment | null; unitName: string }) {
  return (
    <>
      <FocalBar focal={focal} />
      {focal === "maintenant" ? <NowFocal a={a} unitName={unitName} /> : <DecisionPlan focal={focal} />}
    </>
  );
}
