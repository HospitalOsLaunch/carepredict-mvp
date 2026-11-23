import { type FormEvent, type ReactNode, useState } from "react";
import { type DsAction, type DsRecommendation, type DsReview, type DsSnapshot, pointer } from "../api/decision";
import { type DecisionStore, type DsDoc, useDecision } from "../data/useDecision";
import "../styles/decision.css";

// 24-hour plan, auto first. No figure is written here: each number shown is read from an
// engine document and carries data-src="<doc>#<JSON pointer>" and data-raw (T32).

const STATUS: Record<string, [string, string]> = {
  RECOMMENDATION_READY: ["Proposition prête", "ds-pill--ready"],
  NO_ACTION_PREFERRED: ["Rien à changer : la pratique habituelle suffit", "pill--ok"],
  INSUFFICIENT_DATA: ["Abstention : données insuffisantes", "pill--bad"],
  INFEASIBLE: ["Impossible en l'état", "pill--bad"],
  HYPOTHETICAL_ONLY: ["Hypothèse simulée, non exécutable", "pill--warn"],
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

function ActionLine({ a, snapshot }: { a: DsAction; snapshot: DsSnapshot | null }) {
  const option = snapshot?.reinforcements.find((r) => r.option_id === a.target);
  let text: string;
  if (a.type === "coordinate_discharge")
    text = `Coordonner la sortie de ${a.target} : départ visé ${local(a.window_start)} (transport demandé maintenant, nettoyage après départ)`;
  else if (a.type === "reinforcement")
    text = `Renfort ${option?.skill ?? ""} ${local(a.window_start)}–${local(a.window_end)} (${a.target}, ${option?.source ?? ""})`;
  else if (a.type === "locked_discharge") text = `Sortie de ${a.target} à ${local(a.window_start)}`;
  else text = `Présence de ${a.target} prolongée jusqu'à ${local(a.window_start)} (${a.preconditions[0] ?? ""})`;
  return (
    <li>
      {text}
      {a.conditional ? <span className="ds-tag ds-tag--cond">demandé, non confirmé</span> : null}
      {a.origin === "manual_lock" ? <span className="ds-tag ds-tag--lock">verrouillé</span> : null}
      {a.basis === "hypothesis_only" ? <span className="ds-tag ds-tag--cond">hypothèse</span> : null}
    </li>
  );
}

function Details({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <details className="ds-details">
      <summary>
        {title} ({items.length})
      </summary>
      <ul className="facts">
        {items.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    </details>
  );
}

function Figures({ doc, i, base }: { doc: DsDoc; i: number; base: number }) {
  const p = `/bundle/evaluations/${i}/metrics`;
  const b = `/bundle/evaluations/${base}/metrics`;
  const item = (label: string, value: ReactNode) => (
    <div className="ds-fig" key={label}>
      <small>{label}</small>
      <b>{value}</b>
    </div>
  );
  return (
    <div className="ds-figs" data-testid="ds-figures">
      {item("Minutes de soins non couvertes", <><Fig doc={doc} ptr={`${b}/uncovered_care_minutes`} /> → <Fig doc={doc} ptr={`${p}/uncovered_care_minutes`} /></>)}
      {item("Attente de lit (patients·h)", <><Fig doc={doc} ptr={`${b}/waiting_patient_hours`} /> → <Fig doc={doc} ptr={`${p}/waiting_patient_hours`} /></>)}
      {item("IDE requis au pic (total)", <Fig doc={doc} ptr={`${p}/max_total_staff_required/IDE`} />)}
      {item("IDE en plus du planning (pic)", <Fig doc={doc} ptr={`${p}/max_additional_staff_required/IDE`} />)}
      {item("Heures de renfort", <Fig doc={doc} ptr={`${p}/reinforcement_hours`} />)}
      {item("Pression max (score expérimental)", <><Fig doc={doc} ptr={`${b}/peak_pressure`} /> → <Fig doc={doc} ptr={`${p}/peak_pressure`} /></>)}
      {item("Heures au-dessus du seuil", <><Fig doc={doc} ptr={`${b}/hours_above_threshold`} /> → <Fig doc={doc} ptr={`${p}/hours_above_threshold`} /></>)}
      {item("Lits remis à disposition", <Fig doc={doc} ptr={`${p}/beds_returned`} />)}
    </div>
  );
}

function Chart({ reco, i, base }: { reco: DsRecommendation; i: number; base: number }) {
  const ev = reco.bundle!.evaluations;
  const series = [
    { name: "Pratique habituelle", color: "var(--ink-3)", pts: ev[base]?.trajectory ?? [] },
    { name: "Plan", color: "var(--hos-violet)", pts: ev[i]?.trajectory ?? [] },
  ];
  const n = series[0]!.pts.length;
  if (!n || series.some((s) => s.pts.some((p) => p.pressure_score === null))) {
    return <p className="mute">Score de pression non configuré : seules les composantes sont affichées.</p>;
  }
  const W = 640, H = 180, pad = 28;
  const x = (h: number) => pad + (h * (W - 2 * pad)) / Math.max(1, n - 1);
  const y = (v: number) => H - pad - (v * (H - 2 * pad)) / 10;
  const threshold = reco.bundle!.score.threshold;
  return (
    <section className="panel" aria-labelledby="ds-chart-title">
      <header className="panel__head">
        <h2 className="panel__title" id="ds-chart-title">Trajectoire de pression, heure par heure</h2>
      </header>
      <div className="panel__body ds-chart">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Score de pression expérimental heure par heure, pratique habituelle et plan">
          <line x1={pad} y1={y(0)} x2={W - pad} y2={y(0)} stroke="var(--line-strong)" />
          {typeof threshold === "number" ? (
            <line x1={pad} y1={y(threshold)} x2={W - pad} y2={y(threshold)} stroke="var(--alerte)" strokeDasharray="4 4" />
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
          {series[0]!.pts.filter((_, h) => h % 4 === 0).map((p) => (
            <text key={p.hour_index} x={x(p.hour_index)} y={H - 8} fontSize={11} fill="var(--ink-3)" textAnchor="middle">
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
            <i className="ds-sw" style={{ background: "var(--alerte)" }} />
            seuil ({reco.bundle!.score.score_status})
          </span>
        </div>
        <p className="mute">
          Moyennes ponctuelles sur les scénarios de prévision : pas une garantie simultanée sur l'horizon. Le pic et le
          temps au-dessus du seuil comptent autant que la valeur finale.
        </p>
      </div>
    </section>
  );
}

function ReviewButtons(props: { store: DecisionStore; doc: DsDoc; onModify?: () => void }) {
  const { store, doc } = props;
  const [result, setResult] = useState<DsReview | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const send = async (decision: "approve" | "reject") => {
    setConflict(null);
    try {
      setResult(await store.review(doc, decision));
    } catch (error) {
      // e.g. 409: the same idempotency key was already used for another request
      setResult(null);
      setConflict(String(error));
    }
  };
  const text: Record<DsReview["outcome"], string> = {
    APPROVED_IN_DEMO: "Validée dans la démonstration. Aucune commande n'a été envoyée ; agissez dans vos outils habituels.",
    REJECTED: "Refusée. Merci, c'est noté.",
    MODIFY_REQUESTED: "Modification demandée.",
    INVALIDATED: "Proposition invalidée : une nouvelle information est arrivée. Un recalcul est nécessaire.",
    REFUSED: "Validation impossible pour cette proposition.",
  };
  return (
    <>
      <div className="proposal__actions">
        <button
          type="button"
          className="btn btn--primary ds-approve"
          data-testid="ds-approve"
          disabled={!doc.reco.approvable}
          title={doc.reco.approvable ? undefined : "Non approuvable : hypothèse, abstention ou impossibilité"}
          onClick={() => void send("approve")}
        >
          Valider (démo)
        </button>
        <button type="button" className="btn" data-testid="ds-reject" onClick={() => void send("reject")}>
          Refuser
        </button>
        {props.onModify ? (
          <button type="button" className="btn btn--quiet" data-testid="ds-modify" onClick={props.onModify}>
            Modifier
          </button>
        ) : null}
      </div>
      {result ? (
        <p className="ds-feedback" role="status" data-testid="ds-feedback" data-outcome={result.outcome}>
          {text[result.outcome]}
          {result.reasons.length ? ` (${result.reasons.join(", ")})` : null}
          {result.replayed ? (
            <span className="mute" data-testid="ds-replayed">
              {" "}
              Reçu déjà enregistré pour cette même demande ; validité actuelle : {result.current_validity}.
            </span>
          ) : null}
          {result.recompute_required ? (
            <>
              {" "}
              <button type="button" className="btn btn--small" data-testid="ds-recompute" onClick={store.reload}>
                Recalculer maintenant
              </button>
            </>
          ) : null}
        </p>
      ) : null}
      {conflict ? (
        <p className="ds-err" role="alert" data-testid="ds-conflict">
          Demande non traitée : {conflict}
        </p>
      ) : null}
    </>
  );
}

function AutoPlan({ store, onModify }: { store: DecisionStore; onModify: () => void }) {
  const doc = store.auto!;
  const reco = doc.reco;
  const i = evalIndex(reco, reco.primary_plan_id);
  if (!reco.bundle || i < 0) {
    return (
      <section className="panel ds-primary" data-testid="ds-auto">
        <div className="panel__body">
          <Status reco={reco} />
          <p>HospitalOS s'abstient plutôt que d'inventer des valeurs.</p>
          <ul className="facts" data-testid="ds-diagnostics">
            {reco.diagnostics.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </div>
      </section>
    );
  }
  const base = evalIndex(reco, reco.baseline_plan_id);
  const primary = reco.bundle.evaluations[i]!;
  const alt = evalIndex(reco, reco.alternative_plan_id);
  const s = reco.bundle.search;
  return (
    <>
      <section className="panel ds-primary" data-testid="ds-auto" aria-labelledby="ds-auto-title">
        <div className="panel__body ds-stack">
          <Status reco={reco} />
          <h2 id="ds-auto-title" className="proposal__title">
            {primary.plan.actions.length ? "Plan prioritaire" : "Maintenir la pratique habituelle"}
          </h2>
          {primary.plan.actions.length ? (
            <ol className="ds-actions" data-testid="ds-actions">
              {primary.plan.actions.map((a) => (
                <ActionLine key={a.action_id} a={a} snapshot={store.snapshot} />
              ))}
            </ol>
          ) : (
            <p>Aucune action n'apporte d'amélioration matérielle selon l'objectif versionné : rien n'est ajouté pour animer l'écran.</p>
          )}
          <Figures doc={doc} i={i} base={base} />
          {primary.conditional_on.length ? (
            <p className="ds-warn" data-testid="ds-conditional">
              Résultat conditionnel : {primary.conditional_on.join(", ")} demandé(s) mais non confirmé(s). Sans ce
              renfort : <Fig doc={doc} ptr={`/bundle/evaluations/${i}/confirmed_only/uncovered_care_minutes`} /> minutes
              non couvertes.
            </p>
          ) : null}
          <Details title="Raisons" items={reco.reasons} />
          <Details title="Conditions" items={reco.conditions} />
          <Details title="Incertitudes" items={reco.uncertainties} />
          <Details title="Hypothèses de remplacement et diagnostics" items={reco.diagnostics} />
          <ReviewButtons store={store} doc={doc} onModify={onModify} />
        </div>
      </section>
      {alt >= 0 ? (
        <section className="panel" data-testid="ds-alternative">
          <header className="panel__head">
            <h2 className="panel__title">Alternative réellement distincte</h2>
          </header>
          <div className="panel__body">
            <ol className="ds-actions">
              {reco.bundle.evaluations[alt]!.plan.actions.map((a) => (
                <ActionLine key={a.action_id} a={a} snapshot={store.snapshot} />
              ))}
            </ol>
            <p>
              Minutes non couvertes : <Fig doc={doc} ptr={`/bundle/evaluations/${alt}/metrics/uncovered_care_minutes`} /> ·
              heures de renfort : <Fig doc={doc} ptr={`/bundle/evaluations/${alt}/metrics/reinforcement_hours`} />
            </p>
          </div>
        </section>
      ) : null}
      <Chart reco={reco} i={i} base={base} />
      <section className="panel" data-testid="ds-search">
        <header className="panel__head">
          <h2 className="panel__title">Recherche</h2>
        </header>
        <div className="panel__body">
          <p>
            <Fig doc={doc} ptr="/bundle/search/evaluated" /> plans évalués sur{" "}
            <Fig doc={doc} ptr="/bundle/search/enumerated" /> admissibles ; recherche{" "}
            <Fig
              doc={doc}
              ptr="/bundle/search/complete"
              format={(v: boolean) =>
                v ? "complète sur cet univers borné" : "incomplète : meilleur parmi les évalués, aucun optimum revendiqué"
              }
            />
          </p>
          <Details title="Écartés et pourquoi" items={Object.entries(s.rejected).map(([k, v]) => `${k} : ${v}`)} />
        </div>
      </section>
    </>
  );
}

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
    prefill?.target ?? snap.stays.find((s) => s.medical_authorization === "authorized")?.stay_id ?? snap.stays[0]?.stay_id;
  const x2 = snap.stays.find((s) => s.planned_departure);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const locks: unknown[] = [{ kind: "discharge_at", stay_id: f.get("x1"), at: f.get("x1_at"), basis: f.get("x1_basis") }];
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
        <legend>X1 — sortie à une heure donnée</legend>
        <div className="ds-row">
          <label>
            Séjour
            <select name="x1" className="select" defaultValue={x1Default}>
              {snap.stays.map((s) => (
                <option key={s.stay_id} value={s.stay_id}>
                  {s.stay_id} — autorisation : {s.medical_authorization}
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
              <option value="validated_instruction">instruction validée</option>
              <option value="hypothesis_only">hypothèse seulement</option>
            </select>
          </label>
        </div>
      </fieldset>
      <fieldset>
        <legend>X2 — présence prolongée de t heures</legend>
        <div className="ds-row">
          <label>
            Séjour
            <select name="x2" className="select" defaultValue={x2?.stay_id ?? ""}>
              <option value="">aucun</option>
              {snap.stays.map((s) => (
                <option key={s.stay_id} value={s.stay_id}>
                  {s.stay_id} — autorisation : {s.medical_authorization}
                </option>
              ))}
            </select>
          </label>
          <label>
            Heure de référence
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
            t (heures)
            <input name="x2_t" type="number" min={0} max={12} defaultValue={4} data-testid="ds-x2-t" />
          </label>
        </div>
      </fieldset>
      <fieldset>
        <legend>Renforts et échéance</legend>
        <div className="ds-row">
          {snap.reinforcements.map((r) => (
            <label key={r.option_id}>
              {r.option_id} ({r.skill}, {r.confirmation})
              <select name={`r_${r.option_id}`} className="select" defaultValue="free">
                <option value="free">laisser chercher</option>
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
          <input name="complements" type="checkbox" defaultChecked /> rechercher des compléments compatibles
        </label>
      </fieldset>
      <div className="proposal__actions">
        <button type="submit" className="btn btn--primary ds-approve" data-testid="ds-run-manual" disabled={busy}>
          Calculer avec le même moteur
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

function ManualResult({ store }: { store: DecisionStore }) {
  const doc = store.manual!;
  const reco = doc.reco;
  if (!reco.bundle) {
    return (
      <section className="panel" data-testid="ds-manual">
        <div className="panel__body">
          <Status reco={reco} />
          <ul className="facts" data-testid="ds-manual-diagnostics">
            {reco.diagnostics.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </div>
      </section>
    );
  }
  const rows: Array<[string, string | null]> = [
    ["Pratique habituelle", reco.baseline_plan_id],
    ["Scénario verrouillé seul", reco.locked_plan_id],
    ["Verrouillé + compléments", reco.primary_plan_id],
  ];
  // An infeasible locked scenario has no primary plan: show the locks that were evaluated.
  const shown = reco.bundle.evaluations[evalIndex(reco, reco.primary_plan_id ?? reco.locked_plan_id)];
  return (
    <section className="panel" data-testid="ds-manual">
      <div className="panel__body ds-stack">
        <Status reco={reco} />
        {shown ? (
          <ol className="ds-actions" data-testid="ds-manual-actions">
            {shown.plan.actions.map((a) => (
              <ActionLine key={a.action_id} a={a} snapshot={store.snapshot} />
            ))}
          </ol>
        ) : null}
        {reco.diagnostics.length ? (
          <ul className="facts ds-err" data-testid="ds-manual-diagnostics">
            {reco.diagnostics.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        ) : null}
        <div className="table-wrap">
          <table className="table" data-testid="ds-branches">
            <caption className="ds-caption">
              Minutes de soins non couvertes · attente de lit en patients·h · heures de renfort
            </caption>
            <thead>
              <tr>
                <th>Branche</th>
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
                    <td className="r"><Fig doc={doc} ptr={`${m}/uncovered_care_minutes`} /></td>
                    <td className="r"><Fig doc={doc} ptr={`${m}/waiting_patient_hours`} /></td>
                    <td className="r"><Fig doc={doc} ptr={`${m}/reinforcement_hours`} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {reco.status === "HYPOTHETICAL_ONLY" ? (
          <p className="ds-warn">Simulation conditionnelle d'une hypothèse : elle ne peut pas devenir un plan exécutable.</p>
        ) : null}
        <Details title="Raisons" items={reco.reasons} />
        <Details title="Conditions" items={reco.conditions} />
        <ReviewButtons key={doc.id} store={store} doc={doc} />
      </div>
    </section>
  );
}

function Provenance({ doc }: { doc: DsDoc }) {
  const r = doc.reco;
  const b = r.bundle;
  return (
    <p className="ds-prov mute" data-testid="ds-provenance">
      Recommandation {r.recommendation_id} · moteur {r.engine_version} · objectif {r.objective_version} · snapshot{" "}
      {r.snapshot_id}
      {b ? ` · backend ${b.backend.name} ${b.backend.version} (${b.backend.code_sha256.slice(0, 12)})` : ""}
      {doc.sourceSha ? ` · copie compacte de la sortie SHA-256 ${doc.sourceSha.slice(0, 12)}` : ""} ·{" "}
      {r.scientific_status} · validation clinique : non · G2 {r.g2}
    </p>
  );
}

export function DecisionPlan() {
  const store = useDecision();
  const [manualOpen, setManualOpen] = useState(false);
  const [prefill, setPrefill] = useState<DsAction | null>(null);
  const auto = store.auto;
  const openManual = () => {
    const primary = auto?.reco.bundle?.evaluations[evalIndex(auto.reco, auto.reco.primary_plan_id)];
    setPrefill(primary?.plan.actions.find((a) => a.type === "coordinate_discharge") ?? null);
    setManualOpen(true);
  };
  const [injected, setInjected] = useState<string[]>([]);
  return (
    <div className="ds-page">
      <div className="page-head">
        <h1>Plan jusqu'à demain, calculé automatiquement</h1>
        <p>
          HospitalOS a observé l'unité, prévu la pratique habituelle et cherché lui-même un plan sur 24 h. C'est vous qui
          décidez ; rien n'est envoyé.
        </p>
        <div className="ds-bar">
          <label className="ds-unit">
            Unité
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
          {store.snapshot ? (
            <span className="mute" data-testid="ds-asof">
              Situation au {local(store.snapshot.as_of, true)} (Europe/Paris)
            </span>
          ) : null}
          <span className="ds-flag">Données synthétiques · prototype non validé · G2 NO-GO</span>
          {store.source === "fixture" ? (
            <span className="pill" data-testid="ds-source">
              Sorties du moteur, sans API locale
            </span>
          ) : null}
        </div>
      </div>
      {store.error ? (
        <div className="notice notice--error" role="alert">
          {store.error}
        </div>
      ) : null}
      <div className="ds-grid">
        <div className="ds-col">
          {auto ? <AutoPlan key={auto.id} store={store} onModify={openManual} /> : <div className="skeleton" aria-busy="true" aria-label="Calcul du plan" />}
          {store.events.length && store.source === "api" ? (
            <div className="demobar">
              <span className="demobar__tag">Démonstration</span>
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
            Simuler un scénario <span className="mute">(optionnel)</span>
          </h2>
          <p className="mute">
            Verrouillez des décisions X1/X2 ; le même moteur calcule les conséquences et cherche des compléments sans
            modifier vos verrous.
          </p>
          {!manualOpen ? (
            <button type="button" className="btn" data-testid="ds-open-manual" onClick={openManual}>
              Simuler un scénario
            </button>
          ) : store.source === "api" && store.snapshot ? (
            <ManualForm store={store} prefill={prefill} />
          ) : (
            <div className="ds-examples" data-testid="ds-examples">
              <p className="note">
                Sans l'API locale du moteur, la saisie libre n'est pas possible : voici des scénarios calculés à
                l'avance par le même moteur.
              </p>
              {store.manualExamples.map((m) => (
                <button key={m.id} type="button" className="btn btn--small" onClick={() => store.showExample(m.id)}>
                  {m.label}
                </button>
              ))}
            </div>
          )}
          {store.manual ? <ManualResult store={store} /> : null}
        </aside>
      </div>
      {auto ? <Provenance doc={auto} /> : null}
    </div>
  );
}
