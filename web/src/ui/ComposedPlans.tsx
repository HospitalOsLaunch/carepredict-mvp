import { useId, useState } from "react";
import { COMPARISON_OBJECTIVES, type ComparisonObjective, type WmSession } from "../api/worldModel";
import { ACTION_KINDS, WARD_METRICS, type CaseHours, type PlanAction, type PlanEvaluation, type PlanKind, type PlanMenu, type PlanMetrics, type WardImpact, type WardMetric } from "../api/worldPlans";
import { useComposedPlans } from "../data/useComposedPlans";
import { n, objectives, signed, time } from "../domain/worldModel";
import { Alert, Check, Clock, Refresh } from "./icons";
import { ContextCards, WorldJournal } from "./WorldJourney";
import "../styles/composedPlans.css";

const kinds: Record<PlanKind, string> = {
  discharge: "Sorties", admission: "Admissions", replacement: "Remplacements", redeployment: "Réaffectations",
  reinforcement: "Renforts", transport: "Transport", cleaning: "Bionettoyage", smr: "Places en SMR", beds: "Lits",
};
const impactGroups: Array<{ name: string; rows: Array<[keyof PlanMetrics, string]> }> = [
  { name: "Flux patients", rows: [["transfer_queue", "En attente de transfert à 16 h"], ["admissions", "Admissions"], ["discharges", "Sorties"],
    ["admission_queue_at_16", "En attente d’admission à 16 h"], ["redirected_patients", "Patients réorientés"],
    ["named_admissions", "Admissions de dossiers identifiés"], ["named_discharges", "Sorties de dossiers identifiés"]] },
  { name: "Personnel", rows: [["uncovered_ide_minutes", "Soins IDE non couverts (min)"], ["uncovered_as_minutes", "Soins AS non couverts (min)"]] },
  { name: "Transport", rows: [["transport_used", "Équivalents de courses réalisés"]] },
  { name: "Bionettoyage", rows: [["beds_cleaned", "Lits remis en état"]] },
  { name: "SMR", rows: [["smr_transfers", "Transferts en réadaptation"]] },
  { name: "Lits", rows: [["bed_wait_patient_hours", "Attente d’un lit (heures-patients)"], ["open_beds", "Lits ouverts à 16 h"], ["available_beds", "Lits propres libres à 16 h"]] },
];
const wardLabels: Record<WardMetric, string> = {
  transfer_queue: "File de transfert à 16 h (patients)", admissions: "Admissions (patients)", redirected_patients: "Réorientations (patients)",
  care_minutes: "Soins IDE et AS non couverts (min)", transport_used: "Transport (équivalents de courses)", beds_cleaned: "Bionettoyage (lits remis en état)",
  smr_transfers: "Transferts en SMR (patients)", available_beds: "Lits propres libres à 16 h",
};

function score(metrics: PlanMetrics, objective: ComparisonObjective) {
  if (objective === "transfer_queue") return metrics.transfer_queue;
  if (objective === "bed_wait") return metrics.bed_wait_patient_hours;
  return metrics.uncovered_ide_minutes + metrics.uncovered_as_minutes;
}
function lineCount(count: number) { return count + (count === 1 ? " intervention" : " interventions"); }
function offers(menu: PlanMenu): PlanEvaluation[] {
  const unique = new Map<string, PlanEvaluation>();
  for (const plan of [...menu.recommendations, menu.reference]) if (!unique.has(plan.id)) unique.set(plan.id, plan);
  return [...unique.values()];
}
function scope(menu: PlanMenu) {
  const { evaluated: count, examined, feasible, recommendable, complete } = menu.search;
  if (examined !== undefined && feasible !== undefined) {
    const protectedCount = recommendable === undefined ? "" : ` · ${n(recommendable)} préservent l’accès`;
    return `${n(examined)} combinaisons examinées · ${n(count)} simulées · ${n(feasible)} réalisables${protectedCount} · recherche ${complete ? "exhaustive" : "partielle"}`;
  }
  return `${n(count)} combinaison${count > 1 ? "s" : ""} évaluée${count > 1 ? "s" : ""} · recherche ${menu.search.complete ? "exhaustive" : "partielle"}`;
}
function title(plan: PlanEvaluation, menu: PlanMenu, index: number) {
  if (plan.id === menu.reference.id) return plan.id === menu.recommendations[0]?.id
    ? "Référence · meilleur plan évalué" : "Planning horaire de référence";
  return plan.id === menu.recommendations[0]?.id ? "Meilleur plan évalué" : "Alternative " + index;
}
function describe(action: PlanAction) {
  return `${n(action.quantity)} ${action.unit} · ${time(action.start_hour)}–${time(action.end_hour)} · ${n(action.cost_eur)} €`;
}
function actionNames(ids: string[], actions: PlanAction[], limit?: number) {
  const names = ids.slice(0, limit).map(id => actions.find(a => a.id === id)?.label ?? id);
  if (limit && ids.length > limit) names.push(`+${ids.length - limit}`);
  return names.join(" · ");
}

function PlanChoice({ menu, objective, activeId, onPick, disabled, group }: {
  menu: PlanMenu; objective: ComparisonObjective; activeId: string | null; onPick: (id: string) => void; disabled: boolean; group: string;
}) {
  const name = useId();
  return <fieldset className="jp-picks" disabled={disabled}><legend className="visually-hidden">{group}</legend>
    {offers(menu).map((plan, i) => {
      const label = title(plan, menu, i);
      return <label key={plan.id} className={`jp-pick${activeId === plan.id ? " is-picked" : ""}`}>
        <input type="radio" name={name} checked={activeId === plan.id} onChange={() => onPick(plan.id)} aria-label={label} />
        <span className="jp-pick__body"><strong>{label}</strong>
          <small>{lineCount(plan.action_ids.length)} · {n(plan.cost_eur)} €</small>
          {plan.action_ids.length > 0 && <small>{actionNames(plan.action_ids, menu.actions, 2)}</small>}
        </span>
        <span className="jp-score"><strong>{plan.metrics ? n(score(plan.metrics, objective)) : "Non renseigné"}</strong><small>{objectives[objective].unit}</small></span>
      </label>;
    })}
  </fieldset>;
}

function ActionList({ plan, actions, actual }: { plan: PlanEvaluation; actions: PlanAction[]; actual?: Record<string, number> | null }) {
  if (!plan.action_ids.length) return <p className="jp-hint">Le plan conserve les affectations horaires prévues à midi.</p>;
  return <ul className="jp-action-list">{plan.action_ids.map(id => {
    const a = actions.find(item => item.id === id);
    const isPatient = a?.kind === "admission" || a?.kind === "discharge";
    const isStaff = a?.kind === "replacement" || a?.kind === "redeployment" || a?.kind === "reinforcement";
    return <li key={id}><strong>{a?.label ?? id}</strong>
      {a && <small>{describe(a)}</small>}
      {isPatient && plan.realized[id] != null && <small>Réalisation prévue · {n(plan.realized[id]!)} sur {n(a!.quantity)}</small>}
      {isPatient && actual?.[id] != null && <small>Réalisation relevée · {n(actual[id]!)} sur {n(a!.quantity)}</small>}
      {isStaff && plan.realized[id] != null && <small>Temps mobilisé prévu · {n(plan.realized[id]!)} min</small>}
      {isStaff && actual?.[id] != null && <small>Temps mobilisé relevé · {n(actual[id]!)} min</small>}
    </li>;
  })}</ul>;
}

function CaseTimes({ plan, reference, actual }: { plan: CaseHours; reference?: CaseHours; actual?: CaseHours | null }) {
  const ids = [...new Set([...Object.keys(reference ?? {}), ...Object.keys(plan), ...Object.keys(actual ?? {})])].sort();
  if (!ids.length) return null;
  const display = (hour: number | null | undefined) => hour === undefined ? "Non renseignée" : hour === null ? "Non réalisé à 16 h" : time(hour);
  return <details className="jp-disclosure"><summary>Horaires des admissions et des sorties identifiées</summary>
    <div className="jp-table-wrap"><table className="jp-impacts"><thead><tr><th scope="col">Dossier</th>
      <th scope="col">Référence</th><th scope="col">Plan prévu</th>{actual && <th scope="col">Relevé</th>}</tr></thead>
      <tbody>{ids.map(id=><tr key={id}><th scope="row">{id}</th><td>{display(reference?.[id])}</td>
        <td>{display(plan[id])}</td>{actual && <td>{display(actual[id])}</td>}</tr>)}</tbody>
    </table></div>
  </details>;
}

function WardEffects({ impacts, wards }: { impacts: WardImpact[]; wards: WmSession["wards"] }) {
  const [metric,setMetric] = useState<WardMetric>("transfer_queue");
  return <details className="jp-disclosure"><summary>Effets par unité</summary>
    <p className="jp-hint">Écarts prévus entre le plan sélectionné et le planning horaire pour chaque unité.</p>
    <label className="jp-input-label">Indicateur par unité<select className="select" value={metric} onChange={e=>{
      const next=WARD_METRICS.find(k=>k===e.target.value); if(next) setMetric(next);
    }}>{WARD_METRICS.map(k=><option key={k} value={k}>{wardLabels[k]}</option>)}</select></label>
    <div className="jp-table-wrap"><table className="jp-impacts"><caption className="visually-hidden">Écarts prévus par unité</caption>
      <thead><tr><th scope="col">Unité</th><th scope="col">Écart prévu</th></tr></thead>
      <tbody>{wards.map(ward=>{
        const delta=impacts.find(impact=>impact.ward_id===ward.id)?.[metric];
        return <tr key={ward.id}><th scope="row">{ward.label}</th><td>{delta == null ? "Non renseigné" : signed.format(delta)}</td></tr>;
      })}</tbody>
    </table></div>
  </details>;
}

function ImpactTable({ plan, reference, actual, wards, id, returnId }: {
  plan: PlanEvaluation; reference: PlanEvaluation | undefined; actual?: PlanMetrics | null; wards: WmSession["wards"]; id: string; returnId?: string;
}) {
  const m = plan.metrics;
  if (!m) return null;
  return <section id={id} tabIndex={-1} className="wm-card jp-card jp-impact-panel" aria-label="Impacts du plan par ressource">
    <p className="wm-eyebrow">Projection conjointe à midi</p><h2>Effets sur les ressources</h2>
    <p className="jp-hint">Les flux et les soins sont cumulés de 12 h à 16 h. Les stocks sont évalués à 16 h.</p>
    <div className="jp-table-wrap"><table className="jp-impacts">
      <caption className="visually-hidden">Impacts chiffrés du plan comparés au planning horaire</caption>
      <thead><tr><th scope="col">Indicateur</th><th scope="col">Référence</th><th scope="col">Plan</th><th scope="col">Écart</th>
        {actual && <th scope="col">Relevé</th>}</tr></thead>
      {impactGroups.map((group) => <tbody key={group.name}>
        <tr className="jp-table-group"><th scope="rowgroup" colSpan={actual ? 5 : 4}>{group.name}</th></tr>
        {group.rows.map(([key, label]) => {
          const base = reference?.metrics?.[key];
          const value = m[key];
          const measured = actual?.[key];
          if (value === undefined && base === undefined && measured === undefined) return null;
          return <tr key={key}><th scope="row">{label}</th><td>{base == null ? "—" : n(base)}</td>
            <td>{value == null ? "—" : n(value)}</td><td>{base == null || value == null ? "—" : signed.format(value - base)}</td>
            {actual && <td>{measured == null ? "—" : n(measured)}</td>}</tr>;
        })}
      </tbody>)}
    </table></div>
    {!!plan.ward_impacts?.length && <WardEffects impacts={plan.ward_impacts} wards={wards} />}
    {returnId && <button type="button" className="wm-jump" onClick={()=>document.getElementById(returnId)?.focus()}>Revenir au plan à valider</button>}
  </section>;
}

function Editor({ menu, ids, setIds, locked, working, evaluate, optimize }: {
  menu: PlanMenu; ids: string[]; setIds: (ids: string[]) => void; locked: boolean; working: string | null;
  evaluate: () => void; optimize: () => void;
}) {
  const [filter, setFilter] = useState<PlanKind | "all">("all");
  const visible = filter === "all" ? menu.actions : menu.actions.filter(a => a.kind === filter);
  const omitted = ids.filter(id => !menu.actions.some(a => a.id === id));
  return <section className="wm-card jp-card" aria-label="Éditeur de composition">
    <p className="wm-eyebrow">Composition manuelle</p><h2>Choisir les interventions</h2>
    <p className="jp-hint">Chaque ligne désigne une intervention avec sa destination et sa quantité.</p>
    <label className="jp-input-label">Famille d’interventions
      <select className="select" value={filter} onChange={e => setFilter(ACTION_KINDS.find(k => k === e.target.value) ?? "all")}>
        <option value="all">Toutes les interventions</option>
        {ACTION_KINDS.filter(k => menu.actions.some(a => a.kind === k)).map(k => <option key={k} value={k}>{kinds[k]}</option>)}
      </select>
    </label>
    <fieldset className="jp-editor-list" disabled={locked}><legend className="visually-hidden">Interventions du brouillon</legend>
      {visible.map(a => {
        const checked = ids.includes(a.id);
        return <label key={a.id} className={`jp-editor-action${checked ? " is-picked" : ""}`}>
          <input type="checkbox" checked={checked} disabled={!a.eligible && !checked} aria-label={a.label}
            onChange={() => setIds(checked ? ids.filter(id => id !== a.id) : [...ids,a.id])} />
          <span><strong>{a.label}</strong><small>{describe(a)}</small>
            {a.constraint && <small>{a.eligible ? a.constraint : "Indisponible à midi · " + a.constraint}</small>}
            {!a.eligible && !a.constraint && <small>Indisponible à midi</small>}
          </span>
        </label>;
      })}
    </fieldset>
    {omitted.length > 0 && <div className="jp-conflicts" role="alert">Certaines interventions du brouillon sont absentes du catalogue.
      {omitted.map(id => <button className="wm-jump" key={id} type="button" onClick={() => setIds(ids.filter(x=>x!==id))}>Retirer {id}</button>)}
    </div>}
    <div className="jp-editor-controls"><strong>{lineCount(ids.length)} dans le brouillon</strong>
      <button type="button" className="btn" disabled={locked || !!working || !!omitted.length} onClick={evaluate}>
        {working === "preview" ? "Évaluation en cours…" : "Évaluer ma composition"}</button>
      {ids.length > 1 && <button type="button" className="wm-jump" disabled={locked || !!working || !!omitted.length} onClick={optimize}>
        {working === "optimize" ? "Comparaison en cours…" : "Comparer les sous-ensembles"}</button>}
    </div>
  </section>;
}

function Reading({ session, actions }: { session: WmSession; actions: PlanAction[] }) {
  const report = session.plan_report!;
  const observation = session.observation!;
  const [other, setOther] = useState<string | null>(null);
  const alternatives = report.alternatives.filter(a => a.plan.id !== session.selected_id);
  const changes = alternatives.filter(a => a.plan.action_ids.length > 0);
  const selected = alternatives.find(a => a.plan.id === other) ?? alternatives[0];
  const label = (plan: PlanEvaluation) => plan.action_ids.length ? actionNames(plan.action_ids, actions, 3) : "Planning horaire de référence";
  return <section className="wm-card jp-card" aria-label="Relevé du plan composé">
    <p className="wm-eyebrow">Publication à {time(observation.published_hour)}</p><h2>La file observée à 16 h</h2>
    <div className="jp-readouts"><div><span>Plan validé · file observée</span><strong>{observation.observed_stock === null ? "Non renseignée" : n(observation.observed_stock)}</strong></div>
      {selected && <div><span>Autre plan · file estimée</span><strong>{n(selected.reconstructed_queue)}</strong></div>}</div>
    <p className="jp-hint">{observation.visible_components} composantes du relevé publiées sur {observation.total_components}. File exprimée en équivalents patients.</p>
    {selected && <label className="jp-input-label">Autre plan à estimer
      <select className="select" value={selected.plan.id} onChange={e=>setOther(e.target.value)}>
        {alternatives.map(a => <option key={a.plan.id} value={a.plan.id}>{a.plan.action_ids.length > 0 ? `Alternative ${changes.indexOf(a)+1} · ` : ""}{label(a.plan)}</option>)}
      </select>
    </label>}
    {selected && <p className="jp-hint">Le modèle utilise les composantes publiées pour estimer la file du plan alternatif.</p>}
    {selected && selected.plan.action_ids.length > 0 && <details className="jp-disclosure">
      <summary>Interventions de l’autre plan ({selected.plan.action_ids.length})</summary>
      <ActionList plan={selected.plan} actions={actions} />
    </details>}
    {report.actual_metrics === null && <p className="jp-hint">Les mesures complètes de ressources du plan restent inconnues dans ce relevé.</p>}
    <details className="jp-disclosure"><summary>File observée par unité</summary>
      <dl>{session.wards.map((ward,i) => <div key={ward.id}><dt>{ward.label}</dt>
        <dd>{observation.by_ward[i] == null ? "Non renseignée" : n(observation.by_ward[i]!)}</dd></div>)}</dl>
    </details>
  </section>;
}

export function ComposedPlans({ session, locked, busy, onConfirm, onAdvance }: {
  session: WmSession; locked: boolean; busy: string | null;
  onConfirm: (ids: string[], objective: ComparisonObjective, scopeIds?: string[]) => Promise<void>; onAdvance: () => Promise<void>;
}) {
  const work = useComposedPlans(session);
  const { menu, objective, draft } = work;
  const planning = session.phase === "planning";
  const saved = session.confirmed_plan;
  const choices = menu ? offers(menu) : [];
  const suggested = choices.find(p => p.id === work.pick) ?? choices[0];
  const subsidiary = work.subsets && offers(work.subsets).find(p => p.id === work.subsetId);
  const plan = saved ?? (draft ? subsidiary ?? work.preview : suggested);
  const disabled = locked || Boolean(work.working);
  const actions = menu?.actions ?? [];
  const actual = session.plan_report?.actual_metrics;
  const canConfirm = planning && !!plan?.feasible && !!menu && !disabled;
  const displayedIds = plan?.action_ids ?? draft?.ids ?? [];
  const detailsId = useId();
  const impactId = useId();
  return <div className="jp-layout"><div className="jp-main">
    {planning && <section className="wm-card jp-card" aria-label="Plans composés proposés">
      <div className="jp-head"><div><p className="wm-eyebrow">Décision de midi</p><h2>Comparer les plans composés</h2></div>
        {menu && <span className="wm-time-chip">Budget {n(menu.budget_eur)} €</span>}</div>
      <label className="jp-input-label">Critère du plan à midi
        <select className="select" value={objective} disabled={locked} onChange={e => {
          const next=COMPARISON_OBJECTIVES.find(k => k === e.target.value); if (next) work.chooseObjective(next);
        }}>{COMPARISON_OBJECTIVES.map(k => <option value={k} key={k}>{objectives[k].label}</option>)}</select>
      </label>
      {menu && <>
        <p className="jp-hint">{scope(menu)} sur {menu.search.scope_size !== undefined ? `les ${lineCount(menu.search.scope_size)} du catalogue` : "le catalogue"} de midi.</p>
        {menu.reference.metrics?.admission_queue_at_16 !== undefined && <p className="jp-hint">À l’échelle de l’établissement, le classement maintient au moins les admissions prévues et plafonne les réorientations au niveau de référence. Chaque dossier identifié prévu d’ici 16 h doit être servi à l’heure prévue ou plus tôt.</p>}
        <PlanChoice menu={menu} objective={objective} activeId={draft ? null : suggested?.id ?? null}
          onPick={work.selectPlan} disabled={locked} group="Plans proposés par le simulateur" />
        <div className="jp-tools">
          {!draft && suggested && <button type="button" className="btn" disabled={disabled} onClick={()=>work.setIds(suggested.action_ids)}>Modifier les actions</button>}
          {!!menu.example_action_ids?.length && <button type="button" className="wm-jump" disabled={disabled} onClick={work.tryExample}>
            Essayer le plan à {menu.example_action_ids.length} actions</button>}
          {plan && <button type="button" className="wm-jump jp-mobile-shortcut" aria-controls={detailsId}
            onClick={()=>document.getElementById(detailsId)?.focus()}>Voir le plan à valider</button>}
        </div>
      </>}
    </section>}
    {!menu && (work.menuError ? <div className="wm-problem"><p role="alert"><Alert />{work.menuError}</p>
      <button className="btn btn--small" type="button" onClick={work.retry}><Refresh /> Réessayer les plans</button></div>
      : <p className="wm-loading" role="status"><span aria-hidden="true" />Calcul des plans du simulateur…</p>)}
    {draft && planning && menu && <>
      <Editor menu={menu} ids={draft.ids} setIds={work.setIds} locked={locked} working={work.working}
        evaluate={()=>void work.calculate("preview")} optimize={()=>void work.calculate("optimize")} />
      {work.subsets && <section className="wm-card jp-card" aria-label="Sous-plans du brouillon">
        <p className="wm-eyebrow">À partir de votre sélection</p><h2>Sous-plans comparés</h2><p className="jp-hint">{scope(work.subsets)} sur les {lineCount(draft.ids.length)} du brouillon.</p>
        <PlanChoice menu={work.subsets} objective={objective} activeId={work.subsetId} disabled={disabled}
          onPick={work.setSubset} group="Sous-plans évalués" />
        <button className="wm-jump" type="button" disabled={!work.subsetId || disabled} onClick={()=>work.setSubset(null)}>Revenir au brouillon complet</button>
      </section>}
    </>}
    {work.error && <p role="alert" className="jp-conflicts"><Alert /> {work.error}</p>}
    {session.phase === "review" && session.plan_report && session.observation && <Reading session={session} actions={actions} />}
    <section id={detailsId} tabIndex={-1} className="wm-card jp-card jp-summary" aria-label={saved ? "Plan composé validé" : "Plan à valider"}>
      <p className="wm-eyebrow">{saved ? "Décision enregistrée à midi" : draft ? subsidiary ? "Sous-plan sélectionné" : "Votre composition" : "Plan sélectionné"}</p>
      <h2>{saved ? "Plan validé en simulation" : "Composition à valider"}</h2>
      <p className="jp-hint">{objectives[objective].label}</p>
      {plan ? <>
        <div className="jp-summary__numbers"><strong>{lineCount(plan.action_ids.length)}</strong><span>{n(plan.cost_eur)} €{menu && <> sur {n(menu.budget_eur)} €</>}</span></div>
        {plan.metrics && <p className="jp-total">{objectives[objective].column} · <strong>{n(score(plan.metrics, objective))} {objectives[objective].unit}</strong>
          {menu?.reference.metrics && <> · référence {n(score(menu.reference.metrics, objective))}</>}</p>}
        {plan.metrics?.redirected_patients != null && plan.metrics.admission_queue_at_16 != null && <p className="jp-total">Réorientations prévues · {n(plan.metrics.redirected_patients)}<br/>
          File d’admission prévue à 16 h · {n(plan.metrics.admission_queue_at_16)} patients</p>}
        {!!plan.access_warnings?.length && <div role="alert" className="jp-conflicts"><strong>Compromis prévu sur l’accès aux soins</strong>
          <ul>{plan.access_warnings.map((message,i)=><li key={i}>{message}</li>)}</ul></div>}
        {plan.metrics && <button type="button" className="wm-jump" aria-controls={impactId}
          onClick={()=>document.getElementById(impactId)?.focus()}>Comparer les impacts sur les ressources</button>}
        <ActionList plan={plan} actions={actions} actual={session.plan_report?.realized} />
        {plan.case_hours && <CaseTimes plan={plan.case_hours} reference={menu?.reference.case_hours} actual={session.plan_report?.case_hours} />}
        {!plan.feasible && <div role="alert" className="jp-conflicts"><strong>Conflit dans la composition</strong>
          {plan.conflicts.length ? <ul>{plan.conflicts.map((c,i) => <li key={i}>{c}</li>)}</ul> : <p>Cette combinaison est indisponible à midi.</p>}</div>}
      </> : draft && <p className="jp-hint">Brouillon de {lineCount(displayedIds.length)}. Évaluez la composition pour connaître ses effets et vérifier ses contraintes.</p>}
      {planning && <button className="btn btn--primary jp-confirm" type="button" disabled={!canConfirm}
        onClick={() => { if (canConfirm && plan) void onConfirm(plan.action_ids, objective, subsidiary ? draft?.ids : undefined); }}><Check />{busy === "confirm" ? "Validation…" : "Valider le plan en simulation"}</button>}
      {session.phase === "confirmed" && <button type="button" className="btn btn--primary jp-confirm" disabled={locked} onClick={onAdvance}><Clock /> Avancer à 16 h</button>}
      {session.phase === "awaiting_report" && <div className="jp-delay"><h3>Le relevé de 16 h est en attente</h3><p>Publication prévue à {time(session.publication_hour)}.</p>
        <button type="button" className="btn btn--primary" disabled={locked} onClick={onAdvance}>Avancer à {time(session.publication_hour)}</button></div>}
    </section>
    <WorldJournal session={session} actions={actions} />
    {saved && session.plan_snapshot && menu && <details className="wm-card jp-card jp-disclosure jp-archived">
      <summary>Comparaison archivée à midi</summary>
      <p className="jp-hint">{scope(menu)}{menu.search.scope_size !== undefined && <> sur {lineCount(menu.search.scope_size)}</>}.</p>
      {!!menu.scope_ids?.length && <details className="jp-disclosure"><summary>Interventions du périmètre comparé ({menu.scope_ids.length})</summary>
        <ul className="jp-action-list">{menu.scope_ids.map(id=><li key={id}>{actions.find(a=>a.id===id)?.label ?? id}</li>)}</ul>
      </details>}
      <ul className="jp-action-list">{offers(menu).map((p,i)=><li key={p.id}><strong>{title(p,menu,i)}</strong>
        <small>{p.action_ids.length ? actionNames(p.action_ids,actions) : "Aucune intervention ajoutée"}</small>
        <small>{p.metrics && <>{n(score(p.metrics,objective))} {objectives[objective].unit} · </>}{n(p.cost_eur)} €</small></li>)}</ul>
    </details>}
  </div><aside className="jp-side" aria-label="Effets et repères du plan">
    {plan && <ImpactTable plan={plan} reference={menu?.reference} actual={actual} wards={session.wards} id={impactId} returnId={planning ? detailsId : undefined} />}
    <ContextCards session={session} />
  </aside></div>;
}
