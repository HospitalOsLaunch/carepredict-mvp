import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { canConfirm, COMPARISON_OBJECTIVES, RESOURCE_FAMILIES, RESOURCE_INDICATORS, worldApi, type ComparisonObjective, type ResourceFamily, type Flow, type WmCatalogue, type WmContext, type WmOption, type WmSession } from "../api/worldModel";
import { remember, remembered, useWorldSession, worldError } from "../data/worldModel";
import { familyName, indicatorName, objectives, n, signed, time } from "../domain/worldModel";
import { Alert, Check, Clock, Refresh, SimulationIcon } from "./icons";
import { ContextCards, JourneyClock, WorldJournal } from "./WorldJourney";
import { ComposedPlans } from "./ComposedPlans";
import "../styles/worldModel.css";

const flowName: Record<Flow, string> = { full: "Flux complet", partial: "Flux partiel", delayed: "Flux retardé" };
function objectiveValue(option: WmOption, objective: ComparisonObjective): number | null {
  if (objective === "transfer_queue") return option.forecast;
  if (objective === "bed_wait") return option.bed_wait_patient_hours ?? null;
  const ide = option.uncovered_ide_minutes;
  const as = option.uncovered_as_minutes;
  return ide == null || as == null ? null : ide + as;
}

function bestMeasured(options: WmOption[], objective: ComparisonObjective): WmOption | undefined {
  let best: WmOption | undefined;
  let minimum = Infinity;
  for (const option of options) {
    const value = objectiveValue(option, objective);
    if (value === null) continue;
    const cheaperTie = value === minimum && (option.cost_eur ?? Infinity) < (best?.cost_eur ?? Infinity);
    if (value < minimum || cheaperTie) {
      best = option;
      minimum = value;
    }
  }
  return best;
}

function Loading({ children }: { children: ReactNode }) {
  return <p className="wm-loading" role="status"><span aria-hidden="true" />{children}</p>;
}

function Problem({ text, onRetry, disabled }: { text: string; onRetry: () => void; disabled?: boolean }) {
  return <div className="wm-problem">
    <p role="alert"><Alert /><span>{text}</span></p>
    <button className="btn btn--small" type="button" onClick={onRetry} disabled={disabled}><Refresh /> Réessayer</button>
  </div>;
}

export function WorldModel() {
  const [catalogue, setCatalogue] = useState<WmCatalogue | null>(null);
  const [id, setId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, retry] = useState(0);
  useEffect(() => {
    const ctrl = new AbortController();
    setError(null);
    worldApi.contexts(ctrl.signal).then((result) => {
      if (ctrl.signal.aborted) return;
      const saved = remembered("active-context");
      setCatalogue(result);
      setId(result.contexts.find((c) => c.id === saved)?.id ?? result.contexts[0]!.id);
    }).catch((e: unknown) => {
      if (!ctrl.signal.aborted) setError(e instanceof ApiError && e.status === 404 ? "Le service de simulation est indisponible." : worldError(e));
    });
    return () => ctrl.abort();
  }, [attempt]);
  const context = catalogue?.contexts.find((c) => c.id === id);

  return <div className="wm">
    <header className="wm-heading">
      <div>
        <div className="wm-kicker"><SimulationIcon size={17} /> World model <span aria-hidden="true">/</span> Hôpital synthétique</div>
        <h1>Simuler le plan de midi</h1>
        <p>Comparez à midi les effets des affectations sur les soins, les lits et les transferts jusqu’à 16 h.</p>
      </div>
      {catalogue && context && <label className="wm-context">Contexte synthétique
        <select className="select" value={id ?? ""} onChange={(e) => {
          remember("active-context", e.target.value);
          setId(e.target.value);
        }}>
          {catalogue.contexts.map((c) => <option key={c.id} value={c.id}>{c.label} · {flowName[c.feed]}</option>)}
        </select>
      </label>}
    </header>
    {error ? <Problem text={error} onRetry={() => retry((v) => v + 1)} /> :
      context ? <Workspace key={context.id} context={context} /> : <Loading>Chargement des contextes de simulation…</Loading>}
  </div>;
}

function Workspace({ context }: { context: WmContext }) {
  const run = useWorldSession(context.id);
  return <>
    <div className="wm-tools">
      <div className="wm-source"><span className={`wm-flow wm-flow--${context.feed}`}><i aria-hidden="true" />{flowName[context.feed]}</span>
        <span>{context.ward_count} unités</span>
      </div>
      <div className="wm-tool-actions">
        <button className="wm-plain" type="button" onClick={run.reload} disabled={!!run.busy}><Refresh size={14} /> Actualiser</button>
        <button className="wm-plain" type="button" onClick={run.restart} disabled={!!run.busy}>Nouveau parcours</button>
      </div>
    </div>
    {run.error && <Problem text={run.error} onRetry={run.reload} disabled={!!run.busy} />}
    {run.state ? <Modes key={run.state.id} session={run.state} run={run} /> :
      !run.error && <Loading>Chargement du planning de cet établissement…</Loading>}
  </>;
}

function Modes({ session, run }: { session: WmSession; run: ReturnType<typeof useWorldSession> }) {
  const [single, setSingle] = useState(false);
  const planning = session.phase === "planning";
  const composed = planning ? Boolean(session.plan_version) && !single : Boolean(session.confirmed_plan);
  const locked = Boolean(run.busy || run.error);
  return <>
    <JourneyClock session={session} busy={run.busy} />
    {planning && session.plan_version && <div className="jp-modes" role="group" aria-label="Mode de décision">
      <button type="button" aria-pressed={composed} disabled={locked} onClick={() => setSingle(false)}>Plan composé</button>
      <button type="button" aria-pressed={!composed} disabled={locked} onClick={() => setSingle(true)}>Action unique</button>
    </div>}
    {composed
      ? <ComposedPlans session={session} locked={locked} busy={run.busy} onConfirm={run.confirmPlan} onAdvance={run.advance} />
      : <Journey session={session} locked={locked} busy={run.busy} onConfirm={run.confirm} onAdvance={run.advance} />}
  </>;
}

function Journey({ session, locked, busy, onConfirm, onAdvance }: {
  session: WmSession; locked: boolean; busy: string | null; onConfirm: (id: string, objective: ComparisonObjective) => Promise<void>; onAdvance: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [family, setFamily] = useState<ResourceFamily | "all">("all");
  const [requestedObjective, setObjective] = useState<ComparisonObjective>(session.decision_objective ?? "transfer_queue");
  const toggle = useRef<HTMLButtonElement>(null);
  const reference = session.options.find((o) => o.id === session.reference_id)!;
  const isPlanning = session.phase === "planning";
  const selected = session.options.find((o) => o.id === (session.selected_id ?? draft) && (!isPlanning || canConfirm(o)));
  const stateId = useId();
  const detailId = stateId + "-detail";
  const confirmId = stateId + "-confirm";
  const recorded = session.decision_objective;
  const availableObjectives = COMPARISON_OBJECTIVES.filter((key) => key === "transfer_queue" || key === recorded ||
    session.options.some((o) => o.kind !== "reference" && canConfirm(o) && objectiveValue(o, key) !== null));
  const preferred = isPlanning ? requestedObjective : recorded ?? "transfer_queue";
  const comparison = availableObjectives.includes(preferred) ? preferred : "transfer_queue";
  const objective = objectives[comparison];
  const formatScore = (option: WmOption) => {
    const value = objectiveValue(option, comparison);
    return value === null ? "Non renseigné" : n(value) + " " + objective.unit;
  };
  const featured = [reference];
  for (const kind of RESOURCE_FAMILIES) {
    const candidates = session.options.filter((o) => o.kind === kind);
    const eligible = candidates.filter(canConfirm);
    // An unmeasured or unavailable family remains inspectable, without claiming an optimum.
    const representative = bestMeasured(eligible, comparison) ?? eligible[0] ?? candidates[0];
    if (representative) featured.push(representative);
  }
  const extras = session.options.filter((o) => !featured.some((f) => f.id === o.id));
  const filters = RESOURCE_FAMILIES.filter((kind) => extras.some((o) => o.kind === kind));
  const activeFamily = family !== "all" && filters.includes(family) ? family : "all";
  const visibleExtras = extras.filter((o) => activeFamily === "all" || o.kind === activeFamily);
  const outsideFeatured = selected && extras.some((o) => o.id === selected.id);
  const pinSelection = outsideFeatured && (!expanded || !visibleExtras.some((o) => o.id === selected.id));
  const summary = pinSelection ? [...featured, selected] : featured;
  const hiddenCount = session.options.length - summary.length;

  function optionRow(o: WmOption) {
    const match = selected?.id === o.id;
    const available = canConfirm(o);
    const countsId = stateId + "-forecast-" + o.id;
    const noteId = stateId + "-note-" + o.id;
    const familyLabel = o.kind === "reference" ? "Planning horaire de midi" : familyName[o.kind];
    const value = objectiveValue(o, comparison);
    const note = available ? familyLabel : `${familyLabel} · Indisponible à midi`;
    return <label className={`wm-option${match ? " is-selected" : ""}${available ? "" : " is-unavailable"}`} key={o.id}>
      <input type="radio" name={stateId} value={o.id} checked={match} disabled={!available}
        onChange={() => { if (available) setDraft(o.id); }} aria-label={o.label} aria-describedby={noteId + " " + countsId} />
      <span className="wm-option__name"><strong>{o.label}</strong><small id={noteId}>
        {note}{!available && o.constraint && <span className="wm-limit">{o.constraint}</span>}
      </small></span>
      <strong id={countsId} className={`wm-option__count${value === null ? " wm-option__unknown" : ""}`}>
        {!available ? <><span aria-hidden="true">—</span><span className="visually-hidden">Option non réalisable</span></> :
          value === null ? "Non renseigné" : <>{n(value)}<span className="visually-hidden"> {objective.unit} · {objective.label}</span></>}
      </strong>
    </label>;
  }

  return <>
    <div className="wm-layout">
      <div className="wm-primary">
        {session.phase === "review" && selected && <Observed session={session} selected={selected} />}
        {session.phase === "awaiting_report" && <section className="wm-card wm-waiting" aria-label="Délai de publication">
          <Clock size={22} /><div><h2>Le relevé de 16 h est en attente</h2>
            <p>Sa publication est prévue à {time(session.publication_hour)} dans ce contexte.</p>
            <button className="btn btn--primary" type="button" disabled={locked} onClick={onAdvance}>
              {busy === "advance" ? "Publication…" : `Avancer à ${time(session.publication_hour)}`}</button>
          </div>
        </section>}
        {session.phase !== "review" && <section className="wm-card" aria-labelledby={stateId}>
          <div className="wm-card-head">
            <div><p className="wm-eyebrow">Projection à midi</p><h2 id={stateId}>Comparer les affectations</h2></div>
            <span className="wm-time-chip"><Clock size={14} /> Cible 16 h</span>
          </div>
          {availableObjectives.length > 1 && <label className="wm-alt wm-objective">Critère de comparaison à midi
            <select className="select" value={comparison} disabled={!isPlanning || locked} onChange={(event) => {
              if (!isPlanning || locked) return;
              const next = availableObjectives.find((key) => key === event.target.value);
              if (next) { setObjective(next); setExpanded(false); }
            }}>
              {availableObjectives.map((key) => <option key={key} value={key}>{objectives[key].label}</option>)}
            </select>
          </label>}
          <p className="wm-intro">{objective.description} Pour chaque famille, le minimum disponible parmi les options réalisables apparaît en premier. À égalité, le coût renseigné le plus bas est prioritaire.</p>
          <fieldset className="wm-options" disabled={locked || !isPlanning}>
            <legend className="visually-hidden">Affectation à simuler à midi</legend>
            <div className="wm-option-head" aria-hidden="true"><span>Affectation</span><span className="wm-column-score">{objective.column}<small>{objective.unit}</small></span></div>
            {summary.map(optionRow)}
          </fieldset>
          {extras.length > 0 && <button className="wm-more" ref={toggle} type="button"
            aria-expanded={expanded} aria-controls={stateId + "-more"} onClick={() => setExpanded(!expanded)}>
            {expanded ? "Masquer les autres affectations" : hiddenCount ? `Voir les autres affectations (${hiddenCount})` : "Afficher la liste complète"}
          </button>}
          {isPlanning ? <div className="wm-decision">
            <div className="wm-choice">
              <p>{selected ? <><strong>{selected.label}</strong><br />{objective.column} · {formatScore(selected)}<br />Référence · {formatScore(reference)}</> : "Sélectionnez une affectation pour la valider en simulation."}</p>
              {selected?.constraint && <p className="wm-rule">{selected.constraint}</p>}
              {selected && <button type="button" className="wm-jump" aria-controls={detailId}
                onClick={() => document.getElementById(detailId)?.focus()}>Voir les effets estimés</button>}
            </div>
            <button id={confirmId} type="button" className="btn btn--primary" disabled={!selected || locked}
              onClick={() => selected && onConfirm(selected.id, comparison)}><Check />{busy === "confirm" ? "Validation…" : "Valider en simulation"}</button>
          </div> : session.phase === "confirmed" && <div className="wm-decision">
            <p><strong>{selected?.label}</strong><br />Affectation validée pour ce parcours.</p>
            <button type="button" className="btn btn--primary" disabled={locked} onClick={onAdvance}>
              <Clock /> {busy === "advance" ? "Avancement…" : "Avancer à 16 h"}</button>
          </div>}
          {extras.length > 0 && <div hidden={!expanded} id={stateId + "-more"} className="wm-extra">
            {expanded && <>
              {filters.length > 1 && <label className="wm-alt wm-filter">Famille de ressources
                <select className="select" value={activeFamily}
                  onChange={(e) => setFamily(RESOURCE_FAMILIES.find((kind) => kind === e.target.value) ?? "all")}>
                  <option value="all">Toutes les familles</option>
                  {filters.map((kind) => <option key={kind} value={kind}>{familyName[kind]}</option>)}
                </select>
              </label>}
              <fieldset className="wm-options" disabled={locked || !isPlanning}>
                <legend>Autres affectations</legend>
                {visibleExtras.map(optionRow)}
              </fieldset>
              <button type="button" className="wm-more" onClick={() => {
                setExpanded(false);
                toggle.current?.focus();
              }}>Revenir au choix affiché</button>
            </>}
          </div>}
        </section>}
        {isPlanning && <div className="wm-next">
          <button className="btn btn--small" type="button" disabled><Clock /> Avancer à 16 h</button>
          <span>Disponible après validation.</span>
        </div>}
        <WorldJournal session={session} />
      </div>
      <aside className="wm-aside" aria-label="Repères du parcours">
        <Projection session={session} option={selected ?? reference} reference={reference} id={detailId}
          confirmId={isPlanning && selected ? confirmId : undefined} />
        <ContextCards session={session} />
      </aside>
    </div>
  </>;
}

function Projection({ session, option, reference, id, confirmId }: {
  session: WmSession; option: WmOption; reference: WmOption; id: string; confirmId?: string;
}) {
  const diff = option.forecast - reference.forecast;
  const selectedReference = option.id === reference.id;
  const metrics = RESOURCE_INDICATORS.filter((key) => option[key] != null || reference[key] != null);
  const reading = (value: number | null | undefined) => value == null ? "Non renseigné" : n(value);
  return <section className="wm-card wm-projection" aria-label="Détail de la projection à midi" id={id} tabIndex={-1}>
    <div className="wm-projection__head"><p className="wm-eyebrow">Estimation à midi</p><h2>File attendue à 16 h</h2></div>
    <div className="wm-projection__value"><strong>{n(option.forecast)}</strong><span>patients</span></div>
    <p className="wm-projection__option">{option.label}</p>
    {option.id !== reference.id && <p className="wm-delta">{signed.format(diff)} patient{Math.abs(diff) > 1 ? "s" : ""} par rapport à la référence de {n(reference.forecast)}</p>}
    {option.constraint && <p className="wm-projection__rule"><strong>Conditions à midi</strong> {option.constraint}</p>}
    {metrics.length > 0 && <div className="wm-effects">
      <h3>Effets estimés pour l’établissement</h3>
      {metrics.some((key) => key !== "cost_eur") && <p>Soins et attente cumulés de 12 h à 16 h.</p>}
      <table>
        <caption className="visually-hidden">Conséquences prévues à midi pour l’établissement</caption>
        <thead><tr><th scope="col">Indicateur</th><th scope="col">Référence</th>
          {!selectedReference && <th scope="col">Choix</th>}</tr></thead>
        <tbody>{metrics.map((key) => <tr key={key}><th scope="row">{indicatorName[key]}</th>
          <td>{reading(reference[key])}</td>{!selectedReference && <td>{reading(option[key])}</td>}</tr>)}</tbody>
      </table>
    </div>}
    <details className="wm-details"><summary>Détail par unité</summary>
      <table><thead><tr><th>Unité</th><th>Référence</th><th>Option</th></tr></thead>
        <tbody>{session.wards.map((w, i) => <tr key={w.id}><th scope="row">{w.label}</th><td>{n(reference.by_ward[i]!)}</td><td>{n(option.by_ward[i]!)}</td></tr>)}</tbody>
      </table>
    </details>
    <details className="wm-details"><summary>Projection secondaire JEPA</summary>
      {option.jepa_forecast === null
        ? <p>Projection JEPA indisponible pour cette affectation.</p>
        : <p>Pour cette affectation, JEPA prévoyait <strong>{n(option.jepa_forecast)} patients</strong> à 16 h.</p>}
    </details>
    {confirmId && <button className="wm-jump wm-jump--back" type="button"
      onClick={() => document.getElementById(confirmId)?.focus()}>Revenir à la validation</button>}
  </section>;
}

function Observed({ session, selected }: { session: WmSession; selected: WmOption }) {
  const alternatives = session.options.filter((o) => o.id !== selected.id);
  const feasible = alternatives.filter(canConfirm);
  const initialAlternative = feasible.find((o) => o.id === session.reference_id) ?? feasible[0];
  const [other, setOther] = useState(initialAlternative?.id);
  const option = feasible.find((o) => o.id === other) ?? initialAlternative;
  const reading = session.observation!;
  const out = (value: number | null | undefined) => value == null ? "Non renseignée" : n(value);
  return <section className="wm-card" aria-label="Comparaison après relevé">
    <div className="wm-card-head"><div><p className="wm-eyebrow">Relevé publié à {time(reading.published_hour)}</p><h2>La file observée à 16 h</h2></div><Check size={20} /></div>
    <div className="wm-results">
      <div><span className="wm-eyebrow">Observée en simulation</span><strong>{out(reading.observed_stock)}</strong><small>{selected.label}</small></div>
      <div><span className="wm-eyebrow">Autre option estimée</span><strong>{option ? out(option.reconstruction) : "—"}</strong><small>{option?.label ?? "Aucune autre affectation réalisable à midi"}</small></div>
    </div>
    <p className="wm-coverage">{reading.visible_components} composantes du relevé publiées sur {reading.total_components}. {reading.observed_stock === null ? "Le total observé reste inconnu." : "Les flux simulés sont exprimés en équivalents patients."}</p>
    {option && <label className="wm-alt">Estimer la file avec une autre affectation
      <select className="select" value={option.id} onChange={(e) => setOther(e.target.value)}>
        {alternatives.map((o) => <option key={o.id} value={o.id} disabled={!canConfirm(o)}>
          {o.label}{!canConfirm(o) && ` — Indisponible à midi${o.constraint ? " · " + o.constraint : ""}`}
        </option>)}
      </select>
    </label>}
    {!option && alternatives.length > 0 && <details className="wm-details">
      <summary>Affectations indisponibles à midi ({alternatives.length})</summary>
      <ul>{alternatives.map((o) => <li key={o.id}><strong>{o.label}</strong>{o.constraint && <> · {o.constraint}</>}</li>)}</ul>
    </details>}
    {option && <p className="wm-intro">Le modèle utilise les composantes publiées pour estimer la file de l’autre affectation.
      {option.constraint && <> <strong>Conditions de cette option à midi</strong> {option.constraint}</>}
    </p>}
    <div className="wm-table-wrap"><table className="wm-reading"><caption className="visually-hidden">File de transfert à 16 h par unité, en patients</caption>
      <thead><tr><th scope="col">Unité</th><th scope="col">Observée</th>{option && <th scope="col">Autre option estimée</th>}</tr></thead>
      <tbody>{session.wards.map((w,i) => <tr key={w.id}><th scope="row">{w.label}</th><td>{out(reading.by_ward[i])}</td>{option && <td>{out(option.reconstructed_by_ward?.[i])}</td>}</tr>)}</tbody>
    </table></div>
  </section>;
}
