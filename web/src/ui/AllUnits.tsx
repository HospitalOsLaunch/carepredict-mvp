import { type UnitSummary, clock, duration, waitText } from "../domain/view";
import { Illu } from "./illustrations";

// Every unit at once (user feedback: « comment voir toutes les unités à la fois »). One row per
// unit, the most tense first: who waits, what is usable, departures, the priority action and
// what it gains, doubts. Opening a unit lands on its page.

const STATUS: Record<UnitSummary["decision"], [string, string]> = {
  recommend: ["Action proposée", "pill--brand"],
  no_change: ["Rien à changer", "pill--ok"],
  abstain: ["Données à vérifier", "pill--warn"],
  pending: ["Non évaluée", ""],
};

const tension = (s: UnitSummary) =>
  s.decision === "pending" ? -1 : s.waiting * 1000 + (s.longestWaitMinutes ?? 0) - s.usable * 100;

export function AllUnits(props: {
  summaries: UnitSummary[];
  current: string;
  onOpen: (id: string) => void;
  live: boolean;
}) {
  const rows = [...props.summaries].sort((a, b) => tension(b) - tension(a));
  const known = rows.filter((s) => s.decision !== "pending" && !s.doubtful);
  const total = {
    waiting: known.reduce((n, s) => n + s.waiting, 0),
    usable: known.reduce((n, s) => n + s.usable, 0),
    proposals: rows.filter((s) => s.decision === "recommend").length,
    doubts: rows.filter((s) => s.decision === "abstain" || s.doubtful).length,
  };
  return (
    <div className="allunits">
      <header className="page-head">
        <h1>
          <Illu name="signpost" size={64} />
          Toutes les unités
        </h1>
        <p>
          La plus tendue en premier. {total.waiting} patient
          {total.waiting > 1 ? "s" : ""} à placer et {total.usable} lit
          {total.usable > 1 ? "s" : ""} utilisable{total.usable > 1 ? "s" : ""} dans les unités aux données sûres ·{" "}
          {total.proposals} action
          {total.proposals > 1 ? "s" : ""} proposée
          {total.proposals > 1 ? "s" : ""}
          {total.doubts ? ` · ${total.doubts} unité${total.doubts > 1 ? "s" : ""} à vérifier` : ""}.
        </p>
        {props.live ? (
          <p className="note">Connexion à l'unité en observation : les autres unités ne sont pas encore raccordées.</p>
        ) : null}
      </header>
      <div className="table-wrap">
        <table className="table allunits__table" data-testid="all-units">
          <thead>
            <tr>
              <th scope="col">Unité</th>
              <th scope="col" className="r">
                À placer
              </th>
              <th scope="col" className="r">
                Lits utilisables
              </th>
              <th scope="col" className="r">
                Sorties prêtes
              </th>
              <th scope="col">Action prioritaire</th>
              <th scope="col">
                <span className="visually-hidden">Ouvrir</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const [label, tone] = STATUS[s.decision];
              const unknown = s.decision === "pending" || s.doubtful;
              return (
                <tr key={s.id} className={s.id === props.current ? "is-current" : undefined}>
                  <th scope="row">
                    <span className="allunits__head">
                      <button type="button" className="allunits__name" onClick={() => props.onOpen(s.id)}>
                        {s.name}
                      </button>
                      <span className={`pill ${tone}`}>{label}</span>
                      {s.stateAt ? <span className="allunits__at">état {clock(s.stateAt)}</span> : null}
                    </span>
                  </th>
                  <td className="r num" data-label="À placer">
                    {unknown ? "?" : s.waiting}
                    {!unknown && s.longestWaitMinutes != null ? (
                      <small>attente max {duration(s.longestWaitMinutes)}</small>
                    ) : null}
                  </td>
                  <td className="r num" data-label="Lits utilisables">
                    {unknown ? "?" : s.usable}
                    {!unknown && s.dirty ? <small>{s.dirty} à nettoyer</small> : null}
                  </td>
                  <td className="r num" data-label="Sorties prêtes">
                    {unknown || !s.departures ? "?" : `${s.departures.ready}/${s.departures.total}`}
                  </td>
                  <td className="allunits__act">
                    {s.action ? (
                      <>
                        <span className="allunits__action">{s.action}</span>
                        {s.saved != null && s.saved > 0.5 ? (
                          <small className="allunits__gain">−{waitText(s.saved)} d'attente</small>
                        ) : null}
                      </>
                    ) : s.decision === "abstain" ? (
                      <span className="mute">
                        {s.checks} donnée{(s.checks ?? 0) > 1 ? "s" : ""} à vérifier
                      </span>
                    ) : s.decision === "no_change" ? (
                      <span className="mute">Rien à changer</span>
                    ) : (
                      <span className="mute">—</span>
                    )}
                  </td>
                  <td className="r allunits__open">
                    <button type="button" className="btn btn--small" onClick={() => props.onOpen(s.id)}>
                      Ouvrir
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
