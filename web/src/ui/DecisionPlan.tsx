import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import {
  type DsAction,
  type DsHour,
  type DsRecommendation,
  type DsReview,
  type DsSnapshot,
  pointer,
} from "../api/decision";
import {
  type DecisionRecord,
  PLAN_REASONS,
  getMe,
  journal,
  reasonLabel,
  statusOf,
  useJournal,
  who,
} from "../data/journal";
import { type DecisionStore, type DsDoc, type DsSource, useDecision } from "../data/useDecision";
import {
  AUTHORIZATION,
  BASIS,
  CONFIRMATION,
  actionShort,
  actionText,
  diagnostic,
  groupedConditions,
  humanReasons,
  provenance,
  rejection,
  uncertainty,
} from "../domain/planLabels";
import "../styles/decision.css";
import { Back, Check } from "./icons";
import { NoteField } from "./Proposal";
import { Illu } from "./illustrations";

// 24-hour plan, auto first. Same grammar as the unit's « Action suivante »: one strong card
// (what to do, the effect, two answers), the rest one click away. No figure is written here:
// each number shown is read from an engine document and carries data-src="<doc>#<JSON
// pointer>" and data-raw (T32).

const STATUS: Record<string, [string, string]> = {
  RECOMMENDATION_READY: ["Plan proposé", "pill--brand"],
  NO_ACTION_PREFERRED: ["Rien à changer", "pill--ok"],
  INSUFFICIENT_DATA: ["Données à vérifier", "pill--bad"],
  INFEASIBLE: ["Impossible en l'état", "pill--bad"],
  HYPOTHETICAL_ONLY: ["Hypothèse simulée, non applicable", "pill--warn"],
  INVALIDATED: ["Proposition invalidée", "pill--bad"],
};

const TZ = "Europe/Paris";

function local(iso: string, withDay = false): string {
  const opts: Intl.DateTimeFormatOptions = { timeZone: TZ, hour: "2-digit", minute: "2-digit" };
  if (withDay) Object.assign(opts, { weekday: "short", day: "2-digit", month: "short" });
  return new Intl.DateTimeFormat("fr-FR", opts).format(new Date(iso));
}

function fmt(v: unknown): string {
  if (typeof v === "number") {
    return Number.isInteger(v) ? String(v) : v.toLocaleString("fr-FR", { maximumFractionDigits: 1 });
  }
  return String(v);
}

/** A figure bound to its source document. */
function Fig({ doc, ptr, format = fmt }: { doc: DsDoc; ptr: string; format?: (v: never) => string }) {
  const value = pointer(doc.reco, ptr);
  return (
    <span className="num" data-src={`${doc.id}#${ptr}`} data-raw={JSON.stringify(value ?? null)}>
      {value === null || value === undefined ? "—" : (format as (v: unknown) => string)(value)}
    </span>
  );
}

const value = (doc: DsDoc, ptr: string): number => {
  const v = pointer(doc.reco, ptr);
  return typeof v === "number" ? v : 0;
};

function evalIndex(reco: DsRecommendation, planId: string | null): number {
  if (!planId || !reco.bundle) return -1;
  return reco.bundle.evaluations.findIndex((e) => e.plan.plan_id === planId);
}

function Status({ reco }: { reco: DsRecommendation }) {
  const [label, cls] = STATUS[reco.status] ?? [reco.status, ""];
  return (
    <span className={`pill ${cls}`} data-testid="ds-status" data-status={reco.status}>
      {label}
    </span>
  );
}

/** One action: what, when, from where; then why it may be done (basis) and what it waits for. */
function ActionLine({ a, snapshot, example }: { a: DsAction; snapshot: DsSnapshot | null; example?: boolean }) {
  const basis = BASIS[a.basis];
  const option =
    a.type === "reinforcement" ? snapshot?.reinforcements.find((r) => r.option_id === a.target) : undefined;
  const loan = option?.source === "shared_unit" ? option : undefined;
  return (
    <li className="ds-action" data-testid="ds-action" data-basis={a.basis}>
      <span className="ds-action__text">{actionText(a, snapshot, (iso) => local(iso))}</span>
      <span className="ds-action__tags">
        {a.origin === "manual_lock" ? (
          <span className="ds-tag ds-tag--lock">{example ? "imposé dans l'exemple" : "imposé par vous"}</span>
        ) : null}
        {basis ? (
          <span className={`ds-tag ds-tag--${basis.tone}`} title="Sur quoi repose cette action">
            {basis.label}
          </span>
        ) : (
          <span className="ds-tag">{a.basis}</span>
        )}
        {/* Every reinforcement says whether it is confirmed, not only the doubtful ones. */}
        {a.conditional || option?.confirmation === "requested" ? (
          <span className="ds-tag ds-tag--cond" data-testid="ds-confirmation">
            demandé, non confirmé
          </span>
        ) : option?.confirmation === "confirmed" ? (
          <span className="ds-tag ds-tag--fact" data-testid="ds-confirmation">
            confirmé
          </span>
        ) : option ? (
          <span className="ds-tag ds-tag--cond" data-testid="ds-confirmation">
            {CONFIRMATION[option.confirmation] ?? option.confirmation}
          </span>
        ) : null}
        {loan ? (
          <span className="ds-tag ds-tag--loan" data-testid="ds-lending-unit">
            {provenance(loan)}
          </span>
        ) : null}
      </span>
    </li>
  );
}

function Details({ title, children, open }: { title: string; children: ReactNode; open?: boolean }) {
  return (
    <details className="ds-details" open={open}>
      <summary>{title}</summary>
      <div className="ds-details__body">{children}</div>
    </details>
  );
}

function Bullets({ items, testId }: { items: string[]; testId?: string }) {
  if (!items.length) return null;
  return (
    <ul className="facts" data-testid={testId}>
      {items.map((t) => (
        <li key={t}>{t}</li>
      ))}
    </ul>
  );
}

/** Diagnostics in words, the engine code kept in small type for whoever investigates. */
function Diagnostics({ items, testId, error }: { items: string[]; testId: string; error?: boolean }) {
  if (!items.length) return null;
  return (
    <ul className={`facts${error ? " ds-err" : ""}`} data-testid={testId}>
      {items.map((d) => (
        <li key={d}>
          {diagnostic(d)} <code className="ds-code">{d}</code>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- effect

/** The plan's effect, read like the unit's proposal: one headline pair, then the rest on demand. */
function Effect({ doc, i, base }: { doc: DsDoc; i: number; base: number }) {
  const p = `/bundle/evaluations/${i}/metrics`;
  const b = `/bundle/evaluations/${base}/metrics`;
  const end = doc.reco.bundle?.horizon_end;
  const max = Math.max(value(doc, `${b}/uncovered_care_minutes`), value(doc, `${p}/uncovered_care_minutes`), 1);
  const bar = (ptr: string, on?: boolean) => (
    <span className="pair__track">
      <span
        className={`pair__bar${on ? " pair__bar--on" : ""}`}
        style={{ width: `${(value(doc, ptr) / max) * 100}%` }}
      />
    </span>
  );
  const item = (label: string, v: ReactNode) => (
    <div className="ds-fig" key={label}>
      <small>{label}</small>
      <b>{v}</b>
    </div>
  );
  return (
    <div className="ds-effect" aria-label="Effet simulé du plan">
      <p className="ds-effect__lead">Soins non couverts{end ? ` d'ici ${local(end, true)}` : ""}, en minutes</p>
      <div className="pair">
        <div className="pair__row">
          <span className="pair__label">Pratique habituelle</span>
          {bar(`${b}/uncovered_care_minutes`)}
          <span className="pair__value">
            <Fig doc={doc} ptr={`${b}/uncovered_care_minutes`} />
          </span>
        </div>
        <div className="pair__row">
          <span className="pair__label">Avec le plan</span>
          {bar(`${p}/uncovered_care_minutes`, true)}
          <span className="pair__value">
            <Fig doc={doc} ptr={`${p}/uncovered_care_minutes`} />
          </span>
        </div>
      </div>
      <div className="ds-figs ds-figs--key">
        {item(
          "Attente de lit (patients·h)",
          <>
            <Fig doc={doc} ptr={`${b}/waiting_patient_hours`} /> → <Fig doc={doc} ptr={`${p}/waiting_patient_hours`} />
          </>,
        )}
        {item("Heures de renfort", <Fig doc={doc} ptr={`${p}/reinforcement_hours`} />)}
        {item("Lits remis à disposition", <Fig doc={doc} ptr={`${p}/beds_returned`} />)}
      </div>
      <Details title="Tous les indicateurs">
        <div className="ds-figs" data-testid="ds-figures">
          {item(
            "Minutes de soins non couvertes",
            <>
              <Fig doc={doc} ptr={`${b}/uncovered_care_minutes`} /> →{" "}
              <Fig doc={doc} ptr={`${p}/uncovered_care_minutes`} />
            </>,
          )}
          {item(
            "Attente de lit (patients·h)",
            <>
              <Fig doc={doc} ptr={`${b}/waiting_patient_hours`} /> →{" "}
              <Fig doc={doc} ptr={`${p}/waiting_patient_hours`} />
            </>,
          )}
          {item("IDE requis au pic", <Fig doc={doc} ptr={`${p}/max_total_staff_required/IDE`} />)}
          {item("IDE en plus du planning au pic", <Fig doc={doc} ptr={`${p}/max_additional_staff_required/IDE`} />)}
          {item("Heures de renfort", <Fig doc={doc} ptr={`${p}/reinforcement_hours`} />)}
          {item(
            "Tension maximale (score expérimental)",
            <>
              <Fig doc={doc} ptr={`${b}/peak_pressure`} /> → <Fig doc={doc} ptr={`${p}/peak_pressure`} />
            </>,
          )}
          {item(
            "Heures au-dessus du seuil",
            <>
              <Fig doc={doc} ptr={`${b}/hours_above_threshold`} /> →{" "}
              <Fig doc={doc} ptr={`${p}/hours_above_threshold`} />
            </>,
          )}
          {item("Lits remis à disposition", <Fig doc={doc} ptr={`${p}/beds_returned`} />)}
        </div>
      </Details>
    </div>
  );
}

function Chart({ reco, i, base, hours = 24 }: { reco: DsRecommendation; i: number; base: number; hours?: number }) {
  const ev = reco.bundle!.evaluations;
  const clip = (pts: DsHour[]) => (hours < 24 ? pts.slice(0, hours + 1) : pts);
  const series = [
    { name: "Pratique habituelle", color: "var(--ink-3)", pts: clip(ev[base]?.trajectory ?? []) },
    { name: "Avec le plan", color: "var(--brand)", pts: clip(ev[i]?.trajectory ?? []) },
  ];
  const n = series[0]!.pts.length;
  if (!n || series.some((s) => s.pts.some((p) => p.pressure_score === null))) {
    return <p className="mute">Score de tension non configuré : seules les composantes sont affichées.</p>;
  }
  const W = 640,
    H = 180,
    pad = 28;
  const top = 10;
  const x = (h: number) => pad + (h * (W - 2 * pad)) / Math.max(1, n - 1);
  const y = (v: number) => H - pad - (v * (H - 2 * pad)) / top;
  const threshold = reco.bundle!.score.threshold;
  return (
    <section className="panel" aria-labelledby="ds-chart-title">
      <header className="panel__head">
        <h2 className="panel__title" id="ds-chart-title">
          Tension heure par heure{hours < 24 ? ` · ${hours} premières heures` : ""}
        </h2>
      </header>
      <div className="panel__body ds-chart">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label="Score de tension expérimental heure par heure, pratique habituelle et plan"
        >
          <line x1={pad} y1={y(0)} x2={W - pad} y2={y(0)} stroke="var(--line-strong)" />
          <text x={pad - 6} y={y(0) + 4} fontSize={11} fill="var(--ink-3)" textAnchor="end">
            0
          </text>
          <text x={pad - 6} y={y(top) + 4} fontSize={11} fill="var(--ink-3)" textAnchor="end">
            {top}
          </text>
          {typeof threshold === "number" ? (
            <line
              x1={pad}
              y1={y(threshold)}
              x2={W - pad}
              y2={y(threshold)}
              stroke="var(--alerte)"
              strokeDasharray="4 4"
            />
          ) : null}
          {series.map((s) => (
            <polyline
              key={s.name}
              fill="none"
              stroke={s.color}
              strokeWidth={2.5}
              points={s.pts.map((p, h) => `${x(h)},${y(p.pressure_score ?? 0)}`).join(" ")}
            />
          ))}
          {series[0]!.pts
            .filter((_, h) => h % 4 === 0)
            .map((p) => (
              <text
                key={p.hour_index}
                x={x(p.hour_index)}
                y={H - 8}
                fontSize={11}
                fill="var(--ink-3)"
                textAnchor="middle"
              >
                {p.local_label}
              </text>
            ))}
        </svg>
        <div className="ds-legend">
          {series.map((s) => (
            <span key={s.name}>
              <i className="ds-sw" style={{ background: s.color }} />
              {s.name}
            </span>
          ))}
          <span>
            <i className="ds-sw ds-sw--dash" />
            Seuil de tension
          </span>
        </div>
        <p className="mute">
          Score expérimental sur 10, moyenne des scénarios heure par heure : pas une garantie sur toute la période. Le
          pic et le temps passé au-dessus du seuil comptent autant que l'heure finale.
        </p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- review and journal

/** The journal keeps plan decisions next to the unit's: same lifecycle, origin recorded. */
function planRecord(
  doc: DsDoc,
  source: DsSource,
  snapshot: DsSnapshot | null,
  unit: { id: string; name: string },
  decision: "approve" | "reject",
  reason?: string,
  planId?: string | null,
): DecisionRecord {
  const reco = doc.reco;
  const chosen = planId ?? reco.primary_plan_id ?? reco.locked_plan_id;
  const i = evalIndex(reco, chosen);
  const shown = reco.bundle?.evaluations[i];
  const base = reco.bundle?.evaluations[evalIndex(reco, reco.baseline_plan_id)];
  const actions = shown?.plan.actions ?? [];
  const at = (iso: string) => local(iso);
  const kind =
    planId && planId !== reco.primary_plan_id ? " (autre plan)" : reco.mode === "manual" ? " (variante)" : "";
  const shortList = actions.map((a) => actionShort(a, snapshot, at)).join(", ") || "pratique habituelle";
  const origin = source === "api" ? "decision-api" : "decision-fixture";
  // Figures and conditions are frozen in the record: the decision can be justified later
  // (user testing: « Pourquoi » said « il attend votre décision » once decided).
  const why = [
    ...(shown && base && reco.bundle
      ? [
          `Soins non couverts d'ici ${local(reco.bundle.horizon_end, true)} : ${fmt(base.metrics.uncovered_care_minutes)} → ${fmt(shown.metrics.uncovered_care_minutes)} min (pratique habituelle → plan)`,
          `Renfort : ${fmt(shown.metrics.reinforcement_hours)} h · attente de lit : ${fmt(base.metrics.waiting_patient_hours)} → ${fmt(shown.metrics.waiting_patient_hours)} patients·h`,
        ]
      : []),
    ...(shown?.conditional_on.length
      ? [`Suppose la venue de ${shown.conditional_on.join(", ")} (demandé, non confirmé)`]
      : []),
    ...humanReasons(reco.reasons).filter((r) => !r.includes("attend votre décision")),
  ];
  return {
    id: `${origin}:${reco.recommendation_id}${kind === " (autre plan)" ? `:${chosen}` : ""}`,
    origin,
    stateFingerprint: reco.snapshot_fingerprint ?? null,
    answerAt: "plan",
    planId: chosen ?? reco.recommendation_id,
    unitId: `plan:${unit.id}`,
    unitName: unit.name,
    situation: "Plan 24 h, unité fictive",
    stateAt: snapshot?.as_of ?? reco.created_at,
    proposedAt: reco.created_at,
    expiresAt: reco.valid_until,
    action: null,
    title: `Plan 24 h${kind} : ${shortList}`,
    short: `plan 24 h${kind} : ${shortList}`,
    todo: actions.length
      ? `Appliquez le plan dans vos outils : ${actions.map((a) => actionText(a, snapshot, at)).join(" ; ")}.`
      : undefined,
    rank: kind === " (autre plan)" ? 1 : 0,
    deltaRatio: null,
    horizonEnd: reco.bundle ? local(reco.bundle.horizon_end) : "",
    why,
    events: [
      { at: reco.created_at, type: "proposed", by: null },
      {
        at: reco.created_at,
        type: decision === "approve" ? "validated" : "refused",
        by: getMe(),
        ...(reason ? { reason } : {}),
      },
    ],
  };
}

/** Patients whose medical authorization must be checked again by a person before validating. */
function toRecheck(reco: DsRecommendation): string[] {
  return [
    ...new Set(
      reco.conditions
        .filter((c) => c.endsWith("revalidate_authorization_before_approval"))
        .map((c) => c.split(":")[1] ?? "")
        .filter(Boolean),
    ),
  ];
}

function ReviewButtons(props: {
  store: DecisionStore;
  doc: DsDoc;
  onModify?: () => void;
  unit: { id: string; name: string };
  /** The main plan answers to O / N / 1–6, like the unit's next action. */
  keys?: boolean;
}) {
  const { store, doc } = props;
  const [result, setResult] = useState<DsReview | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [confirmReplace, setConfirmReplace] = useState(false);
  const [checked, setChecked] = useState<string[]>([]);
  const [recordId, setRecordId] = useState<string | null>(null);
  const firstReason = useRef<HTMLButtonElement>(null);
  const { records, me } = useJournal();
  const origin = store.source === "api" ? "decision-api" : "decision-fixture";
  const unitKey = `plan:${props.unit.id}`;
  // A plan decided earlier (this page, a reload, a colleague's screen on this post) stays decided.
  const mainId = `${origin}:${doc.reco.recommendation_id}`;
  const earlier = records.find((r) => r.id === mainId) ?? records.find((r) => r.id.startsWith(`${mainId}:`));
  const active = records.find(
    (r) => r.unitId === unitKey && r.origin === origin && statusOf(r) === "validated" && r.id !== recordId,
  );
  const recheck = toRecheck(doc.reco);
  const ready = recheck.every((id) => checked.includes(id));
  const send = async (decision: "approve" | "reject", reason?: string, planId?: string | null) => {
    setConflict(null);
    setAsking(false);
    setConfirmReplace(false);
    try {
      const review = await store.review(doc, decision);
      setResult(review);
      if (review.outcome === "APPROVED_IN_DEMO" || review.outcome === "REJECTED") {
        // One active plan per unit: the earlier validated one is marked replaced.
        if (decision === "approve" && active) journal.act(active.id, "superseded", doc.reco.created_at);
        const record = planRecord(doc, store.source, store.snapshot, props.unit, decision, reason, planId);
        journal.record(record);
        setRecordId(record.id);
      }
    } catch (error) {
      // e.g. 409: the same idempotency key was already used for another request
      setResult(null);
      setConflict(String(error));
    }
  };
  const approve = () => {
    if (!ready) return;
    if (active && !confirmReplace) return setConfirmReplace(true);
    void send("approve");
  };
  useEffect(() => {
    if (asking) firstReason.current?.focus();
  }, [asking]);
  useEffect(() => {
    if (!props.keys) return;
    const on = (e: Event) => {
      const key = (e as CustomEvent<string>).detail;
      if (result || earlier) return;
      if (key === "yes" && doc.reco.approvable) approve();
      else if (key === "no") setAsking(true);
      else if (asking && /^[1-6]$/.test(key)) void send("reject", PLAN_REASONS[Number(key) - 1]!.id);
    };
    window.addEventListener("hos:shortcut", on);
    return () => window.removeEventListener("hos:shortcut", on);
  });
  const text: Record<DsReview["outcome"], string> = {
    APPROVED_IN_DEMO: "Plan validé. Rien n'a été envoyé : appliquez-le dans vos outils habituels.",
    REJECTED: "Refus noté. Il servira à mieux viser les prochains plans.",
    MODIFY_REQUESTED: "Modification demandée.",
    INVALIDATED: "Proposition invalidée : une nouvelle information est arrivée. Un recalcul est nécessaire.",
    REFUSED: "Validation impossible pour cette proposition.",
  };
  const noted = result && (result.outcome === "APPROVED_IN_DEMO" || result.outcome === "REJECTED");
  const record = recordId ? records.find((r) => r.id === recordId) : undefined;
  const reason = record?.events.find((e) => e.reason)?.reason;

  if (earlier && !result) {
    const s = statusOf(earlier);
    const step = [...earlier.events].reverse().find((e) => e.by && e.type !== "note");
    return (
      <div className="ds-outcome ds-outcome--quiet" data-testid="ds-decided" data-status={s}>
        <p className="ds-outcome__title">
          {s === "superseded"
            ? "Remplacé par un autre plan"
            : s === "refused" && step?.reason === "preferred_option"
              ? "L'autre plan a été choisi"
              : s === "refused"
                ? "Plan refusé"
                : s === "done"
                  ? "Plan appliqué"
                  : "Plan validé"}
          {step ? ` par ${who(step.by, me)} · ${local(step.at, true)}` : ""}
          {step?.reason && step.reason !== "preferred_option"
            ? ` · motif : ${reasonLabel(step.reason)?.toLowerCase()}`
            : ""}
        </p>
        <div className="ds-outcome__actions">
          <a className="btn btn--quiet" href={`#/journal/${encodeURIComponent(earlier.id)}`}>
            Voir dans le journal
          </a>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="ds-answer">
        {recheck.length && !noted && doc.reco.approvable ? (
          <fieldset className="ds-recheck" data-testid="ds-recheck">
            <legend>Avant de valider</legend>
            {recheck.map((id) => (
              <label key={id} className="ds-check">
                <input
                  type="checkbox"
                  checked={checked.includes(id)}
                  onChange={(e) => setChecked((c) => (e.target.checked ? [...c, id] : c.filter((x) => x !== id)))}
                />{" "}
                J'ai revérifié l'autorisation médicale de sortie de {id}
              </label>
            ))}
          </fieldset>
        ) : null}
        {noted ? null : (
          <div className="proposal__actions">
            <button
              type="button"
              className="btn btn--primary"
              data-testid="ds-approve"
              disabled={!doc.reco.approvable || !ready}
              title={
                !doc.reco.approvable
                  ? "Non applicable : hypothèse, abstention ou impossibilité"
                  : !ready
                    ? "Cochez d'abord la vérification de l'autorisation médicale"
                    : undefined
              }
              onClick={approve}
            >
              <Check /> Valider le plan {props.keys ? <kbd className="kbd">O</kbd> : null}
            </button>
            <button
              type="button"
              className="btn"
              data-testid="ds-reject"
              aria-expanded={asking}
              onClick={() => setAsking((v) => !v)}
            >
              Refuser {props.keys ? <kbd className="kbd">N</kbd> : null}
            </button>
            {props.onModify ? (
              <>
                <span className="spacer" />
                <button type="button" className="btn btn--quiet" data-testid="ds-modify" onClick={props.onModify}>
                  Simuler une variante
                </button>
              </>
            ) : null}
          </div>
        )}
      </div>
      {confirmReplace && active ? (
        <div className="feedback" role="group" data-testid="ds-confirm-replace">
          <p className="feedback__label">
            Un plan est déjà validé pour cette unité ({active.short}, {who(lastStepBy(active), me)}). Ce choix le
            remplace.
          </p>
          <div className="chips">
            <button type="button" className="btn btn--primary" onClick={() => void send("approve")}>
              Confirmer le remplacement
            </button>
            <button type="button" className="btn" onClick={() => setConfirmReplace(false)}>
              Garder le plan validé
            </button>
          </div>
        </div>
      ) : null}
      {asking ? (
        <div className="feedback" role="group" aria-labelledby={`why-${doc.id}`} data-testid="ds-reasons">
          <p className="feedback__label" id={`why-${doc.id}`}>
            Pourquoi ? Un appui suffit.
          </p>
          <div className="chips">
            {PLAN_REASONS.map((r, i) => (
              <button
                key={r.id}
                ref={i === 0 ? firstReason : undefined}
                type="button"
                className="chip"
                data-testid={`ds-reason-${r.id}`}
                onClick={() => void send("reject", r.id)}
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
      {result ? (
        <div
          className={`ds-outcome ds-outcome--${result.outcome === "APPROVED_IN_DEMO" ? "todo" : result.outcome === "REJECTED" ? "quiet" : "bad"}`}
          role="status"
          data-testid="ds-feedback"
          data-outcome={result.outcome}
        >
          <p className="ds-outcome__title">
            {text[result.outcome]}
            {reason && reason !== "preferred_option"
              ? ` Motif : ${PLAN_REASONS.find((r) => r.id === reason)?.label.toLowerCase() ?? reason}.`
              : null}
            {reason === "preferred_option"
              ? " Vous avez choisi l'autre plan : il est inscrit au journal, à faire."
              : null}
            {result.reasons.length ? ` (${result.reasons.join(", ")})` : null}
          </p>
          {result.replayed ? (
            <p className="mute" data-testid="ds-replayed">
              Reçu déjà enregistré pour cette même demande ; validité actuelle : {result.current_validity}.
            </p>
          ) : null}
          <div className="ds-outcome__actions">
            {noted && record ? (
              <button
                type="button"
                className="btn btn--quiet"
                onClick={() => {
                  journal.discard(record.id);
                  for (const r of records) if (r.id.startsWith(`${record.id}:`)) journal.discard(r.id);
                  if (active && statusOf(active) === "superseded") journal.undo(active.id);
                  setResult(null);
                  setRecordId(null);
                }}
              >
                Annuler
              </button>
            ) : null}
            {noted ? (
              <a className="btn btn--quiet" href={record ? `#/journal/${encodeURIComponent(record.id)}` : "#/journal"}>
                Voir dans le journal
              </a>
            ) : null}
            {result.recompute_required ? (
              <button type="button" className="btn btn--small" data-testid="ds-recompute" onClick={store.reload}>
                Recalculer maintenant
              </button>
            ) : null}
          </div>
          {record ? <NoteField record={record} now={record.proposedAt} /> : null}
        </div>
      ) : null}
      {conflict ? (
        <p className="ds-err" role="alert" data-testid="ds-conflict">
          Demande non traitée : {conflict}
        </p>
      ) : null}
    </>
  );
}

/**
 * « Choisir plutôt ce plan »: the proposal is refused (« autre option préférée ») and the other
 * plan of the same calculation becomes the team's plan (user testing: all or nothing was a block).
 */
function ChooseAlternative({
  store,
  doc,
  unit,
  planId,
}: {
  store: DecisionStore;
  doc: DsDoc;
  unit: { id: string; name: string };
  planId: string;
}) {
  const { records } = useJournal();
  const origin = store.source === "api" ? "decision-api" : "decision-fixture";
  const decided = records.some((r) => r.id.startsWith(`${origin}:${doc.reco.recommendation_id}`));
  const [error, setError] = useState<string | null>(null);
  if (decided) return null;
  const choose = async () => {
    try {
      const review = await store.review(doc, "reject");
      if (review.outcome !== "REJECTED") return setError("Choix impossible pour cette proposition.");
      const active = records.find(
        (r) => r.unitId === `plan:${unit.id}` && r.origin === origin && statusOf(r) === "validated",
      );
      if (active) journal.act(active.id, "superseded", doc.reco.created_at);
      journal.record(planRecord(doc, store.source, store.snapshot, unit, "reject", "preferred_option"));
      journal.record(planRecord(doc, store.source, store.snapshot, unit, "approve", undefined, planId));
    } catch (e) {
      setError(String(e));
    }
  };
  return (
    <div className="proposal__actions ds-alt-actions">
      <button type="button" className="btn" data-testid="ds-choose-alternative" onClick={() => void choose()}>
        Choisir plutôt ce plan
      </button>
      {error ? <span className="ds-err">{error}</span> : null}
    </div>
  );
}

const lastStepBy = (r: DecisionRecord) => [...r.events].reverse().find((e) => e.by && e.type !== "note")?.by ?? null;

function Conditions({ reco }: { reco: DsRecommendation }) {
  const groups = groupedConditions(reco.conditions);
  if (!groups.length) return null;
  return (
    <ul className="ds-conds" data-testid="ds-conditions">
      {groups.map((g) => (
        <li key={g.about}>
          <b>{g.about}</b> : {g.items.join(" · ")}
        </li>
      ))}
    </ul>
  );
}

function AutoPlan({
  store,
  onModify,
  unit,
  windowHours = 24,
}: {
  store: DecisionStore;
  onModify: () => void;
  unit: { id: string; name: string };
  windowHours?: number;
}) {
  const doc = store.auto!;
  const reco = doc.reco;
  const i = evalIndex(reco, reco.primary_plan_id);
  if (!reco.bundle || i < 0) {
    return (
      <section className="panel proposal proposal--abstain ds-primary" data-testid="ds-auto">
        <div className="proposal__band">
          <span className="proposal__kind" data-testid="ds-status" data-status={reco.status}>
            {(STATUS[reco.status] ?? [reco.status])[0]}
          </span>
        </div>
        <div className="proposal__main ds-stack">
          <h2 className="proposal__title">Pas de plan pour l'instant</h2>
          <p>
            Mieux vaut ne rien proposer qu'inventer des valeurs. Complétez ces informations dans vos outils habituels
            (planning, dossier), puis recalculez :
          </p>
          <Diagnostics items={reco.diagnostics} testId="ds-diagnostics" />
        </div>
        <div className="proposal__actions">
          <button type="button" className="btn" onClick={store.reload}>
            Recalculer
          </button>
        </div>
      </section>
    );
  }
  const base = evalIndex(reco, reco.baseline_plan_id);
  const primary = reco.bundle.evaluations[i]!;
  const alt = evalIndex(reco, reco.alternative_plan_id);
  const quiet = !primary.plan.actions.length;
  const reasons = humanReasons(reco.reasons);
  // A window shorter than the plan: what starts after it is listed apart, never dropped.
  const cut = Date.parse(reco.bundle.horizon_start) + windowHours * 3600_000;
  const windowed = windowHours < 24;
  const inside = primary.plan.actions.filter((a) => !windowed || Date.parse(a.window_start) < cut);
  const later = primary.plan.actions.filter((a) => windowed && Date.parse(a.window_start) >= cut);
  const cutLabel = local(new Date(cut).toISOString(), true);
  return (
    <>
      <section
        className={`panel proposal ds-primary${quiet ? " proposal--quiet" : ""}`}
        data-testid="ds-auto"
        aria-labelledby="ds-auto-title"
      >
        {/* The band carries the status: no second pill repeating it inside the card. */}
        <div className="proposal__band">
          <span className="proposal__kind" data-testid="ds-status" data-status={reco.status}>
            {(STATUS[reco.status] ?? [reco.status])[0]}
          </span>
          <span className="expiry">Valable jusqu'à {local(reco.valid_until)}</span>
        </div>
        <div className="proposal__main ds-stack">
          <h2 id="ds-auto-title" className="proposal__title">
            {quiet
              ? "Maintenir la pratique habituelle"
              : windowed
                ? `Pendant la garde, d'ici ${cutLabel}`
                : `À organiser d'ici ${local(reco.bundle.horizon_end, true)}`}
          </h2>
          {quiet ? (
            <p>Aucune action n'apporte d'amélioration sensible : rien n'est ajouté pour animer l'écran.</p>
          ) : (
            <>
              {inside.length ? (
                <ol className="ds-actions" data-testid="ds-actions">
                  {inside.map((a) => (
                    <ActionLine key={a.action_id} a={a} snapshot={store.snapshot} />
                  ))}
                </ol>
              ) : (
                <p data-testid="ds-actions-empty">
                  Rien à lancer pendant la garde : le plan commence après {cutLabel}.
                </p>
              )}
              {later.length ? (
                <Details
                  title={`Ensuite, après ${cutLabel} : ${later.length} action${later.length > 1 ? "s" : ""} du même plan`}
                >
                  <ol className="ds-actions ds-actions--later" data-testid="ds-actions-later">
                    {later.map((a) => (
                      <ActionLine key={a.action_id} a={a} snapshot={store.snapshot} />
                    ))}
                  </ol>
                </Details>
              ) : null}
            </>
          )}
          {primary.conditional_on.length ? (
            <p className="ds-warn" data-testid="ds-conditional">
              Le résultat suppose la venue de {primary.conditional_on.join(", ")}, demandé mais non confirmé. Sans ce
              renfort : <Fig doc={doc} ptr={`/bundle/evaluations/${i}/confirmed_only/uncovered_care_minutes`} /> minutes
              de soins non couvertes.
            </p>
          ) : null}
          {windowed ? (
            <p className="ds-note" data-testid="ds-window-note">
              Les effets ci-dessous portent sur tout le plan, calculé sur 24 h : le moteur ne sait pas isoler la garde.
            </p>
          ) : null}
          <Effect doc={doc} i={i} base={base} />
          <Bullets items={reasons} />
          <Details title="Avant de valider : conditions et incertitudes">
            <Conditions reco={reco} />
            <Bullets items={reco.uncertainties.map(uncertainty)} />
            <Diagnostics items={reco.diagnostics} testId="ds-plan-diagnostics" />
          </Details>
        </div>
        <ReviewButtons store={store} doc={doc} onModify={onModify} unit={unit} keys />
      </section>
      {alt >= 0 ? (
        <section className="panel" data-testid="ds-alternative">
          <header className="panel__head">
            <h2 className="panel__title">Autre plan possible</h2>
          </header>
          <div className="panel__body ds-stack">
            <ol className="ds-actions">
              {reco.bundle.evaluations[alt]!.plan.actions.map((a) => (
                <ActionLine key={a.action_id} a={a} snapshot={store.snapshot} />
              ))}
            </ol>
            <p className="mute">
              Soins non couverts : <Fig doc={doc} ptr={`/bundle/evaluations/${alt}/metrics/uncovered_care_minutes`} />{" "}
              min · renfort : <Fig doc={doc} ptr={`/bundle/evaluations/${alt}/metrics/reinforcement_hours`} /> h
            </p>
          </div>
          {reco.approvable ? (
            <ChooseAlternative store={store} doc={doc} unit={unit} planId={reco.alternative_plan_id!} />
          ) : null}
        </section>
      ) : null}
      <Chart reco={reco} i={i} base={base} hours={windowHours} />
    </>
  );
}

// ---------------------------------------------------------------- variant (manual mode)

function hourOptions(snapshot: DsSnapshot): Array<{ iso: string; label: string }> {
  const start = Date.parse(snapshot.as_of);
  return Array.from({ length: 23 }, (_, k) => {
    const iso = new Date(start + (k + 1) * 3_600_000).toISOString().replace(".000Z", "+00:00");
    return { iso, label: local(iso, true) };
  });
}

function sameInstant(a: string | null | undefined, b: string): boolean {
  return Boolean(a) && Date.parse(a!) === Date.parse(b);
}

function ManualForm({ store, prefill }: { store: DecisionStore; prefill: DsAction | null }) {
  const snap = store.snapshot!;
  const hours = hourOptions(snap);
  const x1Default =
    prefill?.target ??
    snap.stays.find((s) => s.medical_authorization === "authorized")?.stay_id ??
    snap.stays[0]?.stay_id;
  const x2 = snap.stays.find((s) => s.planned_departure);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const stay = (s: DsSnapshot["stays"][number]) =>
    `${s.stay_id} — ${AUTHORIZATION[s.medical_authorization] ?? s.medical_authorization}`;
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const locks: unknown[] = [
      { kind: "discharge_at", stay_id: f.get("x1"), at: f.get("x1_at"), basis: f.get("x1_basis") },
    ];
    if (f.get("x2"))
      locks.push({
        kind: "extend_presence",
        stay_id: f.get("x2"),
        reference_time: f.get("x2_ref"),
        extension_hours: Number(f.get("x2_t")),
        basis: "validated_instruction",
      });
    for (const r of snap.reinforcements) {
      const v = f.get(`r_${r.option_id}`);
      if (v !== "free") locks.push({ kind: "reinforcement", option_id: r.option_id, include: v === "include" });
    }
    setBusy(true);
    setError(null);
    try {
      await store.simulate({
        locks,
        deadline: { day_offset: 1, local_time: `${String(f.get("deadline"))}:00` },
        search_complements: f.get("complements") === "on",
      });
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="ds-form" data-testid="ds-manual-form" onSubmit={(e) => void submit(e)}>
      <fieldset>
        <legend>X1 · Sortie à une heure donnée</legend>
        <div className="ds-row">
          <label>
            Patient
            <select name="x1" className="select" defaultValue={x1Default}>
              {snap.stays.map((s) => (
                <option key={s.stay_id} value={s.stay_id}>
                  {stay(s)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Heure
            <select
              name="x1_at"
              className="select"
              defaultValue={hours.find((h) => sameInstant(prefill?.window_start, h.iso))?.iso ?? hours[0]?.iso}
            >
              {hours.map((h) => (
                <option key={h.iso} value={h.iso}>
                  {h.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Statut
            <select name="x1_basis" className="select" defaultValue="validated_instruction">
              <option value="validated_instruction">consigne validée</option>
              <option value="hypothesis_only">hypothèse seulement</option>
            </select>
          </label>
        </div>
      </fieldset>
      <fieldset>
        <legend>X2 · Présence prolongée</legend>
        <div className="ds-row">
          <label>
            Patient
            <select name="x2" className="select" defaultValue={x2?.stay_id ?? ""}>
              <option value="">aucun</option>
              {snap.stays.map((s) => (
                <option key={s.stay_id} value={s.stay_id}>
                  {stay(s)}
                </option>
              ))}
            </select>
          </label>
          <label>
            À partir de
            <select
              name="x2_ref"
              className="select"
              defaultValue={hours.find((h) => sameInstant(x2?.planned_departure, h.iso))?.iso ?? hours[0]?.iso}
            >
              {hours.map((h) => (
                <option key={h.iso} value={h.iso}>
                  {h.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Durée (heures)
            <input name="x2_t" type="number" min={0} max={12} defaultValue={4} data-testid="ds-x2-t" />
          </label>
        </div>
      </fieldset>
      <fieldset>
        <legend>Renforts et échéance</legend>
        <div className="ds-row">
          {snap.reinforcements.map((r) => (
            <label key={r.option_id} data-testid={`ds-reinforcement-${r.option_id}`}>
              {r.option_id} · {r.skill} · {provenance(r)} · {CONFIRMATION[r.confirmation] ?? r.confirmation}
              <select name={`r_${r.option_id}`} className="select" defaultValue="free">
                <option value="free">laisser HospitalOS choisir</option>
                <option value="include">imposer</option>
                <option value="exclude">exclure</option>
              </select>
            </label>
          ))}
          <label>
            Jusqu'à demain
            <input name="deadline" type="time" defaultValue="20:00" />
          </label>
        </div>
        <label className="ds-check">
          <input name="complements" type="checkbox" defaultChecked /> compléter avec d'autres actions compatibles
        </label>
      </fieldset>
      <div className="proposal__actions">
        <button type="submit" className="btn btn--primary" data-testid="ds-run-manual" disabled={busy}>
          {busy ? "Calcul…" : "Calculer la variante"}
        </button>
      </div>
      {error ? (
        <p className="ds-err" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}

function ManualResult({ store, unit }: { store: DecisionStore; unit: { id: string; name: string } }) {
  const doc = store.manual!;
  const reco = doc.reco;
  if (!reco.bundle) {
    return (
      <section className="panel" data-testid="ds-manual">
        <div className="panel__body">
          <Status reco={reco} />
          <Diagnostics items={reco.diagnostics} testId="ds-manual-diagnostics" error />
        </div>
      </section>
    );
  }
  const rows: Array<[string, string | null]> = [
    ["Pratique habituelle", reco.baseline_plan_id],
    ["Vos choix seuls", reco.locked_plan_id],
    ["Vos choix + compléments", reco.primary_plan_id],
  ];
  // An infeasible locked scenario has no primary plan: show the locks that were evaluated.
  const shown = reco.bundle.evaluations[evalIndex(reco, reco.primary_plan_id ?? reco.locked_plan_id)];
  return (
    <section className="panel" data-testid="ds-manual">
      <div className="panel__body ds-stack">
        <Status reco={reco} />
        {store.source === "fixture" ? (
          <p className="note" data-testid="ds-example-note">
            Exemple calculé à l'avance par le moteur : ces choix ne sont pas les vôtres.
          </p>
        ) : null}
        {shown ? (
          <ol className="ds-actions" data-testid="ds-manual-actions">
            {shown.plan.actions.map((a) => (
              <ActionLine key={a.action_id} a={a} snapshot={store.snapshot} example={store.source === "fixture"} />
            ))}
          </ol>
        ) : null}
        <Diagnostics items={reco.diagnostics} testId="ds-manual-diagnostics" error />
        <div className="table-wrap">
          <table className="table" data-testid="ds-branches">
            <caption className="ds-caption">
              Soins non couverts en minutes · attente de lit en patients·h · renfort en heures
            </caption>
            <thead>
              <tr>
                <th>Variante</th>
                <th className="r">Non couvert</th>
                <th className="r">Attente</th>
                <th className="r">Renfort</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([label, pid]) => {
                const k = evalIndex(reco, pid);
                if (k < 0) return null;
                const m = `/bundle/evaluations/${k}/metrics`;
                return (
                  <tr key={label}>
                    <td>{label}</td>
                    <td className="r">
                      <Fig doc={doc} ptr={`${m}/uncovered_care_minutes`} />
                    </td>
                    <td className="r">
                      <Fig doc={doc} ptr={`${m}/waiting_patient_hours`} />
                    </td>
                    <td className="r">
                      <Fig doc={doc} ptr={`${m}/reinforcement_hours`} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {reco.status === "HYPOTHETICAL_ONLY" ? (
          <p className="ds-warn">Simulation d'une hypothèse : elle ne peut pas devenir un plan à appliquer.</p>
        ) : null}
        <Bullets items={humanReasons(reco.reasons)} />
        <Details title="Conditions">
          <Conditions reco={reco} />
        </Details>
        <ReviewButtons key={doc.id} store={store} doc={doc} unit={unit} />
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- traceability

function HowFound({ doc, snapshot }: { doc: DsDoc; snapshot: DsSnapshot | null }) {
  const r = doc.reco;
  const b = r.bundle;
  return (
    <section className="panel" data-testid="ds-search" aria-labelledby="ds-how-title">
      <header className="panel__head">
        <h2 className="panel__title" id="ds-how-title">
          Comment ce plan a été trouvé
        </h2>
      </header>
      <div className="panel__body ds-stack">
        {b ? (
          <p>
            <Fig doc={doc} ptr="/bundle/search/evaluated" /> plans simulés sur{" "}
            <Fig doc={doc} ptr="/bundle/search/enumerated" /> possibles ; recherche{" "}
            <Fig
              doc={doc}
              ptr="/bundle/search/complete"
              format={(v: boolean) =>
                v
                  ? "complète dans ce périmètre"
                  : "incomplète : meilleur parmi les plans simulés, sans optimum revendiqué"
              }
            />
            .
          </p>
        ) : null}
        {b && Object.keys(b.search.rejected).length ? (
          <Details title={`Options écartées (${Object.keys(b.search.rejected).length})`}>
            <ul className="facts" data-testid="ds-rejected">
              {Object.entries(b.search.rejected).map(([k, v]) => {
                const x = rejection(k, v, snapshot);
                return (
                  <li key={k}>
                    <b>{x.about}</b> : {x.why}
                  </li>
                );
              })}
            </ul>
          </Details>
        ) : null}
        <Details title="Détail du calcul (moteur)">
          <ul className="facts ds-raw">
            {[...r.reasons, ...r.uncertainties].map((t) => (
              <li key={t}>
                <code>{t}</code>
              </li>
            ))}
          </ul>
        </Details>
        <p className="ds-prov mute" data-testid="ds-provenance">
          Recommandation {r.recommendation_id} · moteur {r.engine_version} · objectif {r.objective_version} · état{" "}
          {r.snapshot_id}
          {b ? ` · backend ${b.backend.name} ${b.backend.version} (${b.backend.code_sha256.slice(0, 12)})` : ""}
          {doc.sourceSha ? ` · copie compacte de la sortie SHA-256 ${doc.sourceSha.slice(0, 12)}` : ""} ·{" "}
          {r.scientific_status} · validation clinique : non · G2 {r.g2}
        </p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- page

// ---------------------------------------------------------------- 3 / 7 days: perspective

const DAY_MS = 86_400_000;

/**
 * Beyond 24 h nothing is planned: the page shows what is already known (planned departures,
 * reinforcement options and their confirmation) and what would be needed to plan further. No
 * figure is extrapolated. Days are 24-hour blocks from the plan start, so block 1 is the plan.
 */
function Perspective({ days, store }: { days: number; store: DecisionStore }) {
  const snap = store.snapshot;
  if (!snap) return <div className="skeleton" aria-busy="true" aria-label="Chargement" />;
  const start = Date.parse(snap.as_of);
  const blockOf = (iso: string) => Math.floor((Date.parse(iso) - start) / DAY_MS);
  const byDay = Array.from({ length: days }, (_, d) =>
    snap.stays.filter((st) => st.planned_departure && blockOf(st.planned_departure) === d),
  );
  const beyond = snap.stays.filter((st) => st.planned_departure && blockOf(st.planned_departure) >= days);
  const unknown = snap.stays.filter((st) => !st.planned_departure);
  const reco = store.auto?.reco;
  const primary = reco?.bundle?.evaluations[evalIndex(reco, reco.primary_plan_id)];
  const planned = (primary?.plan.actions ?? []).filter((x) => x.type === "coordinate_discharge");
  const last = byDay.reduce((n, l, d) => (l.length ? d : n), 0);
  return (
    <div className="ds-stack" data-testid="ds-perspective">
      <div className="notice notice--far" role="note">
        <b>Perspective, non planifiée.</b> Le plan s'arrête à 24 h (horizon supporté par le moteur). Ce qui suit est la
        situation connue à {local(snap.as_of, true)} : aucune action n'est proposée au-delà, et aucun chiffre n'est
        extrapolé.
      </div>
      <section className="panel" aria-labelledby="ds-far-days">
        <header className="panel__head">
          <h2 className="panel__title" id="ds-far-days">
            Sorties prévues, jour par jour
          </h2>
        </header>
        <div className="panel__body">
          <ol className="far-days" data-testid="ds-far-days">
            {byDay.slice(0, last + 1).map((list, d) => (
              <li
                key={d}
                className={`far-day${d === 0 ? " far-day--planned" : ""}${d > last ? " far-day--empty" : ""}`}
              >
                <span className="far-day__head">
                  <b>{d === 0 ? "Les 24 h du plan" : `Jour ${d + 1}`}</b>
                  <small>
                    {d === 0 ? "planifié" : "non planifié"} · jusqu'au{" "}
                    {local(new Date(start + (d + 1) * DAY_MS).toISOString(), true)}
                  </small>
                </span>
                <span className="far-day__n num">{list.length + (d === 0 ? planned.length : 0)}</span>
                <span className="far-day__list">
                  {[
                    ...(d === 0 ? planned.map((x) => `${x.target} (sortie à coordonner, plan proposé)`) : []),
                    ...list.map(
                      (st) => `${st.stay_id} (${AUTHORIZATION[st.medical_authorization] ?? st.medical_authorization})`,
                    ),
                  ].join(" · ") ||
                    (d > last
                      ? "Aucune sortie prévue connue : le dossier ne renseigne pas si loin."
                      : "Aucune sortie prévue")}
                </span>
              </li>
            ))}
            {last + 1 < days ? (
              <li className="far-day far-day--empty" data-testid="ds-far-empty">
                <span className="far-day__head">
                  <b>{last + 2 === days ? `Jour ${days}` : `Jours ${last + 2} à ${days}`}</b>
                  <small>non planifié · jusqu'au {local(new Date(start + days * DAY_MS).toISOString(), true)}</small>
                </span>
                <span className="far-day__n num">?</span>
                <span className="far-day__list">
                  Aucune sortie prévue connue : le dossier ne renseigne pas si loin. Ce n'est pas « zéro sortie ».
                </span>
              </li>
            ) : null}
          </ol>
          <p className="mute">
            {unknown.length} séjour{unknown.length > 1 ? "s" : ""} sans date de sortie prévue
            {beyond.length ? ` · ${beyond.length} prévu${beyond.length > 1 ? "s" : ""} au-delà` : ""}. Source : dates de
            sortie prévues du dossier, état du {local(snap.as_of, true)} ; plan proposé pour les 24 premières heures.
          </p>
        </div>
      </section>
      <section className="panel" aria-labelledby="ds-far-reinf">
        <header className="panel__head">
          <h2 className="panel__title" id="ds-far-reinf">
            Renforts mobilisables connus
          </h2>
        </header>
        <div className="panel__body">
          {snap.reinforcements.length ? (
            <ul className="far-reinf" data-testid="ds-far-reinf">
              {snap.reinforcements.map((r) => (
                <li key={r.option_id}>
                  <b>{r.skill}</b> · {provenance(r)} · {CONFIRMATION[r.confirmation] ?? r.confirmation}
                </li>
              ))}
            </ul>
          ) : (
            <p>Aucune option de renfort connue.</p>
          )}
          <p className="mute">
            Options valables pour les 24 h du plan. Pour les jours suivants, rien n'indique qu'elles resteront
            disponibles : à anticiper avec le planning.
          </p>
        </div>
      </section>
      <section className="panel" aria-labelledby="ds-far-need">
        <header className="panel__head">
          <h2 className="panel__title" id="ds-far-need">
            Pour planifier à {days} jours, il faudrait
          </h2>
        </header>
        <div className="panel__body">
          <ul className="far-need">
            <li>les entrées programmées (bloc, hôpital de jour, mutations prévues) jour par jour ;</li>
            <li>une date de sortie prévisionnelle pour chaque séjour, y compris ceux qui n'en ont pas ;</li>
            <li>le planning soignant validé sur la période, pas seulement la garde en cours ;</li>
            <li>une prévision des arrivées par les urgences, par jour, avec son incertitude.</li>
          </ul>
          <p className="mute">
            Tant que ces données manquent, un plan à {days} jours serait une extrapolation : HospitalOS préfère
            l'afficher comme une perspective.
          </p>
        </div>
      </section>
    </div>
  );
}

/** Window on the 24-hour plan (« focale »): 12 or 24 hours, or a 3/7-day perspective. */
export type PlanFocal = "12h" | "24h" | "3j" | "7j";

export function DecisionPlan({ focal = "24h" }: { focal?: PlanFocal }) {
  const store = useDecision();
  const windowHours = focal === "12h" ? 12 : 24;
  const far = focal === "3j" || focal === "7j";
  const [manualOpen, setManualOpen] = useState(false);
  const [prefill, setPrefill] = useState<DsAction | null>(null);
  const auto = store.auto;
  const unit = { id: store.unit, name: store.units.find((u) => u.id === store.unit)?.name ?? store.unit };
  const openManual = () => {
    const primary = auto?.reco.bundle?.evaluations[evalIndex(auto.reco, auto.reco.primary_plan_id)];
    setPrefill(primary?.plan.actions.find((a) => a.type === "coordinate_discharge") ?? null);
    setManualOpen(true);
    requestAnimationFrame(() => document.getElementById("ds-manual-title")?.scrollIntoView?.({ behavior: "smooth" }));
  };
  const [injected, setInjected] = useState<string[]>([]);
  return (
    <div className="ds-page">
      <div className="demobar" data-testid="ds-bar">
        <span className="demobar__tag">Démonstration</span>
        <span className="demobar__text">
          Unité fictive · prototype non validé (G2 NO-GO)
          {store.snapshot ? (
            <span data-testid="ds-asof">
              {Date.parse(store.snapshot.as_of) > Date.now()
                ? ` · plan préparé pour la relève de ${local(store.snapshot.as_of, true)}`
                : ` · situation au ${local(store.snapshot.as_of, true)}`}
            </span>
          ) : null}
        </span>
        {store.source === "fixture" ? (
          <span className="demobar__text" data-testid="ds-source">
            · résultats précalculés par le moteur, sans API locale
          </span>
        ) : null}
        <label className="demobar__select">
          <span className="visually-hidden">Unité fictive du plan</span>
          <select
            className="select"
            data-testid="ds-unit"
            value={store.unit}
            onChange={(e) => {
              setManualOpen(false);
              setInjected([]);
              store.setUnit(e.target.value);
            }}
          >
            {store.units.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <header className="page-head">
        <a className="back" href="#/">
          <Back size={14} /> Unité
        </a>
        <h1>
          <Illu name={far ? "signpost" : "path"} size={64} />
          {focal === "12h"
            ? "Plan de la garde (12 h)"
            : far
              ? `Perspective à ${focal === "3j" ? "3" : "7"} jours`
              : "Plan jusqu'à demain"}
        </h1>
        <p>
          {far
            ? "Le moteur ne planifie que sur 24 h. Au-delà, HospitalOS montre ce qui est déjà connu, sans proposer d'action ni inventer de plan."
            : focal === "12h"
              ? "Le plan à 24 h, lu sur les 12 prochaines heures : ce qui est à organiser pendant la garde. Les effets restent calculés sur 24 h."
              : "HospitalOS a prévu la pratique habituelle sur 24 h et cherché seul un meilleur plan : sorties à coordonner, renforts à demander. C'est vous qui décidez ; rien n'est envoyé."}
        </p>
      </header>
      {store.error ? (
        <div className="notice notice--error" role="alert">
          {store.error}
        </div>
      ) : null}
      {far ? (
        <Perspective days={focal === "3j" ? 3 : 7} store={store} />
      ) : (
        <div className="ds-grid">
          <div className="ds-col">
            {auto ? (
              <AutoPlan key={auto.id} store={store} onModify={openManual} unit={unit} windowHours={windowHours} />
            ) : (
              <div className="skeleton" aria-busy="true" aria-label="Calcul du plan" />
            )}
            {store.events.length && store.source === "api" ? (
              <div className="demobar">
                <span className="demobar__tag">Démonstration</span>
                <span className="demobar__text">Faire arriver une information :</span>
                {store.events.map((ev) => (
                  <button
                    key={ev.id}
                    type="button"
                    className="btn btn--quiet"
                    data-testid={`ds-inject-${ev.id}`}
                    disabled={injected.includes(ev.id)}
                    onClick={() => void store.inject(ev.id).then(() => setInjected((x) => [...x, ev.id]))}
                  >
                    {injected.includes(ev.id) ? `${ev.label} — reçue` : ev.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <aside className="ds-col" aria-labelledby="ds-manual-title">
            <h2 id="ds-manual-title" className="ds-h2">
              Simuler une variante <span className="mute">(optionnel)</span>
            </h2>
            <p className="mute">
              Imposez une heure de sortie (X1) ou une présence prolongée (X2) : le même moteur recalcule le reste du
              plan sans toucher à vos choix.
            </p>
            {!manualOpen ? (
              <button type="button" className="btn" data-testid="ds-open-manual" onClick={openManual}>
                Simuler une variante
              </button>
            ) : store.source === "api" && store.snapshot ? (
              <ManualForm store={store} prefill={prefill} />
            ) : (
              <div className="ds-examples" data-testid="ds-examples">
                <p className="note">
                  Sans l'API locale du moteur, la saisie libre n'est pas possible : voici des variantes calculées à
                  l'avance par le même moteur.
                </p>
                {store.manualExamples.map((m) => (
                  <button key={m.id} type="button" className="btn btn--small" onClick={() => store.showExample(m.id)}>
                    {m.label}
                  </button>
                ))}
              </div>
            )}
            {store.manual ? <ManualResult store={store} unit={unit} /> : null}
          </aside>
        </div>
      )}
      {auto && !far ? <HowFound doc={auto} snapshot={store.snapshot} /> : null}
    </div>
  );
}
