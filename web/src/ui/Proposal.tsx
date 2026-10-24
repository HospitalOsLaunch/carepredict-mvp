import { useEffect, useRef, useState } from "react";
import { REASONS, type Verdict, opinionFor, saveOpinion } from "../data/feedback";
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
import { Ban, Check, Info, Refresh } from "./icons";

interface Props {
  a: Assessment;
  now: string;
  busy: boolean;
  awaitingEvaluation: boolean;
  onEvaluate: () => void;
  onToast: (message: string) => void;
}

export function Proposal({ a, now, busy, awaitingEvaluation, onEvaluate, onToast }: Props) {
  const plan = a.plan;
  const live = a.origin === "api-live" || a.scenarioId.startsWith("live");
  const evaluateLabel = live ? "Évaluer maintenant" : "Recalculer";

  if (awaitingEvaluation || (!plan && a.gateReasons.length === 0)) {
    return (
      <section className="panel proposal proposal--quiet" aria-labelledby="proposal-title">
        <Band label="Pas encore évaluée" a={a} />
        <div className="proposal__main">
          <div>
            <h2 className="proposal__title" id="proposal-title">
              Aucune évaluation pour l'état actuel
            </h2>
            <p className="mute">
              L'évaluation simule les prochaines heures avec et sans chaque action possible. En observation,
              elle est enregistrée comme épisode, sans rien envoyer.
            </p>
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
        <Band label="Abstention" a={a} />
        <div className="proposal__main">
          <div>
            <h2 className="proposal__title" id="proposal-title">
              Pas de proposition : l'état de l'unité n'est pas fiable
            </h2>
            <p className="mute">
              HospitalOS ne calcule rien sur des informations manquantes, trop anciennes ou contradictoires.
              Mettez-les à jour à la source, puis réévaluez.
            </p>
          </div>
          <div className="gates">
            {groups.map((g) => (
              <div key={g.title}>
                <h3>
                  {g.title} ({g.codes.length})
                </h3>
                <ul>
                  {g.codes.slice(0, 4).map((c) => (
                    <li key={c} title={c}>
                      {explain(c)}
                    </li>
                  ))}
                  {g.codes.length > 4 ? <li className="mute">et {g.codes.length - 4} autres</li> : null}
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
  const max = Math.max(
    cmp.baseline?.worst_decile_waiting_patient_minutes ?? 0,
    cmp.selected?.worst_decile_waiting_patient_minutes ?? 0,
    1,
  );

  return (
    <section className={`panel proposal${quiet ? " proposal--quiet" : ""}`} aria-labelledby="proposal-title">
      <Band label={quiet ? "Rien à changer" : "Action suivante"} a={a} />
      <div className="proposal__main">
        <div>
          <h2 className="proposal__title" id="proposal-title">
            {actionTitle(plan.selected)}
          </h2>
          <ul className="facts">
            {plan.reasons.map((r) => (
              <li key={r} title={r}>
                {explain(r)}
              </li>
            ))}
            {context.map((line) => (
              <li key={line}>{line}</li>
            ))}
            {plan.warnings.map((w) => (
              <li key={w} title={w}>
                {explain(w)}
              </li>
            ))}
          </ul>
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
              aria-label={pairLabel(
                cmp.baseline.mean_waiting_patient_minutes,
                cmp.selected.mean_waiting_patient_minutes,
              )}
            >
              <PairRow
                label="Sans action"
                mean={cmp.baseline.mean_waiting_patient_minutes}
                tail={cmp.baseline.worst_decile_waiting_patient_minutes}
                max={max}
              />
              <PairRow
                label="Avec la proposition"
                mean={cmp.selected.mean_waiting_patient_minutes}
                tail={cmp.selected.worst_decile_waiting_patient_minutes}
                max={max}
                on
              />
            </div>
            <p className="effect__note">
              Attente cumulée en patient-minutes, moyenne de {plan.scenarios} scénarios. Le trait marque le
              pire décile.{" "}
              {plan.service_status === "served_in_all_sampled_scenarios"
                ? `Tous les patients sont placés avant ${end} dans chaque scénario.`
                : plan.service_status === "unserved_in_some_sampled_scenarios"
                  ? `Dans ${cmp.selected.scenarios_with_unserved_demand} scénarios sur ${plan.scenarios}, au moins un patient attend encore à ${end}.`
                  : null}
            </p>
          </div>
        ) : (
          <div className="effect">
            <p className="effect__note">
              {plan.candidates.length - 1} actions possibles ont été simulées sur{" "}
              {duration(plan.horizon_minutes)}. Aucune ne réduit l'attente sans risquer de surcharger une
              ressource.
            </p>
          </div>
        )}
      </div>

      {quiet ? (
        <div className="proposal__actions">
          <a className="btn" href="#/proposition">
            Voir les options comparées
          </a>
          <span className="spacer" />
          <button className="btn btn--quiet" onClick={onEvaluate} disabled={busy}>
            <Refresh /> {evaluateLabel}
          </button>
        </div>
      ) : (
        <Opinion
          key={plan.plan_id}
          planId={plan.plan_id}
          stateAt={a.state.at}
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
  tail: number;
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
        <span className="pair__tail" style={{ left: `calc(${(tail / max) * 100}% - 1px)` }} />
      </span>
      <span className="pair__value num">{num(mean)}</span>
    </div>
  );
}

function Band({ label, a }: { label: string; a: Assessment }) {
  return (
    <div className="proposal__band">
      <span>
        <span className="proposal__kind">{label}</span>
        {a.plan ? <> pour l'état de {clock(a.state.at)}</> : null}
      </span>
      <span title="Résultat d'une simulation sous hypothèses déclarées, pas une prédiction validée">
        Simulation sous hypothèses synthétiques
      </span>
    </div>
  );
}

interface OpinionProps {
  planId: string;
  stateAt: string;
  now: string;
  expired: boolean;
  expiresAt: string;
  minutesLeft: number;
  busy: boolean;
  evaluateLabel: string;
  onEvaluate: () => void;
  onToast: (message: string) => void;
}

function Opinion(p: OpinionProps) {
  const [stored, setStored] = useState(() => opinionFor(p.planId));
  const [declining, setDeclining] = useState(false);
  const firstReason = useRef<HTMLButtonElement>(null);

  const record = (verdict: Verdict, why: string | null = null) => {
    const opinion = {
      plan_id: p.planId,
      verdict,
      reason: verdict === "would_not" ? why : null,
      comment: "",
      recorded_at: p.now,
      state_at: p.stateAt,
    };
    const kept = saveOpinion(opinion);
    setStored(opinion);
    setDeclining(false);
    p.onToast(
      kept
        ? "Avis noté sur cet appareil. Rien n'a été envoyé."
        : "Avis non conservé : stockage du navigateur indisponible.",
    );
  };

  // Keyboard shortcuts are dispatched by the shell (see useShortcuts): O = oui, N = non.
  useEffect(() => {
    const on = (e: Event) => {
      const key = (e as CustomEvent<string>).detail;
      if (stored || p.expired) return;
      if (key === "yes") record("would_do");
      if (key === "no") setDeclining(true);
      if (declining && /^[1-6]$/.test(key)) record("would_not", REASONS[Number(key) - 1]!.id);
    };
    window.addEventListener("hos:shortcut", on);
    return () => window.removeEventListener("hos:shortcut", on);
  });

  useEffect(() => {
    if (declining) firstReason.current?.focus();
  }, [declining]);

  const expiry = p.expired ? (
    <span className="expiry expiry--late">Expirée à {clock(p.expiresAt)}. Réévaluez avant d'agir.</span>
  ) : (
    <span className="expiry">
      Valable jusqu'à {clock(p.expiresAt)}, encore {duration(p.minutesLeft)}
    </span>
  );

  if (stored) {
    return (
      <div className="proposal__actions">
        <span className="status-line">
          {stored.verdict === "would_do" ? <Check /> : <Ban />}
          {stored.verdict === "would_do" ? "Vous l'auriez fait" : "Vous ne l'auriez pas fait"}
          {stored.reason ? (
            <span className="mute">({REASONS.find((r) => r.id === stored.reason)?.label})</span>
          ) : null}
        </span>
        <span className="spacer" />
        <button className="btn btn--quiet" onClick={() => setStored(null)}>
          Modifier mon avis
        </button>
        <a className="btn" href="#/proposition">
          Voir le détail
        </a>
      </div>
    );
  }

  return (
    <>
      <div className="proposal__actions">
        <button
          className="btn btn--primary"
          onClick={() => record("would_do")}
          disabled={p.expired}
          aria-describedby="shadow-note"
        >
          <Check /> Je l'aurais fait <kbd className="kbd">O</kbd>
        </button>
        <button
          className="btn"
          onClick={() => setDeclining((v) => !v)}
          aria-expanded={declining}
          disabled={p.expired}
        >
          Je ne l'aurais pas fait <kbd className="kbd">N</kbd>
        </button>
        <a className="btn btn--quiet" href="#/proposition">
          Détail <kbd className="kbd">D</kbd>
        </a>
        <span className="spacer" />
        {p.expired ? (
          <button className="btn" onClick={p.onEvaluate} disabled={p.busy}>
            <Refresh /> {p.evaluateLabel}
          </button>
        ) : null}
        {expiry}
      </div>
      {declining ? (
        <div className="feedback" role="group" aria-labelledby="why-label">
          <p className="feedback__label" id="why-label">
            Pourquoi ? Un appui suffit.
          </p>
          <div className="chips">
            {REASONS.map((r, i) => (
              <button
                key={r.id}
                ref={i === 0 ? firstReason : undefined}
                type="button"
                className="chip"
                onClick={() => record("would_not", r.id)}
              >
                <kbd className="kbd" aria-hidden="true">
                  {i + 1}
                </kbd>
                {r.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      <p className="note proposal__note" id="shadow-note">
        <Info size={14} /> Mode observation : votre avis mesure la pertinence de la proposition. Aucune
        demande n'est envoyée.
      </p>
    </>
  );
}
