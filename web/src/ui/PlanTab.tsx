import { actionTitle } from "../domain/labels";
import { type Assessment, clock, longClock, steps, waitText } from "../domain/view";
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

function FocalBar({ focal, plan }: { focal: Focal; plan: Assessment["plan"] }) {
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
          <small>
            {(f.id === "3j" || f.id === "7j") &&
            plan?.windows?.some((w) => w.minutes === (f.id === "3j" ? 4320 : 10080))
              ? "plan calculé"
              : f.hint}
          </small>
        </a>
      ))}
    </nav>
  );
}

export function PlanTab({ focal, a, unitName }: { focal: Focal; a: Assessment | null; unitName: string }) {
  const plan = a?.plan;
  const far = focal === "3j" || focal === "7j";
  const duration = { maintenant: plan?.horizon_minutes, "12h": 720, "24h": 1440, "3j": 4320, "7j": 10080 }[
    focal
  ];
  const index = plan?.windows?.findIndex((w) => w.minutes === duration) ?? -1;
  const win = plan?.windows?.[index];
  const prefix = `/windows/${index}`;
  const horizonIndex = plan?.horizons?.findIndex((h) => h.days === (focal === "3j" ? 3 : 7)) ?? -1;
  const horizon = plan?.horizons?.[horizonIndex];
  const todo = plan?.decision === "recommend" ? steps(plan) : [];
  return (
    <>
      <FocalBar focal={focal} plan={plan ?? null} />
      <div
        className="ds-page"
        data-plan-id={plan?.plan_id}
        data-unit={plan?.unit_id}
        data-testid={focal === "maintenant" ? "focal-now" : "unit-plan"}
      >
        <header className="page-head">
          <h1>
            <Illu name="key" size={56} />
            {FOCALS.find((f) => f.id === focal)?.label} · {unitName}
          </h1>
          {plan && (
            <p>
              Évaluation de l’unité à <time {...source(plan, "/created_at")}>{clock(plan.created_at)}</time>.
            </p>
          )}
        </header>
        {far && !win ? (
          <section className="panel" data-testid="ds-perspective">
            <h2>Perspective, non planifiée</h2>
            <p>La planification à cet horizon attend la qualification des sources et des prévisions.</p>
            {plan && horizon && (
              <>
                <p>
                  {horizon.reasons.includes("accuracy_gate")
                    ? "La précision requise pour prévoir les lits occupés et les urgences n’est pas atteinte."
                    : null}
                  {horizon.reasons.includes("source_gate")
                    ? " Certaines sources sont absentes ou incomplètes."
                    : null}
                </p>
                <table>
                  <caption>Éléments connus à la relève · {unitName}</caption>
                  <thead>
                    <tr>
                      <th>Jour</th>
                      <th>Entrées programmées</th>
                      <th>Sorties estimées</th>
                      <th>Lits armés, minimum</th>
                      <th>Urgences attendues sur le jour civil</th>
                    </tr>
                  </thead>
                  <tbody>
                    {horizon.perspective.map((row, i) => (
                      <tr key={row.day}>
                        <th {...source(plan, `/horizons/${horizonIndex}/perspective/${i}/day`)}>{row.day}</th>
                        {(
                          [
                            "bookings",
                            "estimated_departures",
                            "min_staffed_beds",
                            "expected_ed_full_day",
                          ] as const
                        ).map((k) => (
                          <td key={k} {...source(plan, `/horizons/${horizonIndex}/perspective/${i}/${k}`)}>
                            {row[k] == null
                              ? "Inconnu"
                              : row[k].toLocaleString("fr-FR", { maximumFractionDigits: 1 })}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
            <a href="#/donnees" className="linkbtn">
              Voir les contrôles de l’unité
            </a>
          </section>
        ) : !plan || !win ? (
          <section className="panel">
            <h2>{!a ? "Chargement de l’unité" : "Évaluation indisponible à cet horizon"}</h2>
            <a href="#/donnees">Consulter les données de l’unité</a>
          </section>
        ) : (
          <section className="panel proposal" data-testid="unit-evaluation">
            <div className="proposal__main">
              <div className="ds-stack">
                <h2>{todo.length ? bundleTitle(todo) : "Rien à lancer maintenant"}</h2>
                {todo.length > 0 && (
                  <ul className="steps">
                    {todo.map((action, i) => {
                      const slot = plan.action_timing?.[i];
                      const pointer = `/action_timing/${i}`;
                      const later = slot && Date.parse(slot.starts_at) >= Date.parse(win.until);
                      return (
                        <li key={i} className="steps__item">
                          <span {...source(plan, plan.bundle?.length ? `/bundle/${i}` : "/selected")}>
                            {actionTitle(action)}
                          </span>
                          {slot?.ends_at && (
                            <small>
                              {later ? "Après cette fenêtre · " : ""}
                              {slot.skill && `${slot.skill} · `}
                              <time {...source(plan, pointer + "/starts_at")}>
                                {longClock(slot.starts_at)}
                              </time>{" "}
                              –<time {...source(plan, pointer + "/ends_at")}>{longClock(slot.ends_at)}</time>
                              {slot.lender && ` · prêt de ${slot.lender}`}
                            </small>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
                <p data-testid="window-until">
                  Attente cumulée jusqu’à <b {...source(plan, prefix + "/until")}>{longClock(win.until)}</b>
                </p>
                <dl className="kv-strip">
                  {(
                    [
                      ["Sans action", "baseline_wait"],
                      ["Avec le plan", "selected_wait"],
                      ["Attente évitée", "saved_wait"],
                    ] as const
                  ).map(([label, key]) => (
                    <div className="kv" key={key}>
                      <dt>{label}</dt>
                      <dd className="num" {...source(plan, prefix + "/" + key)}>
                        {win[key] < 0 ? "−" : ""}
                        {waitText(win[key])}
                      </dd>
                    </div>
                  ))}
                </dl>
                <a className="btn btn--primary" href="#/">
                  Examiner la décision sur la page unité
                </a>
              </div>
            </div>
          </section>
        )}
      </div>
    </>
  );
}
