import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  type DecisionRecord,
  REASONS,
  STATUS,
  type Status,
  abstentionRecord,
  bundleTitle,
  journal,
  otherOptions,
  reasonLabel,
  recordFor,
  statusOf,
  deltaText,
  todoHint,
  useJournal,
  who,
} from "../data/journal";
import { actionTitle, explain } from "../domain/labels";
import type { Action, Plan } from "../api/types";
import {
  type Assessment,
  type Gain,
  type Practice,
  delayText,
  delaysText,
  practiceOf,
  savedText,
  aheadOf,
  bedElsewhere,
  clock,
  clockPlus,
  comparison,
  duration,
  gainOf,
  gateGroups,
  minutesBetween,
  oldestFact,
  pct,
  proposalContext,
  steps,
  waitText,
} from "../domain/view";
import { source as planSource } from "./unitSource";
import { Ban, Check, Clock, Refresh } from "./icons";
import { Illu, proposalIllu } from "./illustrations";

const GENERIC = new Set([
  "lower_simulated_waiting_cost_requires_human_approval",
  "no_admissible_simulated_improvement",
]);

export type ToastFn = (message: string, undo?: () => void) => void;

interface Props {
  a: Assessment;
  unit: { id: string; name: string };
  now: string;
  busy: boolean;
  awaitingEvaluation: boolean;
  onEvaluate: () => void;
  onToast: ToastFn;
}

export function Proposal({ a, unit, now, busy, awaitingEvaluation, onEvaluate, onToast }: Props) {
  const plan = a.plan;
  // Only a connection to the unit in observation evaluates « now »; a replay recomputes.
  const live = a.origin === "api-live";
  const evaluateLabel = live ? "Évaluer maintenant" : "Recalculer";

  // Every proposal and every abstention leaves a trace in the decision journal.
  const traced = useMemo(() => {
    if (awaitingEvaluation) return null;
    if (plan && plan.decision !== "no_change") return recordFor(a, unit, plan);
    if (!plan && a.gateReasons.length)
      return abstentionRecord(a, unit, a.episodeId ?? `${unit.id}@${a.state.at}`);
    return null;
  }, [a, unit, plan, awaitingEvaluation]);
  useEffect(() => {
    if (traced) journal.register(traced);
  }, [traced]);
  const { records } = useJournal();
  const current = traced ? (records.find((r) => r.id === traced.id) ?? traced) : null;

  // Empty or doubtful: a compact line, not a big card (user feedback).
  if (awaitingEvaluation || (!plan && a.gateReasons.length === 0)) {
    return (
      <section className="panel proposal proposal--compact" aria-labelledby="proposal-title">
        <div className="compact">
          <Illu name="plane" size={36} className="compact__illu" />
          <div className="compact__text">
            <h2 className="compact__title" id="proposal-title">
              Prêt à évaluer l'unité
            </h2>
            <p className="mute">HospitalOS simule les prochaines heures et propose l'action la plus utile.</p>
          </div>
          <button className="btn btn--primary" onClick={onEvaluate} disabled={busy}>
            <Refresh /> {busy ? "Évaluation…" : evaluateLabel}
          </button>
        </div>
      </section>
    );
  }

  if (!plan || plan.decision === "abstain") {
    const codes = a.gateReasons.length ? a.gateReasons : (plan?.reasons ?? []);
    return (
      <Abstention
        codes={codes}
        busy={busy}
        onEvaluate={onEvaluate}
        source={<Source a={a} plan={plan} busy={busy} onEvaluate={onEvaluate} label={evaluateLabel} />}
      />
    );
  }

  const cmp = comparison(plan);
  const gain = gainOf(plan);
  const practice = practiceOf(plan);
  const expiresAt = a.expiresAt ?? plan.expires_at;
  const minutesLeft = minutesBetween(now, expiresAt);
  const expired = minutesLeft <= 0;
  const quiet = plan.decision === "no_change";
  const todo = steps(plan);
  const combined = todo.length > 1;
  const where = (x: Action) => bedElsewhere(a.state, x, unit.id);
  const context = proposalContext(a.state, plan);
  // A gain of 1 % is not presented like a gain of 30 % (user testing): same card, honest words.
  const lowGain = cmp.deltaRatio != null && Math.abs(cmp.deltaRatio) < 0.05;
  const down = aheadOf(plan).find((x) => x.tone === "warn" && x.text.startsWith("Transport"));
  const facts = [
    ...(down && todo.some((x) => x.kind === "request_transport")
      ? [`${down.text} (hypothèse déclarée) : la demande sera servie à la reprise.`]
      : []),
    ...(lowGain ? ["Gain faible : à faire si le temps le permet, rien d'urgent."] : []),
    ...(combined ? [] : context),
    ...plan.warnings.map(explain),
    ...plan.reasons.filter((r) => !GENERIC.has(r)).map(explain),
  ].slice(0, 2);

  if (quiet) {
    return (
      <section className="panel proposal proposal--compact" aria-labelledby="proposal-title">
        <div className="compact">
          <Illu name="boat" size={36} className="compact__illu" />
          <div className="compact__text">
            <h2 className="compact__title" id="proposal-title">
              Rien à changer pour l'instant
            </h2>
            <p className="mute">
              Aucune des {plan.candidates.length - 1} actions simulées ne ferait mieux d'ici{" "}
              {clockPlus(plan.created_at, plan.horizon_minutes)}.
            </p>
          </div>
          <a className="btn btn--quiet" href="#/proposition">
            Options comparées
          </a>
        </div>
        <Source a={a} plan={plan} busy={busy} onEvaluate={onEvaluate} label={evaluateLabel} />
      </section>
    );
  }

  const pending = current && statusOf(current, now) === "pending";
  return (
    <section className="panel proposal" aria-labelledby="proposal-title" data-testid="proposal" data-plan-id={plan.plan_id} data-unit={plan.unit_id}>
      <Band
        label={
          pending && practice?.contenders.length
            ? "Action prioritaire · à départager selon votre pratique"
            : pending && lowGain
            ? "Option à faible gain"
            : pending
              ? combined
                ? `Action prioritaire · ${todo.length} gestes ensemble`
                : "Action prioritaire"
              : bandLabel(current, now)
        }
        right={pending ? <span className="expiry">Fraîche encore {duration(minutesLeft)}</span> : null}
      />
      <div className="proposal__main">
        <div className="proposal__lead">
          <Illu name={proposalIllu(plan)} size={56} className="proposal__illu" />
          <div>
            <h2 className="proposal__title" id="proposal-title">
              {combined ? bundleTitle(todo, where) : actionTitle(plan.selected, where(plan.selected))}
            </h2>
            {combined ? (
              <ol className="steps" data-testid="proposal-steps">
                {todo.map((x, i) => (
                  <li key={`${x.kind}:${x.bed_id}:${x.patient_id}:${x.slot_id}`} className="steps__item">
                    <span className="steps__text">{actionTitle(x, where(x))}</span>
                    {plan.team_practice?.step_saved_wait?.[i] != null ? (
                      <span className="steps__gain num" {...planSource(plan, `/team_practice/step_saved_wait/${i}`)}>
                        {savedText(plan.team_practice.step_saved_wait[i]!)}
                      </span>
                    ) : plan.bundle_marginal_minutes?.[i] != null ? (
                      <span className="steps__gain num" {...planSource(plan,`/bundle_marginal_minutes/${i}`)}>
                        −{waitText(plan.bundle_marginal_minutes[i]!)}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ol>
            ) : null}
            {facts.length ? (
              <ul className="facts">
                {facts.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            ) : null}
            {combined ? (
              <p className="steps__note">
                Gestes évalués ensemble : chaque gain est ce que le geste ajoute aux précédents.
              </p>
            ) : null}
          </div>
        </div>
        {practice ? (
          <PracticeEffect plan={plan} p={practice} title={(x) => actionTitle(x, where(x))} />
        ) : gain ? (
          <Effect plan={plan} gain={gain} unserved={cmp.selected?.scenarios_with_unserved_demand ?? 0} />
        ) : null}
      </div>
      <Decision
        key={plan.plan_id}
        record={current!}
        a={a}
        unit={unit}
        now={now}
        expired={expired}
        expiresAt={expiresAt}
        minutesLeft={minutesLeft}
        busy={busy}
        onEvaluate={onEvaluate}
        evaluateLabel={evaluateLabel}
        onToast={onToast}
      />
      <Source a={a} plan={plan} busy={busy} onEvaluate={onEvaluate} label={evaluateLabel} />
    </section>
  );
}

const lowerFirst = (t: string) => t.charAt(0).toLowerCase() + t.slice(1);

const PREPARATION = {
  after_request: "préparation lancée par la demande",
  already_started: "préparation déjà en cours",
} as const;

/**
 * What is gained, against what (review of PR #50). The figure is never shown without its
 * hypothesis: « if nobody makes the gesture before 08:30 ». The same gesture made by the team
 * after a delay gives a range, much smaller. Window bounded to the shift (12 h), not 24 h, so
 * the gain does not grow by one hour per hour of window. A near tie is shown, not hidden.
 */
function PracticeEffect({ plan, p, title }: { plan: Plan; p: Practice; title: (a: Action) => string }) {
  const at = (pointer: string) => planSource(plan, `/team_practice${pointer}`);
  const until = <time {...at("/until")}>{p.until}</time>;
  return (
    <div className="effect" aria-label="Ce que vous gagnez" data-testid="effect">
      <p className="effect__kicker">
        Ce que vous gagnez d'ici {until} · selon ce que l'équipe aurait fait sans HospitalOS
      </p>
      <div className="effect__figure">
        <span className="effect__delta num" {...at("/never_saved_wait")}>
          {savedText(p.never)}
        </span>
        <span className="effect__unit">
          d'attente en moins pour les patients à placer <b>si personne ne le fait d'ici {until}</b>
        </span>
      </div>
      {p.supported && p.rows.length ? (
        <table className="practice" data-testid="practice">
          <caption className="visually-hidden">Attente évitée selon ce que l'équipe aurait fait sans HospitalOS</caption>
          <thead>
            <tr>
              <th scope="col">Sans HospitalOS, l'équipe le fait…</th>
              <th scope="col" className="r">
                Attente évitée
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">pas d'ici {p.until}</th>
              <td className="r num" {...at("/never_saved_wait")}>
                {savedText(p.never)}
              </td>
            </tr>
            {p.rows.map((r) => (
              <tr key={r.delay}>
                <th scope="row" {...at(`/cases/${r.highIndex}/delay_minutes`)}>
                  {delayText(r.delay)}
                </th>
                <td className="r num">
                  {Math.abs(r.high - r.low) < 0.5 ? (
                    <span {...at(`/cases/${r.highIndex}/saved_wait`)}>{savedText(r.high)}</span>
                  ) : (
                    <>
                      <span {...at(`/cases/${r.lowIndex}/saved_wait`)}>{savedText(r.low)}</span> à{" "}
                      <span {...at(`/cases/${r.highIndex}/saved_wait`)}>{savedText(r.high)}</span>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <>
          <div
            className="pair"
            role="img"
            aria-label={`Attente cumulée d'ici ${p.until} : ${waitText(plan.team_practice!.never_wait)} si personne ne le fait, ${waitText(plan.team_practice!.selected_wait)} avec la proposition.`}
          >
            <PairRow
              label="Si personne ne le fait"
              provenance={at("/never_wait")}
              value={plan.team_practice!.never_wait}
              max={Math.max(plan.team_practice!.never_wait, plan.team_practice!.selected_wait, 1)}
            />
            <PairRow
              label="Avec la proposition"
              provenance={at("/selected_wait")}
              value={plan.team_practice!.selected_wait}
              max={Math.max(plan.team_practice!.never_wait, plan.team_practice!.selected_wait, 1)}
              on
            />
          </div>
          <p className="effect__note" data-testid="practice-unsupported">
          Pas de fourchette pour ce geste : un renfort ou la préparation d'une entrée ne se rejoue pas encore avec un
          délai d'équipe. Le gain est donc celui d'une équipe qui ne le ferait pas.
          </p>
        </>
      )}
      {p.contenders.map((c) => (
        <p className="effect__tie" role="note" data-testid="near-tie" key={c.index}>
          <b>Quasi-égalité.</b> Si l'équipe le fait déjà {delaysText(c.delays)} (
          {c.preparations.map((x) => PREPARATION[x]).join(" ou ")}), <b>{lowerFirst(title(c.action))}</b> fait aussi
          bien ou mieux (écart jusqu'à{" "}
          <span className="num" {...at(`/cases/${c.index}/leader_margin`)}>
            {c.margin < 0.5 ? "< 1 min" : waitText(c.margin)}
          </span>
          ). À choisir selon votre pratique.
        </p>
      ))}
      <p className="effect__note">
        {p.supported && p.rows.length
          ? "La fourchette va d'une préparation déjà en cours à une préparation lancée par la demande. Ces délais sont des hypothèses, pas des observations : le délai habituel de l'unité est à mesurer. "
          : ""}
        Attente cumulée : somme des
        attentes des patients à placer sur les <span {...at("/window_minutes")}>{duration(p.windowMinutes)}</span> à
        venir, moyenne de <span {...planSource(plan, "/scenarios")}>{plan.scenarios}</span> scénarios simulés.
      </p>
    </div>
  );
}

/**
 * What is gained, at a glance: hours of waiting removed for the patients to place, then the
 * two totals with their unit. The percentage is secondary.
 */
function Effect({ plan, gain, unserved }: { plan: Plan; gain: Gain; unserved: number }) {
  const atWindow = `/windows/${plan.windows?.findIndex(w=>w.minutes===plan.horizon_minutes)}`;
  const max = Math.max(gain.before, gain.after, 1);
  const helps = gain.saved > 0.5;
  return (
    <div className="effect" aria-label="Ce que vous gagnez" data-testid="effect">
      <p className="effect__kicker">Ce que vous gagnez d'ici <span {...planSource(plan,atWindow+"/until")}>{gain.until}</span></p>
      <div className="effect__figure">
        <span className="effect__delta num" {...planSource(plan,atWindow+"/saved_wait")}>{helps ? `−${waitText(gain.saved)}` : "≈ 0"}</span>
        <span className="effect__unit">
          d'attente en moins pour les patients à placer
          {gain.ratio != null && helps ? <span {...planSource(plan,atWindow+"/change_ratio")}> ({pct(gain.ratio).replace("-", "−")})</span> : null}
        </span>
      </div>
      <div
        className="pair"
        role="img"
        aria-label={`Attente cumulée des patients à placer d'ici ${gain.until} : ${waitText(gain.before)} sans action, ${waitText(gain.after)} avec la proposition.`}
      >
        <PairRow label="Sans rien faire" provenance={planSource(plan,atWindow+"/baseline_wait")} value={gain.before} max={max} />
        <PairRow label="Avec la proposition" provenance={planSource(plan,atWindow+"/selected_wait")} value={gain.after} max={max} on />
      </div>
      <p className="effect__note">
        Attente cumulée : somme des temps d'attente de tous les patients à placer sur les{" "}
        <span {...planSource(plan, atWindow + "/minutes")}>{duration(gain.windowMinutes)}</span> à venir, moyenne de <span {...planSource(plan,"/scenarios")}>{plan.scenarios}</span> scénarios simulés.
      </p>
      {plan.service_status === "served_in_all_sampled_scenarios" ? (
        <p className="effect__note">Tous les patients sont placés avant <time {...planSource(plan, atWindow + "/until")}>{gain.until}</time>.</p>
      ) : plan.service_status === "unserved_in_some_sampled_scenarios" ? (
        <p className="effect__note">
          Un patient attend encore à <time {...planSource(plan, atWindow + "/until")}>{gain.until}</time> dans{" "}
          <span {...planSource(plan, atWindow + "/unserved_scenarios")}>{unserved}</span> scénarios sur{" "}
          <span {...planSource(plan, "/scenarios")}>{plan.scenarios}</span>.
        </p>
      ) : null}
    </div>
  );
}

function PairRow({ label, value, max, on, provenance }: { provenance: ReturnType<typeof planSource>; label: string; value: number; max: number; on?: boolean }) {
  return (
    <div className="pair__row">
      <span className="pair__label">{label}</span>
      <span className="pair__track">
        <span className={`pair__bar${on ? " pair__bar--on" : ""}`} style={{ width: `${(value / max) * 100}%` }} />
      </span>
      <span className="pair__value num" {...provenance}>{waitText(value)}</span>
    </div>
  );
}

/**
 * Where the proposal comes from and how fresh it is, with the way to refresh it
 * (user feedback: « d'où vient-elle, quand a-t-elle été actualisée, comment l'actualiser »).
 */
function Source(props: {
  a: Assessment;
  plan: Plan | null;
  busy: boolean;
  onEvaluate: () => void;
  label: string;
}) {
  const { a, plan } = props;
  const oldest = oldestFact(a);
  const received = a.receivedAtBySource ? Object.values(a.receivedAtBySource).sort().at(-1) : null;
  const parts = [
    plan ? `Calculé à ${clock(plan.created_at)} par le planificateur de l'unité` : "Pas de calcul",
    `état de l'unité à ${clock(a.state.at)}`,
    received ? `dernière réception des données à ${clock(received)}` : null,
    oldest ? `information la plus ancienne : il y a ${duration(oldest.minutes)}` : null,
    a.origin === "fixture" ? "démonstration, données figées" : null,
  ].filter(Boolean);
  return (
    <footer className="source" data-testid="proposal-source">
      <p className="source__text">{parts.join(" · ")}</p>
      <div className="source__actions">
        <button type="button" className="btn btn--small" onClick={props.onEvaluate} disabled={props.busy}>
          <Refresh /> {props.busy ? "Calcul…" : props.label}
        </button>
        <a className="linkbtn" href="#/proposition">
          Comment c'est calculé
        </a>
        <a className="linkbtn" href="#/donnees">
          Données
        </a>
      </div>
    </footer>
  );
}

/** No proposal: a short line, the missing data folded away (« 4 données à vérifier ▾ »). */
function Abstention(props: { codes: string[]; busy: boolean; onEvaluate: () => void; source: ReactNode }) {
  const groups = gateGroups(props.codes);
  const total = props.codes.length;
  return (
    <section className="panel proposal proposal--compact proposal--abstain" aria-labelledby="proposal-title">
      <div className="compact">
        <Illu name="cloud" size={36} className="compact__illu" />
        <div className="compact__text">
          <h2 className="compact__title" id="proposal-title">
            Pas de proposition pour l'instant
          </h2>
          <p className="mute">Mieux vaut ne rien proposer que se tromper : des données sont à vérifier.</p>
        </div>
      </div>
      <details className="compact__details" data-testid="abstention-details">
        <summary>
          {total} donnée{total > 1 ? "s" : ""} à vérifier
        </summary>
        <div className="gates">
          {groups.map((g) => (
            <div key={g.title}>
              <h3>
                {g.title} ({g.codes.length})
              </h3>
              <ul>
                {g.codes.slice(0, 3).map((c) => (
                  <li key={c} title={c}>
                    {explain(c)}
                  </li>
                ))}
                {g.codes.length > 3 ? <li className="mute">et {g.codes.length - 3} autres</li> : null}
              </ul>
            </div>
          ))}
        </div>
      </details>
      {props.source}
    </section>
  );
}

function Band({ label, right }: { label: string; right?: ReactNode }) {
  return (
    <div className="proposal__band">
      <span className="proposal__kind">{label}</span>
      {right}
    </div>
  );
}

// ---------------------------------------------------------------- decision lifecycle

const BAND: Record<Status, string> = {
  pending: "Action suivante",
  validated: "Validée, à faire",
  done: "Faite",
  refused: "Refusée",
  abandoned: "Finalement non",
  expired: "Sans réponse",
  superseded: "Remplacée",
  abstained: "Données à vérifier",
  note: "Note",
};

function bandLabel(r: DecisionRecord | null, now: string): string {
  return r ? BAND[statusOf(r, now)] : "Action suivante";
}

/** The last step a person took (validation, refusal…), notes aside. */
const lastHuman = (r: DecisionRecord) => [...r.events].reverse().find((e) => e.by && e.type !== "note");

interface DecisionProps {
  record: DecisionRecord;
  a: Assessment;
  unit: { id: string; name: string };
  now: string;
  expired: boolean;
  expiresAt: string;
  minutesLeft: number;
  busy: boolean;
  evaluateLabel: string;
  onEvaluate: () => void;
  onToast: ToastFn;
}

function Decision(p: DecisionProps) {
  const { me } = useJournal();
  const r = p.record;
  const status = statusOf(r, p.now);
  const [asking, setAsking] = useState<null | "refused" | "abandoned">(null);
  const [noting, setNoting] = useState(false);
  const noteButton =
    status !== "expired" && status !== "superseded" && !r.events.some((e) => e.type === "note") ? (
      <button className="btn btn--quiet" onClick={() => setNoting(true)}>
        Ajouter une note
      </button>
    ) : null;
  const firstReason = useRef<HTMLButtonElement>(null);
  const options = useMemo(() => (p.a.plan ? otherOptions(p.a.plan) : []), [p.a.plan]);

  // A proposal nobody answered before it went stale is closed as « sans réponse ».
  useEffect(() => {
    if (status === "expired" && statusOf(r) === "pending") journal.expire(r.id);
  }, [status, r]);

  const act = (type: "validated" | "done" | "refused" | "abandoned", message: string, reason?: string) => {
    journal.act(r.id, type, p.now, reason ? { reason } : {});
    setAsking(null);
    p.onToast(journal.storageOk ? message : "Non conservé : le navigateur refuse le stockage local.", () =>
      journal.undo(r.id),
    );
  };
  const validate = () => act("validated", "Validée. À vous de jouer : HospitalOS garde la trace.");
  const done = () => act("done", "C'est noté. L'état se mettra à jour à la prochaine réception des données.");
  const answer = (reason: string) =>
    asking === "abandoned"
      ? act("abandoned", "Noté : finalement non.", reason)
      : act("refused", "Refus noté, merci : c'est ce qui nous aide à mieux viser.", reason);

  // Keyboard (dispatched by the shell): O valider, N refuser, F c'est fait, 1–6 motif.
  useEffect(() => {
    const on = (e: Event) => {
      const key = (e as CustomEvent<string>).detail;
      if (status === "pending" && key === "yes") validate();
      else if (status === "pending" && key === "no") setAsking("refused");
      else if (status === "validated" && key === "done") done();
      else if (asking && /^[1-6]$/.test(key)) answer(REASONS[Number(key) - 1]!.id);
    };
    window.addEventListener("hos:shortcut", on);
    return () => window.removeEventListener("hos:shortcut", on);
  });

  useEffect(() => {
    if (asking) firstReason.current?.focus();
  }, [asking]);

  const human = lastHuman(r);
  const stamp = human ? `${who(human.by, me)}, ${clock(human.at)}` : "";
  const mine = !!human && human.by?.id === me.id;
  const undo = mine ? (
    <button className="btn btn--quiet" onClick={() => journal.undo(r.id)}>
      Annuler
    </button>
  ) : null;
  const reevaluate = (primary: boolean) => (
    <button className={`btn${primary ? " btn--primary" : ""}`} onClick={p.onEvaluate} disabled={p.busy}>
      <Refresh /> {p.busy ? "Évaluation…" : primary ? "Réévaluer l'unité" : p.evaluateLabel}
    </button>
  );

  let outcome: JSX.Element | null = null;
  if (status === "validated") {
    outcome = (
      <Outcome
        tone="todo"
        icon={<Clock />}
        title={`Validée par ${stamp}`}
        line={`À vous de jouer : ${todoHint(r.action)} HospitalOS n'envoie rien.`}
      >
        <button className="btn btn--primary" onClick={done}>
          <Check /> C'est fait <kbd className="kbd">F</kbd>
        </button>
        <button
          className="btn"
          onClick={() => setAsking((v) => (v ? null : "abandoned"))}
          aria-expanded={!!asking}
        >
          Finalement non
        </button>
        {noteButton}
        {undo}
      </Outcome>
    );
  } else if (status === "done") {
    outcome = (
      <Outcome
        tone="ok"
        icon={<Check />}
        title={`Faite · ${stamp}`}
        line="L'écran garde la trace de votre geste jusqu'à ce que les données le confirment. Réévaluez pour la suite."
      >
        {reevaluate(true)}
        <a className="btn btn--quiet" href="#/journal">
          Journal
        </a>
        {noteButton}
        {undo}
      </Outcome>
    );
  } else if (status === "refused" || status === "abandoned") {
    outcome = (
      <Outcome
        tone="quiet"
        icon={<Ban />}
        title={`${status === "refused" ? "Refusée" : "Finalement non"} : ${reasonLabel(human?.reason)?.toLowerCase() ?? "sans motif"}`}
        line={`${stamp}.${options.length && status === "refused" ? " D'autres options sont possibles ci-dessous." : ""}`}
      >
        {reevaluate(false)}
        {noteButton}
        {undo}
      </Outcome>
    );
  } else if (status === "expired") {
    outcome = (
      <Outcome
        tone="quiet"
        icon={<Clock />}
        title="Sans réponse"
        line={`Elle a vieilli à ${clock(p.expiresAt)}. Réévaluez avant d'agir : l'unité a pu changer.`}
      >
        {reevaluate(true)}
      </Outcome>
    );
  } else if (status === "superseded") {
    outcome = (
      <Outcome tone="quiet" icon={<Refresh />} title="Remplacée" line="Une évaluation plus récente existe.">
        {reevaluate(true)}
      </Outcome>
    );
  }

  return (
    <>
      {status === "pending" ? (
        <div className="proposal__actions">
          <button className="btn btn--primary" onClick={validate} aria-describedby="decision-note">
            <Check /> Valider <kbd className="kbd">O</kbd>
          </button>
          <button
            className="btn"
            onClick={() => setAsking((v) => (v ? null : "refused"))}
            aria-expanded={!!asking}
          >
            Refuser <kbd className="kbd">N</kbd>
          </button>
          <span className="spacer" />
          <a className="btn btn--quiet" href="#/proposition">
            Détail <kbd className="kbd">D</kbd>
          </a>
        </div>
      ) : (
        outcome
      )}
      {asking ? (
        <div className="feedback" role="group" aria-labelledby="why-label">
          <p className="feedback__label" id="why-label">
            {asking === "refused"
              ? "Pourquoi ? Un appui suffit."
              : "Qu'est-ce qui a changé ? Un appui suffit."}
          </p>
          <div className="chips">
            {REASONS.map((reason, i) => (
              <button
                key={reason.id}
                ref={i === 0 ? firstReason : undefined}
                type="button"
                className="chip"
                onClick={() => answer(reason.id)}
              >
                <kbd className="kbd" aria-hidden="true">
                  {i + 1}
                </kbd>
                {reason.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      {noting || r.events.some((e) => e.type === "note") ? (
        <NoteField record={r} now={p.now} startOpen={noting} onClose={() => setNoting(false)} />
      ) : null}
      {options.length ? (
        <Others
          options={options}
          a={p.a}
          unit={p.unit}
          main={r}
          mainStatus={status}
          now={p.now}
          onToast={p.onToast}
        />
      ) : null}
      <span className="visually-hidden" id="decision-note">
        Valider ne déclenche rien : vous agissez, HospitalOS garde la trace dans le journal.
      </span>
    </>
  );
}

function Outcome(props: {
  tone: "todo" | "ok" | "quiet";
  icon: JSX.Element;
  title: string;
  line: string;
  children: ReactNode;
}) {
  return (
    <div className={`outcome outcome--${props.tone}`}>
      <span className="outcome__icon" aria-hidden="true">
        {props.icon}
      </span>
      <div className="outcome__text">
        <p className="outcome__title">{props.title}</p>
        <p className="outcome__line">{props.line}</p>
      </div>
      <div className="outcome__actions">{props.children}</div>
    </div>
  );
}

/** A short note for the team, kept with the decision. */
export function NoteField({
  record,
  now,
  compact,
  hideNotes,
  startOpen,
  onClose,
}: {
  record: DecisionRecord;
  now: string;
  compact?: boolean;
  startOpen?: boolean;
  onClose?: () => void;
  /** The journal page already shows notes in its timeline. */
  hideNotes?: boolean;
}) {
  const { me } = useJournal();
  const [open, setOpenState] = useState(!!startOpen);
  const setOpen = (v: boolean) => {
    setOpenState(v);
    if (!v) onClose?.();
  };
  const [text, setText] = useState("");
  const notes = record.events.filter((e) => e.type === "note");
  const save = () => {
    if (!text.trim()) return setOpen(false);
    journal.act(record.id, "note", now, { note: text.trim().slice(0, 280) });
    setText("");
    setOpen(false);
  };
  if (record.sample) return null;
  return (
    <div className={`notefield${compact ? " notefield--compact" : ""}`}>
      {(hideNotes ? [] : notes).map((n, i) => (
        <p key={i} className="notefield__note">
          <span className="notefield__by">
            {who(n.by, me)}, {clock(n.at)}
          </span>{" "}
          {n.note}
        </p>
      ))}
      {open ? (
        <form
          className="notefield__form"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <label className="visually-hidden" htmlFor={`note-${record.id}`}>
            Note pour l'équipe
          </label>
          <input
            id={`note-${record.id}`}
            className="input"
            autoFocus
            maxLength={280}
            placeholder="Ex. : transport commandé, arrivée prévue 10 h"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
          />
          <button className="btn btn--primary" type="submit">
            Ajouter
          </button>
        </form>
      ) : (
        <button type="button" className="linkbtn" onClick={() => setOpen(true)}>
          + Ajouter une note
        </button>
      )}
    </div>
  );
}

/**
 * Several proposals at once: the other useful options of the same evaluation, each
 * simulated alone. Choosing one closes HospitalOS' first choice as « autre option
 * préférée »; once the first choice is handled, an option can be validated as well.
 */
function Others(props: {
  options: ReturnType<typeof otherOptions>;
  a: Assessment;
  unit: { id: string; name: string };
  main: DecisionRecord;
  mainStatus: Status;
  now: string;
  onToast: ToastFn;
}) {
  const { records } = useJournal();
  const plan = props.a.plan!;
  const canAct = props.mainStatus !== "expired" && props.mainStatus !== "superseded";
  const combined = (plan.bundle?.length ?? 0) > 1;
  const practice = practiceOf(plan);
  // Visible by default, one step below the proposal: real alternatives, not a hidden link.
  return (
    <div className="others" data-testid="others">
      <p className="others__head">
        Autres options <span className="mute">· gain de chacune seule</span>
      </p>
      <ul className="others__list" id="others-list">
        {props.options.map((o, i) => {
          const rec = recordFor(props.a, props.unit, plan, o.action, i + 1);
          const kept = records.find((r) => r.id === rec.id);
          const st = kept ? statusOf(kept, props.now) : null;
          const tie = practice?.contenders.find(
            (c) =>
              c.action.kind === o.action.kind &&
              c.action.bed_id === o.action.bed_id &&
              c.action.patient_id === o.action.patient_id &&
              c.action.slot_id === o.action.slot_id,
          );
          const altIndex =
            plan.team_practice?.alternatives?.findIndex(
              (x) =>
                x.action.kind === o.action.kind &&
                x.action.bed_id === o.action.bed_id &&
                x.action.patient_id === o.action.patient_id &&
                x.action.slot_id === o.action.slot_id,
            ) ?? -1;
          const alt = altIndex >= 0 ? { ...plan.team_practice!.alternatives![altIndex]!, index: altIndex } : null;
          const firstOnly =
            combined &&
            o.action.kind === plan.selected.kind &&
            o.action.bed_id === plan.selected.bed_id &&
            o.action.patient_id === plan.selected.patient_id;
          return (
            <li key={rec.id} className="others__item">
              <div>
                <p className="others__title">
                  {firstOnly ? "Seulement : " : ""}
                  {rec.title}
                </p>
                {alt ? (
                  <p className="others__effect num">
                    <span {...planSource(plan, `/team_practice/alternatives/${alt.index}/saved_wait`)}>
                      {alt.saved_wait > 0.5 ? `−${waitText(alt.saved_wait)} d'attente` : "gain négligeable"}
                    </span>{" "}
                    d'ici {practice!.until}, si personne ne fait rien d'autre
                  </p>
                ) : (
                  <p className="others__effect num">
                    {o.saved > 0.5 ? `−${waitText(o.saved)} d'attente` : "gain négligeable"} ({deltaText(o.deltaRatio)}) d'ici{" "}
                    {rec.horizonEnd}, si personne ne fait rien d'autre
                  </p>
                )}
                {tie ? (
                  <p className="others__tie" data-testid="others-tie">
                    Aussi bien ou mieux si l'équipe fait déjà le geste principal {delaysText(tie.delays)}
                  </p>
                ) : null}
              </div>
              {st ? (
                <span className={`pill pill--${STATUS[st].tone}`}>{STATUS[st].label}</span>
              ) : canAct ? (
                <button
                  type="button"
                  className="btn btn--small"
                  onClick={() => {
                    if (props.mainStatus === "pending") {
                      journal.choose(props.main, rec, props.now);
                      props.onToast("Option choisie. À vous de jouer.", () => {
                        journal.discard(rec.id);
                        journal.undo(props.main.id);
                      });
                    } else {
                      journal.register(rec);
                      journal.act(rec.id, "validated", props.now);
                      props.onToast("Option validée. À vous de jouer.", () => journal.discard(rec.id));
                    }
                  }}
                >
                  {props.mainStatus === "pending"
                    ? "Choisir plutôt"
                    : props.mainStatus === "refused" || props.mainStatus === "abandoned"
                      ? "Choisir celle-ci"
                      : "Valider aussi"}
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * Commitments in flight on this unit: validated earlier (or chosen as another option)
 * and not marked done yet. They stay visible while new proposals arrive.
 */
export function InProgress({
  unitId,
  situationId,
  excludePlan,
  now,
  onToast,
}: {
  unitId: string;
  /** Demonstration situation on screen: decisions from another situation stay there. */
  situationId: string;
  /** The plan shown in the proposal card: its first choice is handled there. */
  excludePlan: string | null;
  now: string;
  onToast: ToastFn;
}) {
  const { records, me } = useJournal();
  const todo = records.filter(
    (r) =>
      !r.sample &&
      r.unitId === unitId &&
      (!r.situationId || r.situationId === situationId) &&
      !(r.planId === excludePlan && r.rank === 0) &&
      statusOf(r, now) === "validated",
  );
  if (!todo.length) return null;
  return (
    <section className="inprogress" aria-labelledby="inprogress-title">
      <h2 className="inprogress__title" id="inprogress-title">
        <Clock /> En cours de votre côté ({todo.length})
      </h2>
      <ul>
        {todo.map((r) => {
          const human = lastHuman(r);
          return (
            <li key={r.id} className="inprogress__item">
              <div>
                <p className="inprogress__what">{r.title}</p>
                <p className="inprogress__meta">
                  Validée par {human ? `${who(human.by, me)}, ${clock(human.at)}` : "?"} ·{" "}
                  {todoHint(r.action)}
                </p>
              </div>
              <button
                type="button"
                className="btn btn--small"
                onClick={() => {
                  journal.act(r.id, "done", now);
                  onToast("C'est noté.", () => journal.undo(r.id));
                }}
              >
                <Check /> C'est fait
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
