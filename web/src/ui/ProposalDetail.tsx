import { useId, useState } from "react";
import type { Candidate, FutureChange, PairedTrace, Plan, Transition } from "../api/types";
import { DECISION, TRACE_EVENT, actionShort, actionTitle, explain } from "../domain/labels";
import {
  type Assessment,
  clock,
  clockPlus,
  comparison,
  duration,
  isSelected,
  longClock,
  num,
} from "../domain/view";
import { Back } from "./icons";
import { Empty, Illu, type IlluName, proposalIllu } from "./illustrations";

export function ProposalDetail({ a }: { a: Assessment }) {
  const plan = a.plan;
  if (!plan) {
    return (
      <>
        <Head title="Aucune proposition à détailler" illu="cloud" />
        <div className="panel">
          <Empty illu="plane" title="Rien à détailler pour l'instant.">
            L'unité n'a pas encore été évaluée, ou l'évaluation s'est abstenue.{" "}
            <a className="link" href="#/">
              Revenir à l'unité
            </a>
          </Empty>
        </div>
      </>
    );
  }
  return (
    <>
      <Head
        illu={proposalIllu(plan)}
        title={plan.decision === "abstain" ? "Abstention" : actionTitle(plan.selected)}
        subtitle={`${DECISION[plan.decision]} calculée pour l'état de ${longClock(plan.created_at)}. Toutes les actions possibles ont été simulées sur les mêmes ${plan.scenarios} scénarios ; seule la décision humaine engage.`}
      />
      <div className="grid-2">
        <div className="stack">
          <Options plan={plan} />
          {a.trace ? <Trace trace={a.trace} plan={plan} /> : <NoTrace origin={a.origin} />}
        </div>
        <div className="stack">
          <Hypotheses plan={plan} />
          <Traceability plan={plan} a={a} />
        </div>
      </div>
    </>
  );
}

function Head({ title, subtitle, illu }: { title: string; subtitle?: string; illu: IlluName }) {
  return (
    <header className="page-head">
      <a className="back" href="#/">
        <Back size={14} /> Unité
      </a>
      <h1>
        <Illu name={illu} size={64} />
        {title}
      </h1>
      {subtitle ? <p>{subtitle}</p> : null}
    </header>
  );
}

// ---------------------------------------------------------------- options chart

function flags(c: Candidate, plan: Plan): string {
  const parts: string[] = [];
  const shown = isSelected(plan, c) || c.action.kind === "no_op";
  if (shown && c.scenarios_with_unserved_demand)
    parts.push(`patient non placé dans ${c.scenarios_with_unserved_demand}/${plan.scenarios} scénarios`);
  if (c.pressure_regression_scenarios)
    parts.push(`surcharge dans ${c.pressure_regression_scenarios} scénarios : écartée`);
  if (c.violations.length) parts.push(`incohérence : ${c.violations.join(", ")}`);
  return parts.join(" ; ");
}

function Options({ plan }: { plan: Plan }) {
  const [asTable, setAsTable] = useState(false);
  const toggleId = useId();
  const cmp = comparison(plan);
  const max = Math.max(1, ...plan.candidates.map((c) => c.worst_decile_waiting_patient_minutes));
  const base = cmp.baseline?.mean_waiting_patient_minutes ?? null;
  return (
    <section className="panel" aria-labelledby="options-title">
      <header className="panel__head">
        <h2 className="panel__title" id="options-title">
          <Illu name="balance" size={32} />
          Options comparées
        </h2>
        <label className="toggle" htmlFor={toggleId}>
          <input
            id={toggleId}
            type="checkbox"
            checked={asTable}
            onChange={(e) => setAsTable(e.target.checked)}
          />
          Tableau
        </label>
      </header>
      <div className="panel__body">
        <p className="note" style={{ marginBottom: "var(--s3)" }}>
          Attente cumulée simulée des patients à placer jusqu'à{" "}
          {clockPlus(plan.created_at, plan.horizon_minutes)}, en patient-minutes. Plus court est meilleur.
        </p>
        {asTable ? (
          <div
            className="table-wrap"
            tabIndex={0}
            role="group"
            aria-label="Tableau, défilement horizontal possible"
          >
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Action</th>
                  <th scope="col" className="r">
                    Moyenne
                  </th>
                  <th scope="col" className="r">
                    Pire décile
                  </th>
                  <th scope="col" className="r">
                    Écart
                  </th>
                  <th scope="col" className="r">
                    Non placés
                  </th>
                  <th scope="col" className="r">
                    Surcharge
                  </th>
                </tr>
              </thead>
              <tbody>
                {cmp.ranked.map((c) => (
                  <tr key={actionShort(c.action)} className={isSelected(plan, c) ? "is-selected" : undefined}>
                    <th scope="row" style={{ fontWeight: "inherit", color: "inherit" }}>
                      {actionShort(c.action)}
                    </th>
                    <td className="r num">{num(c.mean_waiting_patient_minutes)}</td>
                    <td className="r num">{num(c.worst_decile_waiting_patient_minutes)}</td>
                    <td className="r num">
                      {base == null ? "—" : signed(c.mean_waiting_patient_minutes - base)}
                    </td>
                    <td className="r num">
                      {c.scenarios_with_unserved_demand}/{plan.scenarios}
                    </td>
                    <td className="r num">{c.pressure_regression_scenarios}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <ul className="options">
            {cmp.ranked.map((c) => {
              const selected = isSelected(plan, c);
              const baseline = c.action.kind === "no_op";
              const f = flags(c, plan);
              return (
                <li
                  key={actionShort(c.action)}
                  className={`option${selected ? " option--selected" : ""}${baseline ? " option--baseline" : ""}`}
                  tabIndex={0}
                  aria-label={`${actionShort(c.action)} : ${num(c.mean_waiting_patient_minutes)} patient-minutes en moyenne, ${num(c.worst_decile_waiting_patient_minutes)} au pire décile${selected ? ", option retenue" : ""}${f ? `, ${f}` : ""}`}
                >
                  <span className="option__label" aria-hidden="true">
                    {actionShort(c.action)}
                    {selected ? " · retenue" : baseline ? " · référence" : ""}
                  </span>
                  <span className="option__track" aria-hidden="true">
                    <span
                      className="option__bar"
                      style={{ width: `${(c.mean_waiting_patient_minutes / max) * 100}%` }}
                    />
                    <span
                      className="option__tail"
                      style={{ left: `calc(${(c.worst_decile_waiting_patient_minutes / max) * 100}% - 1px)` }}
                    />
                  </span>
                  <span className="option__value num" aria-hidden="true">
                    {num(c.mean_waiting_patient_minutes)}
                  </span>
                  {f ? (
                    <span className="option__flags" aria-hidden="true">
                      {f}
                    </span>
                  ) : null}
                  <span className="tip" aria-hidden="true">
                    <b>{actionTitle(c.action)}</b>
                    <br />
                    Moyenne {num(c.mean_waiting_patient_minutes)} · pire décile{" "}
                    {num(c.worst_decile_waiting_patient_minutes)}
                    <br />
                    {base != null && !baseline ? (
                      <>
                        Écart à « sans action » : {signed(c.mean_waiting_patient_minutes - base)}
                        <br />
                      </>
                    ) : null}
                    Patients encore en attente en fin d'horizon : jusqu'à {c.max_waiting_at_end}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        <div className="chart-key" aria-hidden="true">
          <span>
            <i
              style={{
                width: 16,
                height: 8,
                background: "var(--brand)",
                borderRadius: "0 4px 4px 0",
                display: "inline-block",
              }}
            />{" "}
            Moyenne
          </span>
          <span>
            <i style={{ width: 2, height: 14, background: "var(--ink-2)", display: "inline-block" }} /> Pire
            décile
          </span>
        </div>
        {plan.candidates_truncated ? (
          <p className="note">Liste d'actions tronquée au budget de {plan.candidates.length} candidats.</p>
        ) : null}
      </div>
    </section>
  );
}

const signed = (v: number) => (v > 0 ? `+${num(v)}` : v < 0 ? `−${num(-v)}` : "0");

// ---------------------------------------------------------------- paired trace

const KEY_EVENTS = new Set([
  "request_transport",
  "depart",
  "clean_end",
  "admit",
  "arrival",
  "transport_start",
  "reserve",
]);

const who = (id: string | null) => (id?.startsWith("hypothetical:") ? "un patient hypothétique" : (id ?? ""));

function describe(t: Transition): string {
  const what = TRACE_EVENT[t.kind] ?? t.kind.replace(/_/g, " ");
  if (t.kind === "admit") return `${what} de ${who(t.patient_id)} en ${t.bed_id}`;
  if (t.kind === "arrival") return `${what} : nouveau patient`;
  if (t.kind === "clean_end") return `${what} : ${t.bed_id}`;
  if (t.kind === "clean_start") return `${what} : ${t.bed_id}`;
  if (t.kind === "resource_change" || t.kind === "bed_admissions")
    return `${what} : ${t.external_id ?? t.resource_id ?? ""}`;
  if (t.patient_id) return `${what} : ${who(t.patient_id)}${t.bed_id ? ` (${t.bed_id})` : ""}`;
  return what;
}

function Lanes({ trace, plan }: { trace: PairedTrace; plan: Plan }) {
  const W = 640;
  const H = 108;
  const left = 132;
  const right = 12;
  const horizon = plan.horizon_minutes;
  const x = (m: number) => left + (m / horizon) * (W - left - right);
  const lanes: Array<[string, Transition[], string]> = [
    ["Sans action", trace.baseline.trajectory.events, "var(--ink-3)"],
    ["Avec la proposition", trace.selected.trajectory.events, "var(--brand)"],
  ];
  const ticks = Array.from({ length: Math.floor(horizon / 120) + 1 }, (_, i) => i * 120);
  return (
    <svg
      className="lanes"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="Événements simulés du scénario 1, sans action et avec la proposition"
    >
      {ticks.map((m) => (
        <g key={m}>
          <line x1={x(m)} x2={x(m)} y1={8} y2={84} stroke="var(--line-soft)" />
          <text x={x(m)} y={100} textAnchor="middle">
            {clockPlus(plan.created_at, m)}
          </text>
        </g>
      ))}
      {lanes.map(([label, events, color], i) => {
        const y = 28 + i * 40;
        return (
          <g key={label}>
            <text className="lane-label" x={0} y={y + 4}>
              {label}
            </text>
            <line x1={left} x2={W - right} y1={y} y2={y} stroke="var(--line)" strokeWidth={2} />
            {events
              .filter(
                (e) => KEY_EVENTS.has(e.kind) || e.kind === "bed_admissions" || e.kind === "resource_change",
              )
              .map((e, j) => {
                const hypo =
                  e.kind === "arrival" || e.kind === "resource_change" || e.kind === "bed_admissions";
                const admit = e.kind === "admit";
                return (
                  <g key={j}>
                    <title>{`${clockPlus(plan.created_at, e.minute)} — ${describe(e)}`}</title>
                    {admit ? (
                      <circle
                        cx={x(e.minute)}
                        cy={y}
                        r={6}
                        fill={color}
                        stroke="var(--sheet)"
                        strokeWidth={2}
                      />
                    ) : hypo ? (
                      <rect
                        x={x(e.minute) - 4}
                        y={y - 4}
                        width={8}
                        height={8}
                        transform={`rotate(45 ${x(e.minute)} ${y})`}
                        fill="var(--sheet)"
                        stroke="var(--ink-3)"
                        strokeWidth={1.5}
                      />
                    ) : (
                      <circle
                        cx={x(e.minute)}
                        cy={y}
                        r={4.5}
                        fill="var(--sheet)"
                        stroke={color}
                        strokeWidth={2}
                      />
                    )}
                  </g>
                );
              })}
          </g>
        );
      })}
    </svg>
  );
}

function Trace({ trace, plan }: { trace: PairedTrace; plan: Plan }) {
  const list = (events: Transition[]) =>
    events
      .filter((e) => KEY_EVENTS.has(e.kind) || e.kind === "resource_change" || e.kind === "bed_admissions")
      .slice(0, 20);
  return (
    <section className="panel" aria-labelledby="trace-title">
      <header className="panel__head">
        <h2 className="panel__title" id="trace-title">
          <Illu name="path" size={32} />
          Déroulé simulé, scénario 1 sur {plan.scenarios}
        </h2>
      </header>
      <div className="panel__body">
        <p className="note" style={{ marginBottom: "var(--s3)" }}>
          Les deux déroulés partagent les mêmes tirages : seule l'action diffère. Les losanges sont des
          hypothèses déclarées (arrivées, capacités).
        </p>
        <Lanes trace={trace} plan={plan} />
        <div className="timeline">
          {(
            [
              ["Sans action", trace.baseline],
              ["Avec la proposition", trace.selected],
            ] as const
          ).map(([label, side]) => (
            <div key={label}>
              <h3>{label}</h3>
              <ol>
                {list(side.trajectory.events).map((e, i) => (
                  <li
                    key={i}
                    className={
                      e.kind === "arrival" || e.kind === "resource_change" || e.kind === "bed_admissions"
                        ? "is-hypo"
                        : undefined
                    }
                  >
                    <time className="num">{clockPlus(plan.created_at, e.minute)}</time>
                    <span>{describe(e)}</span>
                  </li>
                ))}
              </ol>
              <p className="score">
                <span>
                  Attente <b className="num">{num(side.score.waiting_patient_minutes)}</b> patient-min
                </span>
                <span>
                  Admis <b className="num">{side.score.admitted}</b>
                </span>
                <span>
                  En attente à la fin <b className="num">{side.score.waiting_at_end}</b>
                </span>
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function NoTrace({ origin }: { origin: Assessment["origin"] }) {
  return (
    <section className="panel">
      <header className="panel__head">
        <h2 className="panel__title">
          <Illu name="path" size={32} />
          Déroulé simulé
        </h2>
      </header>
      <Empty illu="magnifier" title="Pas de déroulé à montrer.">
        {origin === "fixture"
          ? "La planification s'est abstenue : il n'y a rien eu à simuler."
          : "L'API locale ne renvoie pas le déroulé détaillé. Il est disponible via la ligne de commande (--show-trace) et dans les données de démonstration."}
      </Empty>
    </section>
  );
}

// ---------------------------------------------------------------- hypotheses

const range = (values: number[]) => {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  return lo === hi ? duration(lo) : `${duration(lo)} à ${duration(hi)}`;
};

function change(c: FutureChange, at: string): string {
  const when = clockPlus(at, c.minute);
  if (c.kind === "bed_admissions")
    return `${when} : lit ${c.bed_id} ${c.admissions_open ? "rouvert aux admissions" : "fermé aux admissions"}`;
  const what = {
    staffed_beds: "lits armés",
    cleaning_teams: "équipes de bionettoyage",
    transport: "transport",
    downstream: "places d'aval",
  }[c.resource];
  return `${when} : ${what} (${c.target_id}) ramenés à ${c.capacity}`;
}

function Hypotheses({ plan }: { plan: Plan }) {
  const h = plan.assumptions;
  return (
    <section className="panel" aria-labelledby="hyp-title">
      <header className="panel__head">
        <h2 className="panel__title" id="hyp-title">
          <Illu name="bulb" size={32} />
          Hypothèses déclarées
        </h2>
        <span className="pill pill--warn">synthétiques</span>
      </header>
      <div className="panel__body">
        <dl className="dl">
          <dt>Préparation au départ</dt>
          <dd>{range(h.departure_minutes)}</dd>
          <dt>Trajet du transport</dt>
          <dd>{range(h.transport_minutes)}</dd>
          <dt>Retour du transport</dt>
          <dd>{range(h.transport_return_minutes)}</dd>
          <dt>Bionettoyage</dt>
          <dd>{range(h.cleaning_minutes)}</dd>
          <dt>Charge commune</dt>
          <dd>multiplicateurs {h.load_multipliers.map((m) => `×${m}`).join(", ")} tirés par scénario</dd>
          {plan.future ? (
            <>
              <dt>Arrivées supposées</dt>
              <dd>
                {plan.future.arrivals.length === 0
                  ? "aucune"
                  : plan.future.arrivals
                      .map(
                        (b) =>
                          `${b.count_options.join(" à ")} patients vers ${b.minute_options.map((m) => clockPlus(plan.created_at, m)).join(", ")} (priorité ${b.priority})`,
                      )
                      .join(" ; ")}
              </dd>
              <dt>Changements de capacité</dt>
              <dd>
                <ul>
                  {plan.future.changes.map((c) => (
                    <li key={c.id}>{change(c, plan.created_at)}</li>
                  ))}
                </ul>
              </dd>
            </>
          ) : (
            <>
              <dt>Futur</dt>
              <dd>Aucune arrivée ni changement de capacité déclarés.</dd>
            </>
          )}
        </dl>
        <p className="note" style={{ marginTop: "var(--s4)" }}>
          Ces durées ne sont calibrées sur aucun établissement. Elles servent à comparer les options entre
          elles, pas à prévoir l'heure réelle d'un départ.
        </p>
      </div>
    </section>
  );
}

function Traceability({ plan, a }: { plan: Plan; a: Assessment }) {
  return (
    <section className="panel" aria-labelledby="trace-id-title">
      <header className="panel__head">
        <h2 className="panel__title" id="trace-id-title">
          <Illu name="tag" size={32} />
          Traçabilité
        </h2>
      </header>
      <div className="panel__body">
        <dl className="dl">
          <dt>Décision</dt>
          <dd>{DECISION[plan.decision]}</dd>
          <dt>Motifs</dt>
          <dd>
            {plan.reasons.map((r) => (
              <span key={r} title={r} style={{ display: "block" }}>
                {explain(r)}
              </span>
            ))}
          </dd>
          <dt>Calculée pour</dt>
          <dd>{longClock(plan.created_at)}</dd>
          <dt>Expire à</dt>
          <dd>{clock(plan.expires_at)}</dd>
          <dt>Scénarios, horizon</dt>
          <dd>
            {plan.scenarios} scénarios, {duration(plan.horizon_minutes)}, graine {plan.seed}, poids du pire
            décile {plan.tail_weight.toLocaleString("fr-FR")}
          </dd>
          <dt>Plan</dt>
          <dd className="hash" translate="no">
            {plan.plan_id.slice(0, 16)}
          </dd>
          <dt>Empreinte de l'état</dt>
          <dd className="hash" translate="no">
            {plan.state_fingerprint.slice(0, 16)}
          </dd>
          {a.episodeId ? (
            <>
              <dt>Épisode d'observation</dt>
              <dd className="hash" translate="no">
                {a.episodeId.slice(0, 16)}
              </dd>
            </>
          ) : null}
          <dt>Contrat</dt>
          <dd translate="no">{plan.schema_version}</dd>
        </dl>
      </div>
    </section>
  );
}
