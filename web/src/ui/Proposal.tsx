import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  type DecisionRecord,
  REASONS,
  STATUS,
  type Status,
  abstentionRecord,
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
import {
  type Assessment,
  clock,
  clockPlus,
  comparison,
  duration,
  gateGroups,
  minutesBetween,
  num,
  pct,
  proposalContext,
} from "../domain/view";
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
  const live = a.origin === "api-live" || a.scenarioId.startsWith("live");
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

  if (awaitingEvaluation || (!plan && a.gateReasons.length === 0)) {
    return (
      <section className="panel proposal proposal--quiet" aria-labelledby="proposal-title">
        <Band label="À évaluer" />
        <div className="proposal__main">
          <div className="proposal__lead">
            <Illu name="plane" size={56} className="proposal__illu" />
            <div>
              <h2 className="proposal__title" id="proposal-title">
                Prêt à évaluer l'unité
              </h2>
              <p className="mute">
                HospitalOS simule les prochaines heures et vous propose l'action la plus utile.
              </p>
            </div>
          </div>
        </div>
        <div className="proposal__actions">
          <button className="btn btn--primary" onClick={onEvaluate} disabled={busy}>
            <Refresh /> {busy ? "Évaluation…" : evaluateLabel}
          </button>
        </div>
      </section>
    );
  }

  if (!plan || plan.decision === "abstain") {
    const codes = a.gateReasons.length ? a.gateReasons : (plan?.reasons ?? []);
    const groups = gateGroups(codes);
    return (
      <section className="panel proposal proposal--abstain" aria-labelledby="proposal-title">
        <Band label="Données à vérifier" />
        <div className="proposal__main">
          <div className="proposal__lead">
            <Illu name="cloud" size={56} className="proposal__illu" />
            <div>
              <h2 className="proposal__title" id="proposal-title">
                Pas de proposition pour l'instant
              </h2>
              <p className="mute">
                Mieux vaut ne rien proposer que se tromper. Mettez ces informations à jour, puis réévaluez.
              </p>
            </div>
          </div>
          <div className="gates">
            {groups.map((g) => (
              <div key={g.title}>
                <h3>
                  {g.title} ({g.codes.length})
                </h3>
                <ul>
                  {g.codes.slice(0, 2).map((c) => (
                    <li key={c} title={c}>
                      {explain(c)}
                    </li>
                  ))}
                  {g.codes.length > 2 ? <li className="mute">et {g.codes.length - 2} autres</li> : null}
                </ul>
              </div>
            ))}
          </div>
        </div>
        <div className="proposal__actions">
          <button className="btn" onClick={onEvaluate} disabled={busy}>
            <Refresh /> {busy ? "Évaluation…" : "Réévaluer"}
          </button>
          <a className="btn btn--quiet" href="#/donnees">
            Voir la qualité des données
          </a>
        </div>
      </section>
    );
  }

  const cmp = comparison(plan);
  const expiresAt = a.expiresAt ?? plan.expires_at;
  const minutesLeft = minutesBetween(now, expiresAt);
  const expired = minutesLeft <= 0;
  const end = clockPlus(plan.created_at, plan.horizon_minutes);
  const context = proposalContext(a.state, plan);
  const quiet = plan.decision === "no_change";
  // Two lines at most: the concrete context first, then warnings. Generic planner reasons
  // (« réduit l'attente simulée ») repeat what the effect already shows.
  const facts = [
    ...context,
    ...plan.warnings.map(explain),
    ...plan.reasons.filter((r) => !GENERIC.has(r)).map(explain),
  ].slice(0, 2);
  const max = Math.max(
    cmp.baseline?.worst_decile_waiting_patient_minutes ?? 0,
    cmp.selected?.worst_decile_waiting_patient_minutes ?? 0,
    1,
  );

  return (
    <section className={`panel proposal${quiet ? " proposal--quiet" : ""}`} aria-labelledby="proposal-title">
      <Band
        label={quiet ? "Rien à changer" : bandLabel(current, now)}
        right={
          !quiet && current && statusOf(current, now) === "pending" ? (
            <span className="expiry">Fraîche encore {duration(minutesLeft)}</span>
          ) : null
        }
      />
      <div className="proposal__main">
        <div className="proposal__lead">
          <Illu name={proposalIllu(plan)} size={56} className="proposal__illu" />
          <div>
            <h2 className="proposal__title" id="proposal-title">
              {actionTitle(plan.selected)}
            </h2>
            {facts.length ? (
              <ul className="facts">
                {facts.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>
        {cmp.baseline && cmp.selected && !quiet ? (
          <div className="effect" aria-label="Effet simulé">
            <div className="effect__figure">
              <span className="effect__delta num">
                {cmp.deltaRatio != null ? pct(cmp.deltaRatio).replace("-", "−") : "—"}
              </span>
              <span className="effect__unit">d'attente simulée d'ici {end}</span>
            </div>
            <div
              className="pair"
              role="img"
              title={`Attente cumulée en patient-minutes, moyenne de ${plan.scenarios} scénarios simulés sous hypothèses déclarées.`}
              aria-label={pairLabel(
                cmp.baseline.mean_waiting_patient_minutes,
                cmp.selected.mean_waiting_patient_minutes,
              )}
            >
              <PairRow label="Sans action" mean={cmp.baseline.mean_waiting_patient_minutes} max={max} />
              <PairRow
                label="Avec la proposition"
                mean={cmp.selected.mean_waiting_patient_minutes}
                max={max}
                on
              />
            </div>
            {plan.service_status === "served_in_all_sampled_scenarios" ? (
              <p className="effect__note">Tous les patients placés avant {end}.</p>
            ) : plan.service_status === "unserved_in_some_sampled_scenarios" ? (
              <p className="effect__note">
                Un patient attend encore à {end} dans {cmp.selected.scenarios_with_unserved_demand} scénarios
                sur {plan.scenarios}.
              </p>
            ) : null}
          </div>
        ) : (
          <div className="effect">
            <p className="effect__lead">Tout roule.</p>
            <p className="effect__note">
              Aucune des {plan.candidates.length - 1} actions simulées ne ferait mieux d'ici{" "}
              {duration(plan.horizon_minutes)}.
            </p>
          </div>
        )}
      </div>

      {quiet ? (
        <div className="proposal__actions">
          <button className="btn" onClick={onEvaluate} disabled={busy}>
            <Refresh /> {evaluateLabel}
          </button>
          <span className="spacer" />
          <a className="btn btn--quiet" href="#/proposition">
            Options comparées
          </a>
        </div>
      ) : (
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
      )}
    </section>
  );
}

function pairLabel(base: number, sel: number) {
  return `Attente simulée moyenne : ${num(base)} patient-minutes sans action, ${num(sel)} avec la proposition.`;
}

function PairRow({
  label,
  mean,
  tail,
  max,
  on,
}: {
  label: string;
  mean: number;
  tail?: number;
  max: number;
  on?: boolean;
}) {
  return (
    <div className="pair__row">
      <span className="pair__label">{label}</span>
      <span className="pair__track">
        <span
          className={`pair__bar${on ? " pair__bar--on" : ""}`}
          style={{ width: `${(mean / max) * 100}%` }}
        />
        {tail != null ? (
          <span className="pair__tail" style={{ left: `calc(${(tail / max) * 100}% - 1px)` }} />
        ) : null}
      </span>
      <span className="pair__value num">{num(mean)}</span>
    </div>
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
  const done = () => act("done", "C'est fait. Merci, l'unité respire un peu mieux.");
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
      <Refresh /> {p.busy ? "Évaluation…" : primary ? "Voir la suite" : p.evaluateLabel}
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
        title="Faite. Merci !"
        line={`${stamp}. L'état de l'unité a changé : réévaluez pour la suite.`}
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
  const [open, setOpen] = useState(false);
  const show = open || props.mainStatus === "refused";
  const canAct = props.mainStatus !== "expired" && props.mainStatus !== "superseded";
  return (
    <div className="others">
      <button
        type="button"
        className="others__toggle"
        aria-expanded={show}
        aria-controls="others-list"
        onClick={() => setOpen(!show)}
      >
        <span className="others__chev" aria-hidden="true">
          ›
        </span>
        {props.options.length > 1 ? `${props.options.length} autres options utiles` : "1 autre option utile"}
      </button>
      {show ? (
        <div id="others-list">
          <ul className="others__list">
            {props.options.map((o, i) => {
              const rec = recordFor(props.a, props.unit, plan, o.action, i + 1);
              const kept = records.find((r) => r.id === rec.id);
              const st = kept ? statusOf(kept, props.now) : null;
              return (
                <li key={rec.id} className="others__item">
                  <div>
                    <p className="others__title">{rec.title}</p>
                    <p className="others__effect num">
                      {deltaText(o.deltaRatio)} d'attente simulée d'ici {rec.horizonEnd}
                    </p>
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
          <p className="others__note">Effets simulés séparément : ils ne s'additionnent pas.</p>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Commitments in flight on this unit: validated earlier (or chosen as another option)
 * and not marked done yet. They stay visible while new proposals arrive.
 */
export function InProgress({
  unitId,
  excludePlan,
  now,
  onToast,
}: {
  unitId: string;
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
                  onToast("C'est fait. Merci !", () => journal.undo(r.id));
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
