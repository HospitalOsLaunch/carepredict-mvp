import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { COMPARISON_OBJECTIVES, worldApi, type ComparisonObjective, type WmSession, type WmWard } from "../api/worldModel";
import { plansApi, type PlanEvaluation, type PlanMenu, type UnitIntake, type UnitMetrics, type WardImpact } from "../api/worldPlans";
import { n, objectives, signed, time } from "../domain/worldModel";
import { Check } from "./icons";
import { WardOverview } from "./WardOverview";
import "../styles/unitDecision.css";

interface Props {
  view?: "unite" | "action";
  session: WmSession;
  ward: WmWard;
  onConfirmed: (session: WmSession) => void;
}

type Preference = {
  priority: ComparisonObjective;
  selection: string | null;
  draft: string[] | null;
};

function readPreference(key: string): Preference {
  const initial: Preference = { priority: "bed_wait", selection: null, draft: null };
  try {
    const raw: unknown = JSON.parse(window.sessionStorage.getItem(key) ?? "null");
    if (!raw || typeof raw !== "object") return initial;
    const value = raw as Record<string, unknown>;
    const validId = (id: unknown): id is string => typeof id === "string" && id.length > 0 && id.length <= 128;
    const priority = COMPARISON_OBJECTIVES.find(o => o === value.priority);
    if (!priority || !(value.selection === null || validId(value.selection)) ||
        !(value.draft === null || (Array.isArray(value.draft) && value.draft.length <= 128 &&
          value.draft.every(validId) && new Set(value.draft).size === value.draft.length))) return initial;
    return { priority, selection: value.selection, draft: value.draft };
  } catch { return initial; }
}

const priorities: Record<ComparisonObjective, string> = {
  bed_wait: "Réduire l’attente d’un lit",
  uncovered_care: "Couvrir la charge en soins",
  transfer_queue: "Réduire la file de transfert",
};
const measures = [
  ["care_minutes", "Soins IDE et AS non couverts", "min"],
  ["available_beds", "Lits propres disponibles", "lits"],
  ["transport_used", "Transport mobilisé", "courses-équivalentes"],
  ["beds_cleaned", "Lits remis en état", "lits"],
  ["smr_transfers", "Transferts en SMR", "patients-équivalents"],
  ["admissions", "Admissions", "patients-équivalents"],
  ["redirected_patients", "Réorientations", "patients-équivalents"],
  ["transfer_queue", "File de transfert", "patients-équivalents"],
] as const;
const formatSigned = (v: number) => signed.format(Math.abs(v) < 0.005 ? 0 : v);

function score(metrics: UnitMetrics, priority: ComparisonObjective) {
  if (priority === "bed_wait") return metrics.bed_wait_patient_hours;
  if (priority === "transfer_queue") return metrics.transfer_queue;
  return metrics.uncovered_ide_minutes + metrics.uncovered_as_minutes;
}

function errorMessage(error: unknown) {
  if (error instanceof ApiError && error.detail) return error.detail;
  if (error instanceof TypeError) return "Connexion au moteur de recommandation indisponible.";
  if (error instanceof Error && error.name !== "AbortError") return error.message;
  return "La réponse du moteur tarde à arriver.";
}

function Forecast({ before, after, priority, ward, cost }: {
  before: number; after: number; priority: ComparisonObjective; ward: string; cost: number;
}) {
  const objective = objectives[priority];
  const difference = after - before;
  return <div className="ud-forecast">
    <div className="ud-prediction"><p>{objective.column} · {ward}</p>
      <div><strong>{n(after)} <small>{objective.unit}</small></strong>
        <span className="ud-change"><span className="visually-hidden">Écart prévu · </span>{formatSigned(difference)} {objective.unit}</span></div>
      <p>Planning actuel · {n(before)} {objective.unit}</p>
    </div>
    <div className="ud-cost"><p>Coût additionnel</p><strong>{n(cost)} €</strong></div>
  </div>;
}

function UnitImpacts({ impact, unit }: { impact: WardImpact | undefined; unit: string }) {
  if (!impact) return null;
  return <details className="ud-details"><summary>Effets sur les ressources · {unit}</summary>
    <p>Écarts prévus avec le planning actuel entre 12 h et 16 h. Les files et les lits disponibles sont estimés à 16 h.</p>
    <dl className="ud-metrics">{measures.map(([key, label, measure]) => <div key={key}>
      <dt>{label}</dt><dd>{formatSigned(impact[key])} {measure}</dd>
    </div>)}</dl>
  </details>;
}

function HospitalEffects({ menu, plan, session, ward }: { menu: PlanMenu; plan: PlanEvaluation; session: WmSession; ward: WmWard }) {
  if (!plan.metrics || !menu.reference.metrics) return null;
  const metric = objectives[menu.objective];
  const elsewhere = plan.ward_impacts?.filter(w => w.ward_id !== ward.id &&
    [w.care_minutes, w.admissions, w.redirected_patients, w.transfer_queue].some(delta => Math.abs(delta) >= 0.005));
  return <details className="ud-details"><summary>Effets sur le reste de l’établissement</summary>
    <p>{metric.column} · {session.context.label} · {n(score(menu.reference.metrics, menu.objective))} → {n(score(plan.metrics, menu.objective))} {metric.unit}.</p>
    {!!elsewhere?.length && <div className="ud-table-wrap"><table><caption>Écarts prévus dans les autres unités concernées</caption>
      <thead><tr><th scope="col">Unité</th><th scope="col">Soins non couverts (min)</th>
        <th scope="col">Admissions</th><th scope="col">Réorientations</th><th scope="col">File de transfert</th></tr></thead>
      <tbody>{elsewhere.map(row => <tr key={row.ward_id}><th scope="row">{session.wards.find(w => w.id === row.ward_id)?.label}</th>
        <td>{formatSigned(row.care_minutes)}</td><td>{formatSigned(row.admissions)}</td><td>{formatSigned(row.redirected_patients)}</td><td>{formatSigned(row.transfer_queue)}</td>
      </tr>)}</tbody></table></div>}
  </details>;
}

function Actions({ menu, plan, session, saved }: { menu: PlanMenu; plan: PlanEvaluation; session: WmSession; saved: boolean }) {
  const list = menu.actions.filter(action => plan.action_ids.includes(action.id)).sort((a, b) => a.start_hour - b.start_hour);
  if (!list.length) return <p>Les affectations et les créneaux restent ceux du planning de référence.</p>;
  return <ol className="ud-actions">{list.map(a => {
    const ward = session.wards.find(w => w.id === a.ward_id)?.label;
    const complete = session.plan_report?.realized?.[a.id];
    const isPatient = a.kind === "admission" || a.kind === "discharge";
    return <li key={a.id}><div className="ud-times"><strong>{time(a.start_hour)}</strong><small>à {time(a.end_hour)}</small></div>
      <div><strong>{a.label}</strong>
        <p>{n(a.quantity)} {a.unit}{ward && !a.label.includes(ward) && ` · ${ward}`}{a.cost_eur > 0 && ` · ${n(a.cost_eur)} €`}</p>
        {saved && session.phase === "review" && isPatient && <small>{complete == null
          ? "Réalisation non renseignée" : `Relevé à 16 h · ${n(complete)} sur ${n(a.quantity)}`}</small>}
      </div></li>;
  })}</ol>;
}

export function UnitDecision(props: Props) {
  return <Decision key={JSON.stringify([props.session.context.id, props.session.id, props.ward.id, props.session.plan_version])} {...props} />;
}

function Decision({ view = "action", session, ward, onConfirmed }: Props) {
  const prefKey = "hospitalos.unit-decision." + JSON.stringify([session.context.id, session.id, ward.id, session.plan_version]);
  const [initial] = useState(() => readPreference(prefKey));
  const [priority, setPriority] = useState<ComparisonObjective>(initial.priority);
  const [menu, setMenu] = useState<PlanMenu | null>(null);
  const [failure, setFailure] = useState("");
  const [retry, setRetry] = useState(0);
  const [saving, setSaving] = useState(false);
  const [selection, setSelection] = useState<string | null>(initial.selection);
  const [draft, setDraft] = useState<string[] | null>(initial.draft);
  const [preview, setPreview] = useState<PlanEvaluation | null>(null);
  const [checking, setChecking] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [readOnlyState, setReadOnlyState] = useState<UnitIntake | null>(null);
  const [stateError, setStateError] = useState("");
  const inspection = useRef<AbortController | null>(null);
  const write = useRef<AbortController | null>(null);
  const accept = useRef(onConfirmed);
  accept.current = onConfirmed;
  const saved = session.phase !== "planning";
  const otherUnit = saved && session.decision_ward_id !== ward.id;
  const priorityInUse = saved ? session.decision_objective ?? priority : priority;

  useEffect(() => {
    try {
      if (saved) window.sessionStorage.removeItem(prefKey);
      else window.sessionStorage.setItem(prefKey, JSON.stringify({ priority, selection, draft }));
    } catch { /* The decision still works in memory when tab storage is unavailable. */ }
  }, [prefKey, saved, priority, selection, draft]);
  useEffect(() => () => { write.current?.abort(); inspection.current?.abort(); }, []);
  useEffect(() => {
    if (!otherUnit) return;
    const controller = new AbortController();
    plansApi.unitState(session.id, session.context.id, ward.id, controller.signal).then(value => {
      if (!controller.signal.aborted) setReadOnlyState(value);
    }).catch((error: unknown) => { if (!controller.signal.aborted) setStateError(errorMessage(error)); });
    return () => controller.abort();
  }, [otherUnit, session.id, session.context.id, ward.id, retry]);
  useEffect(() => {
    if (saved) return;
    const controller = new AbortController();
    setFailure(""); setMenu(null);
    plansApi.unitMenu(session.id, priority, ward.id, session.context.id, controller.signal).then(next => {
      if (controller.signal.aborted) return;
      const offered = new Set(next.actions.filter(a => a.eligible).map(a => a.id));
      setDraft(ids => ids && ids.some(id => !offered.has(id)) ? ids.filter(id => offered.has(id)) : ids);
      setSelection(id => id && [next.reference, ...next.recommendations].some(p => p.id === id) ? id : null);
      setMenu(next);
    }).catch(async (e: unknown) => {
      if (controller.signal.aborted) return;
      if (e instanceof ApiError && e.status === 409) {
        try {
          const current = await worldApi.read(session.id, session.context.id, controller.signal);
          if (!controller.signal.aborted && current.phase !== "planning") { accept.current(current); return; }
        } catch { /* Show the original rejection and offer a retry. */ }
      }
      if (!controller.signal.aborted) setFailure(errorMessage(e));
    });
    return () => controller.abort();
  }, [saved, session.id, session.context.id, ward.id, priority, retry]);

  const current = saved ? session.plan_snapshot : menu?.objective === priority && menu.ward_id === ward.id ? menu : null;
  const choices = current ? Array.from(new Map([...current.recommendations, current.reference].map(p => [p.id, p])).values()) : [];
  const top = current?.recommendations[0];
  const ranked = choices.find(p => p.id === selection) ?? top;
  const plan = saved ? session.confirmed_plan : draft !== null ? preview : ranked;
  const candidateOK = plan?.feasible && !plan.access_warnings?.length;
  const situation = otherUnit ? readOnlyState : current?.ward_state;
  function edit(ids: string[] | null) {
    inspection.current?.abort();
    inspection.current = null;
    setChecking(false); setDraft(ids); setPreview(null); setPreviewError("");
  }
  async function evaluateDraft() {
    if (draft === null || inspection.current || saved || saving) return;
    const controller = new AbortController();
    inspection.current = controller;
    setChecking(true); setPreviewError("");
    try {
      const result = await plansApi.unitPreview(session.id, session.context.id, ward.id, draft, priority, controller.signal);
      if (!controller.signal.aborted) setPreview(result);
    } catch (error) {
      if (!controller.signal.aborted) setPreviewError(errorMessage(error));
    } finally {
      if (inspection.current === controller) { inspection.current = null; setChecking(false); }
    }
  }
  const scope = session.wards.find(w => w.id === session.decision_ward_id)?.label ?? "l’établissement";
  const before = current?.reference.ward_metrics;
  const after = plan?.ward_metrics;
  const objective = objectives[priorityInUse];
  const impact = plan?.ward_impacts?.find(row => row.ward_id === ward.id);
  const count = plan?.action_ids.length ?? 0;

  async function confirm() {
    if (write.current || saved || failure || !plan || !candidateOK || !current) return;
    const controller = new AbortController();
    write.current = controller;
    setSaving(true);
    try {
      const next = await worldApi.confirmUnit(session.id, session.context.id, ward.id, plan, priority, controller.signal, draft !== null ? plan.id : undefined);
      if (!controller.signal.aborted) accept.current(next);
    } catch (e) {
      if (!controller.signal.aborted) {
        // A timeout or a competing write can follow a successful commit. Reconcile the journal.
        try {
          const latest = await worldApi.read(session.id, session.context.id, controller.signal);
          if (!controller.signal.aborted && latest.phase !== "planning") { accept.current(latest); return; }
        } catch { /* Keep the original diagnosis for the cadre. */ }
        if (!controller.signal.aborted) setFailure(errorMessage(e));
      }
    } finally {
      if (write.current === controller) write.current = null;
      if (!controller.signal.aborted) setSaving(false);
    }
  }

  const compact = view === "unite";
  const selectedIds = saved ? plan?.action_ids ?? [] : draft ?? plan?.action_ids ?? [];
  const selectedActions = current?.actions.filter(a => selectedIds.includes(a.id)).sort((a, b) => a.start_hour - b.start_hour) ?? [];
  const isDraft = !saved && draft !== null;
  let title = "Action à valider";
  if (otherUnit) title = `Décision enregistrée pour ${scope}`;
  else if (isDraft && plan && !candidateOK) title = "Composition à ajuster";
  else if (isDraft && !plan) title = "Composition à évaluer";
  else if (plan) {
    if (count === 0) title = "Maintenir le planning actuel";
    else if (count === 1) title = selectedActions[0]?.label ?? "Action recommandée";
    else title = `Coordonner ${count} actions`;
  }

  const feedback = <>
    {failure && <div className="ud-alert" role="alert"><p>{failure}</p>
      <button className="btn" onClick={() => { setFailure(""); setMenu(null); setRetry(r => r + 1); }}>Actualiser la recommandation</button></div>}
    {!failure && !saved && !current && <p role="status">Calcul de la recommandation pour {ward.label}…</p>}
    {!failure && !saved && current && !isDraft && !plan && <p role="status">Aucune action recommandée avec les données disponibles.</p>}
    {otherUnit && <p>Cette décision engage les ressources de {session.context.label}.</p>}
  </>;
  const recorded = saved && <p className="ud-status" role="status"><Check />Choix enregistré dans le journal de l’établissement.</p>;
  const scopeError = otherUnit && !situation && stateError && <p role="alert">{stateError} <button className="btn" onClick={() => {
    setStateError(""); setRetry(r => r + 1);
  }}>Relire la situation de l’unité</button></p>;
  const canAssess = !otherUnit && !failure && candidateOK && before && after;
  const delta = canAssess ? score(after, priorityInUse) - score(before, priorityInUse) : null;
  const sourceLabel = saved ? "Décision validée" : isDraft ? "Plan ajusté"
    : selection && plan?.id !== top?.id ? "Alternative sélectionnée" : "Recommandation de l’unité";
  if (compact) {
    return <WardOverview state={situation ?? null} ward={ward}
      selectedIds={candidateOK && !otherUnit ? plan?.action_ids ?? [] : []}>
      <section className="ud-compact" aria-label="Recommandation de l’unité">
        <div className="ud-compact-title"><p className="ud-overline">{sourceLabel}</p><h2>{title}</h2></div>
        <a className="btn" href="#/action">Ouvrir dans Action <span aria-hidden="true">→</span></a>
        <div className="ud-compact-body">
          {feedback}
          {!otherUnit && selectedActions.length > 0 && <ol className="ud-compact-actions">{selectedActions.map(a =>
            <li key={a.id}><strong>{a.label}</strong> <span>· {n(a.quantity)} {a.unit}</span></li>)}</ol>}
          {plan && canAssess && delta !== null && <p className="ud-compact-impact">
            <span>{objective.column} · <strong>{formatSigned(delta)} {objective.unit}</strong></span>
            <span>Coût additionnel · <strong>{n(plan.cost_eur)} €</strong></span>
          </p>}
          {isDraft && !plan && !failure && <p className="ud-muted">Évaluation requise pour estimer l’effet de cette composition.</p>}
          {isDraft && preview && !candidateOK && <p role="alert">{[...preview.conflicts, ...preview.access_warnings ?? []].join(" ")}</p>}
          {isDraft && previewError && <p role="alert">{previewError}</p>}
          {checking && <p role="status">Évaluation du plan en cours…</p>}
          {recorded}{scopeError}
        </div>
      </section>
    </WardOverview>;
  }

  return <div className="ud-stack">
    <section className="ud-card" aria-label="Recommandation de l’unité">
      <header className="ud-head"><div><p className="ud-overline">{sourceLabel}</p><h2>{title}</h2></div>
        {!saved && <label className="ud-priority">Priorité de l’unité<select className="select"
          value={priority} disabled={saving} onChange={e => {
            const choice = COMPARISON_OBJECTIVES.find(o => o === e.target.value);
            if (choice && choice !== priority) { edit(null); setSelection(null); setMenu(null); setFailure(""); setPriority(choice); }
          }}>{COMPARISON_OBJECTIVES.map(o => <option key={o} value={o}>{priorities[o]}</option>)}</select></label>}
      </header>
      {feedback}
      {plan && canAssess && <Forecast before={score(before, priorityInUse)} after={score(after, priorityInUse)}
        priority={priorityInUse} ward={ward.label} cost={plan.cost_eur}/>}
      {plan && current && !otherUnit && candidateOK && <Actions menu={current} plan={plan} session={session} saved={saved}/>}
      {recorded}
      {!saved && plan && current && candidateOK && !failure && <div className="ud-footer">
        <button className="btn btn--primary" disabled={saving} onClick={confirm}>
          {saving ? "Validation en cours…" : count === 0 ? "Valider le maintien du planning" : count === 1 ? "Valider l’action" : `Valider les ${count} actions`}</button>
        <span>Validation dans le journal de démo. Exécution manuelle dans le SIH.</span>
      </div>}
      {!saved && current && !failure && <div className="ud-tools">
        {draft === null && choices.length > 1 && <details className="ud-details"><summary>Comparer les alternatives</summary>
          <fieldset className="ud-picks" disabled={saving}><legend className="visually-hidden">Plans admissibles</legend>
            {choices.map(p => <label key={p.id}><input type="radio" name="unit-plan-choice" checked={p.id === ranked?.id}
              onChange={() => setSelection(p.id)}/><span><strong>{p.action_ids.length
              ? p.action_ids.map(id => current.actions.find(a => a.id === id)?.label).join(" + ")
              : "Maintenir le planning actuel"}</strong><small>{p.id === top?.id ? "Recommandé · " : ""}
                {p.ward_metrics && `${n(score(p.ward_metrics, priority))} ${objectives[priority].unit} · `}{n(p.cost_eur)} €</small></span></label>)}
          </fieldset></details>}
        {draft === null ? <button type="button" className="ud-link" disabled={saving}
          onClick={() => edit(ranked?.action_ids ?? [])}>Ajuster les actions</button>
          : <div className="ud-editor"><fieldset className="ud-picks" disabled={saving}><legend>Actions du plan ajusté</legend>
            {current.actions.filter(a => !current.scope_ids || current.scope_ids.includes(a.id)).map(a =>
              <label key={a.id}><input type="checkbox" disabled={!a.eligible} checked={draft.includes(a.id)}
                onChange={() => edit(draft.includes(a.id) ? draft.filter(id => id !== a.id) : [...draft, a.id])}/>
                <span><strong>{a.label}</strong><small>{n(a.quantity)} {a.unit} · {time(a.start_hour)} à {time(a.end_hour)} · {n(a.cost_eur)} €</small>
                {!a.eligible && <small>{a.constraint}</small>}</span></label>)}
          </fieldset><div className="ud-edit-controls"><button className="btn" disabled={checking || saving} onClick={evaluateDraft}>
            {checking ? "Calcul en cours…" : "Évaluer les actions"}</button>
            <button className="ud-link" disabled={saving} onClick={() => { edit(null); setSelection(null); }}>Revenir à la recommandation</button></div>
          {previewError && <p role="alert">{previewError}</p>}
          {preview && !candidateOK && <ul className="ud-alert" role="alert">{[...preview.conflicts, ...preview.access_warnings ?? []].map(w => <li key={w}>{w}</li>)}</ul>}
        </div>}
      </div>}
      {plan && current && !otherUnit && candidateOK && <div className="ud-evidence">
        {count > 0 && <details className="ud-details"><summary>Conditions et disponibilité des ressources</summary>
          <ul className="ud-conditions">{selectedActions.filter(a => a.constraint).map(a =>
            <li key={a.id}><strong>{a.label}</strong><p>{a.constraint}</p></li>)}</ul></details>}
        {impact && <UnitImpacts impact={impact} unit={ward.label}/>}
        {count > 0 && <HospitalEffects menu={current} plan={plan} session={session} ward={ward}/>}
        <details className="ud-details"><summary>Critère de sélection</summary>
          <p>{priorities[priorityInUse]} pour {ward.label}, entre 12 h et 16 h.</p>
          <p>{current.search.complete ? "Recherche exhaustive sur le périmètre disponible." : "Recherche partielle sur le périmètre disponible."}
            {current.search.examined != null && ` ${n(current.search.examined)} combinaisons examinées.`}</p></details>
      </div>}
      {otherUnit && impact && <UnitImpacts impact={impact} unit={ward.label}/>}
    </section>
  </div>;
}
