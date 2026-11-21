import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { COMPARISON_OBJECTIVES, worldApi, type ComparisonObjective, type WmSession, type WmWard } from "../api/worldModel";
import { plansApi, type PlanEvaluation, type PlanMenu, type UnitIntake, type UnitMetrics, type WardImpact } from "../api/worldPlans";
import { n, objectives, signed, time } from "../domain/worldModel";
import { Check, Clock } from "./icons";
import "../styles/unitDecision.css";

interface Props {
  session: WmSession;
  ward: WmWard;
  onConfirmed: (session: WmSession) => void;
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

function KnownCases({ list }: { list: UnitIntake["cases"] }) {
  if (!list.length) return <p className="ud-muted">Aucun dossier identifié dans le registre.</p>;
  return <ul className="ud-cases">{list.map(c => <li key={c.id}>
    <strong>{c.id}</strong><span>{c.eligible
      ? c.scheduled_hour === null ? `Disponible dès ${time(c.available_hour)}` : `Prévu à ${time(c.scheduled_hour)}`
      : "Accord en attente"}</span>
  </li>)}</ul>;
}

function Situation({ state, unit }: { state: UnitIntake; unit: string }) {
  return <section className="ud-situation" aria-label={`Situation · ${unit}`}>
    <header><h2>Situation de l’unité</h2><span><Clock />Données de {time(state.as_of_hour)}</span></header>
    <div className="ud-situ-grid">
      <section><h3>Sorties à coordonner</h3><KnownCases list={state.cases.filter(c => c.kind === "discharge")} /></section>
      <section><h3>Lits disponibles</h3><p className="ud-census"><strong>{n(state.available_beds)}</strong> sur {n(state.capacity_beds)} lits</p>
        <p className="ud-muted">Lits propres et libres estimés.</p></section>
      <section><h3>Admissions à organiser</h3><p className="ud-muted">File estimée de {n(state.admission_queue)} patients.</p>
        <KnownCases list={state.cases.filter(c => c.kind === "admission")} /></section>
    </div>
  </section>;
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
  return <Decision key={`${props.session.id}:${props.ward.id}`} {...props} />;
}

function Decision({ session, ward, onConfirmed }: Props) {
  const [priority, setPriority] = useState<ComparisonObjective>("bed_wait");
  const [menu, setMenu] = useState<PlanMenu | null>(null);
  const [failure, setFailure] = useState("");
  const [retry, setRetry] = useState(0);
  const [saving, setSaving] = useState(false);
  const [selection, setSelection] = useState<string | null>(null);
  const [draft, setDraft] = useState<string[] | null>(null);
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
      if (!controller.signal.aborted) setMenu(next);
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

  return <div className="ud-stack">
    <section className="ud-card" aria-label="Recommandation de l’unité">
      <header className="ud-head"><div><p className="ud-overline">{saved ? "Décision validée" : "Recommandation de l’unité"}</p>
        <h2>{otherUnit ? `Décision enregistrée pour ${scope}` : !saved && draft !== null && plan && !candidateOK ? "Composition à ajuster" : !saved && draft !== null && !plan ? "Composition à évaluer" : !plan ? "Action à valider" : count === 0 ? "Maintenir le planning actuel"
          : count === 1 ? current?.actions.find(a => a.id === plan.action_ids[0])?.label ?? "Action recommandée"
          : `Coordonner ${count} actions`}</h2></div>
        {!saved && <label className="ud-priority">Priorité de l’unité<select className="select"
          value={priority} disabled={saving} onChange={e => {
            const choice = COMPARISON_OBJECTIVES.find(o => o === e.target.value);
            if (choice) { edit(null); setSelection(null); setMenu(null); setFailure(""); setPriority(choice); }
          }}>{COMPARISON_OBJECTIVES.map(o => <option key={o} value={o}>{priorities[o]}</option>)}</select></label>}
      </header>
      {failure && <div className="ud-alert" role="alert"><p>{failure}</p>
        <button className="btn" onClick={() => { setFailure(""); setMenu(null); setRetry(r => r + 1); }}>Actualiser la recommandation</button></div>}
      {!failure && !saved && !current && <p role="status">Calcul de la recommandation pour {ward.label}…</p>}
      {!failure && !saved && current && draft === null && !plan && <p role="status">Aucune action recommandée avec les données disponibles.</p>}
      {otherUnit && <p>Cette décision engage les ressources de {session.context.label}.
        {impact && ` Ses effets prévus sur ${ward.label} figurent ci-dessous.`}</p>}
      {plan && current && !otherUnit && candidateOK && <>
        {before && after && <div className="ud-forecast">
          <div><p>{objective.column} · {ward.label}</p><strong>{n(score(after, priorityInUse))} <small>{objective.unit}</small></strong>
            <p>Prévision avec {count ? "la décision" : "le planning actuel"}</p></div>
          <div><p>Planning actuel</p><strong>{n(score(before, priorityInUse))} <small>{objective.unit}</small></strong></div>
        </div>}
        <Actions menu={current} plan={plan} session={session} saved={saved}/>
        {count > 0 && <details className="ud-details"><summary>Conditions et disponibilité des ressources</summary>
          <ul className="ud-conditions">{current.actions.filter(a => plan.action_ids.includes(a.id) && a.constraint).map(a =>
            <li key={a.id}><strong>{a.label}</strong><p>{a.constraint}</p></li>)}</ul></details>}
        {(saved || draft === null) && <p className="ud-muted">{plan.id !== current.recommendations[0]?.id ? "Plan alternatif."
          : current.search.complete ? "Meilleur plan admissible sur le périmètre de l’unité." : "Meilleur résultat parmi les combinaisons examinées."}
          {current.search.examined != null && ` ${n(current.search.examined)} combinaisons comparées.`}</p>}
      </>}
      {impact && <UnitImpacts impact={impact} unit={ward.label} />}
      {plan && current && !otherUnit && count > 0 && <HospitalEffects menu={current} plan={plan} session={session} ward={ward} />}
      {saved ? <p className="ud-status" role="status"><Check />Choix enregistré dans le journal de l’établissement.</p>
        : plan && current && candidateOK && !failure && <div className="ud-footer"><button className="btn btn--primary" disabled={saving || !plan.feasible}
          onClick={confirm}>{saving ? "Validation en cours…" : count === 0 ? "Valider le maintien du planning" : count === 1 ? "Valider l’action" : `Valider les ${count} actions`}</button>
          <span>Coût additionnel prévu <strong>{n(plan.cost_eur)} €</strong></span></div>}
      {(saved || plan) && <p className="ud-muted">La validation est enregistrée dans le journal de démo. Les réservations et demandes de renfort dans le SIH restent manuelles.</p>}
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
    </section>
    {situation && <Situation state={situation} unit={ward.label} />}
    {otherUnit && !situation && stateError && <p role="alert">{stateError} <button className="btn" onClick={() => { setStateError(""); setRetry(r => r + 1); }}>Relire la situation de l’unité</button></p>}
  </div>;
}
