import type { FeedKind, LiveSnapshot, Plan } from "../api/types";
import { longClock } from "../domain/view";
import { source } from "./unitSource";

const labels: Record<FeedKind, string> = {
  bookings: "Entrées programmées",
  departures: "Dates de sortie prévisionnelles",
  roster: "Planning soignant validé",
  emergency: "Prévision des arrivées par les urgences",
};
const reasons: Record<string, string> = {
  missing: "Aucun reçu",
  scope: "Périmètre incohérent",
  conflict: "Versions en conflit",
  outage: "Source en panne",
  partial: "Export partiel",
  stale: "Source périmée",
  coverage: "Période incomplète",
  duplicate_booking: "Entrée en double",
  future_record: "Horodatage postérieur à la publication",
  future_admission: "Admission postérieure à la revue du séjour",
  admission_clock_missing: "Heure d’admission manquante pour un séjour présent",
  duplicate_stay: "Séjour en double",
  discharge_coverage: "Couverture des séjours insuffisante",
  census_incomplete: "Recensement incomplet pour calculer la couverture",
  capacity_conflict: "Capacité du planning incompatible avec celle observée",
  shift_or_skill_gap: "Créneau, validation ou compétence manquante, ou double affectation",
  daily_coverage: "Jours manquants ou en double",
  qualification_missing: "Prévisions non qualifiées",
  cohort_ranking_unqualified: "Classement des gestes avec les nouveaux flux non qualifié",
  accuracy_gate: "Précision prédictive insuffisante",
  source_gate: "Sources à vérifier",
};
export function OutlookQuality({ plan }: { plan: Plan | LiveSnapshot | null }) {
  return (
    <section className="panel" aria-labelledby="outlook-title" data-testid="outlook-quality">
      <h2 id="outlook-title">Sources du plan à plusieurs jours</h2>
      {plan && "shadow_flow" in plan && !!plan.shadow_flow?.length && (
        <div data-testid="flow-shadow">
          <h3>Projection des flux en observation</h3>
          <p>Moyennes simulées sans geste ajouté. Le classement des actions utilise le moteur de référence.</p>
          <table>
            <thead><tr><th>Horizon</th><th>Admissions</th><th>Sorties</th><th>Lits occupés</th></tr></thead>
            <tbody>{plan.shadow_flow.map((w, i) => (
              <tr key={w.minutes}>
                <th {...source(plan, `/shadow_flow/${i}/minutes`)}>{w.minutes / 60} h</th>
                {(["mean_admissions", "mean_departures", "mean_occupied"] as const).map((k) => (
                  <td key={k} {...source(plan, `/shadow_flow/${i}/${k}`)}>{w[k].toLocaleString("fr-FR", { maximumFractionDigits: 1 })}</td>
                ))}
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {!plan?.horizons?.length ? (
        <ul>
          {Object.entries(labels).map(([k, v]) => (
            <li key={k}>{v} · Aucun reçu évalué</li>
          ))}
        </ul>
      ) : (
        plan.horizons.map((h, j) => (
          <details key={h.days} open={j === 0}>
            <summary>
              <b {...source(plan, `/horizons/${j}/days`)}>J+{h.days}</b> ·{" "}
              {h.qualified && h.data_ready ? "Plan évalué" : "Perspective non planifiée"}
            </summary>
            <p>{h.reasons.map((r) => reasons[r] ?? r).join(" · ")}</p>
            <dl>
              {h.feeds.map((f, i) => {
                const ref = `/horizons/${j}/feeds/${i}`;
                return (
                  <div key={f.kind}>
                    <dt>
                      <strong>{labels[f.kind]}</strong>
                    </dt>
                    <dd>
                      {f.reasons.length ? f.reasons.map((r) => reasons[r] ?? r).join(" · ") : "Source prête"}
                      {f.source && (
                        <>
                          {" "}
                          · {f.source} (version <span {...source(plan, ref + "/revision")}>{f.revision}</span>
                          )
                        </>
                      )}
                      {f.received_at && (
                        <>
                          {" "}
                          · reçu{" "}
                          <time {...source(plan, ref + "/received_at")}>{longClock(f.received_at)}</time>
                        </>
                      )}
                      {f.synced_at && (
                        <>
                          {" "}
                          · synchronisé{" "}
                          <time {...source(plan, ref + "/synced_at")}>{longClock(f.synced_at)}</time>
                        </>
                      )}
                      {f.covers_until && (
                        <>
                          {" "}
                          · couvert jusqu’au{" "}
                          <time {...source(plan, ref + "/covers_until")}>{longClock(f.covers_until)}</time>
                        </>
                      )}
                      {f.expected != null && (
                        <>
                          {" "}
                          · <span {...source(plan, ref + "/covered")}>{f.covered}</span> /{" "}
                          <span {...source(plan, ref + "/expected")}>{f.expected}</span>{" "}
                          {f.kind === "departures" ? "séjours" : "jours"}
                        </>
                      )}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </details>
        ))
      )}
    </section>
  );
}
