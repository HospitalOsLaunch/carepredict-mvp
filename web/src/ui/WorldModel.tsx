import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { worldApi, type Flow, type WmCatalogue, type WmContext, type WmOption, type WmSession } from "../api/worldModel";
import { remember, remembered, useWorldSession, worldError } from "../data/worldModel";
import { Alert, BookIcon, Check, Clock, Info, Refresh, SimulationIcon } from "./icons";
import "../styles/worldModel.css";

const flowName: Record<Flow, string> = { full: "Flux complet", partial: "Flux partiel", delayed: "Flux retardé" };
const numeric = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 });
const signed = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2, signDisplay: "exceptZero" });
const n = (x: number) => numeric.format(x);
const time = (x: number) => `${x} h`;
const statusName: Record<WmSession["phase"], string> = {
  planning: "Décision à prendre", confirmed: "Affectation validée en simulation",
  awaiting_report: "Relevé en attente", review: "Relevé publié",
};
const journalName = {
  opened: "Parcours ouvert", confirmed: "Choix validé en simulation",
  awaiting_report: "Relevé de 16 h encore en attente", report_received: "Relevé de 16 h publié",
};

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
        <h1>Simuler une affectation</h1>
        <p>Comparez les options de midi pour la file de patients en attente de transfert à 16 h.</p>
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

function Clockline({ session }: { session: WmSession }) {
  const step = session.phase === "planning" || session.phase === "confirmed" ? 1 : 2;
  return <ol className="wm-clockline" aria-label="Chronologie du parcours">
    {[
      { at: 8, label: "Planning de référence" },
      { at: session.decision_hour, label: "Décision simulée" },
      { at: session.target_hour, label: session.phase === "awaiting_report" ? "Relevé attendu" : "Relevé de la file" },
    ].map((point, i) => <li key={point.at} className={i === step ? "is-now" : i < step ? "is-past" : ""} aria-current={i === step ? "step" : undefined}>
      <span className="wm-clockline__dot" aria-hidden="true">{i < step ? <Check size={14} /> : <Clock size={15} />}</span>
      <span><strong>{time(point.at)}</strong><span>{point.label}</span></span>
    </li>)}
  </ol>;
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
    {run.state ? <Journey key={run.state.id} session={run.state} locked={!!run.busy || !!run.error}
      busy={run.busy} onConfirm={run.confirm} onAdvance={run.advance} /> :
      !run.error && <Loading>Chargement du planning de cet établissement…</Loading>}
  </>;
}

function Journey({ session, locked, busy, onConfirm, onAdvance }: {
  session: WmSession; locked: boolean; busy: string | null; onConfirm: (id: string) => Promise<void>; onAdvance: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  const reference = session.options.find((o) => o.id === session.reference_id)!;
  const selected = session.options.find((o) => o.id === (session.selected_id ?? draft));
  const isPlanning = session.phase === "planning";
  const stateId = useId();
  const minima = (["transport", "cleaning"] as const).flatMap((kind) => {
    const ranked = session.options.filter((o) => o.kind === kind).sort((a, b) => a.forecast - b.forecast);
    return ranked.length ? [ranked[0]!] : [];
  });
  const featured = [reference, ...minima];
  const extras = session.options.filter((o) => !featured.some((f) => f.id === o.id));
  const extraSelected = selected && extras.some((o) => o.id === selected.id);
  const summary = extraSelected && !expanded ? [...featured, selected] : featured;
  const hiddenCount = session.options.length - summary.length;

  function optionRow(o: WmOption) {
    const match = selected?.id === o.id;
    const forecastId = stateId + "-forecast-" + o.id;
    const subtitle = o.kind === "reference" ? "Planning horaire de midi" :
      minima.some((m) => m.id === o.id) ? "File estimée la plus basse de cette famille" : null;
    return <label className={`wm-option${match ? " is-selected" : ""}`} key={o.id}>
      <input type="radio" name={stateId} value={o.id} checked={match}
        onChange={() => setDraft(o.id)} aria-label={o.label} aria-describedby={forecastId} />
      <span className="wm-option__name"><strong>{o.label}</strong>{subtitle && <small>{subtitle}</small>}</span>
      <strong id={forecastId} className="wm-option__count">{n(o.forecast)}<span className="visually-hidden"> patients à 16 h</span></strong>
    </label>;
  }

  return <>
    <Clockline session={session} />
    <div className="wm-phase" role="status">
      <span className="wm-status"><i aria-hidden="true" />{statusName[session.phase]}</span>
      <span>Horloge simulée <strong>{time(session.hour)}</strong></span>
      {busy === "load" && <span>Actualisation…</span>}
    </div>
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
          <p className="wm-intro">Le modèle d’état (SSM) estime la file totale en équivalents patients.</p>
          <fieldset className="wm-options" disabled={locked || !isPlanning}>
            <legend className="visually-hidden">Affectation à simuler à midi</legend>
            <div className="wm-option-head" aria-hidden="true"><span>Affectation</span><span>File à 16 h</span></div>
            {summary.map(optionRow)}
          </fieldset>
          {extras.length > 0 && <button className="wm-more" ref={toggle} type="button"
            aria-expanded={expanded} aria-controls={stateId + "-more"} onClick={() => setExpanded(!expanded)}>
            {expanded ? "Masquer les autres affectations" : hiddenCount ? `Voir les autres affectations (${hiddenCount})` : "Afficher la liste complète"}
          </button>}
          {isPlanning ? <div className="wm-decision">
            <p>{selected ? <><strong>{selected.label}</strong><br />{n(selected.forecast)} patients estimés à 16 h · référence {n(reference.forecast)}</> : "Sélectionnez une affectation pour la valider en simulation."}</p>
            <button type="button" className="btn btn--primary" disabled={!selected || locked}
              onClick={() => selected && onConfirm(selected.id)}><Check />{busy === "confirm" ? "Validation…" : "Valider en simulation"}</button>
          </div> : session.phase === "confirmed" && <div className="wm-decision">
            <p><strong>{selected?.label}</strong><br />Affectation validée pour ce parcours.</p>
            <button type="button" className="btn btn--primary" disabled={locked} onClick={onAdvance}>
              <Clock /> {busy === "advance" ? "Avancement…" : "Avancer à 16 h"}</button>
          </div>}
          {extras.length > 0 && <div hidden={!expanded} id={stateId + "-more"} className="wm-extra">
            {expanded && <>
              <fieldset className="wm-options" disabled={locked || !isPlanning}>
                <legend>Autres affectations</legend>
                {extras.map(optionRow)}
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
        <Journal session={session} />
      </div>
      <aside className="wm-aside" aria-label="Repères du parcours">
        <Projection session={session} option={selected ?? reference} reference={reference} />
        <section className="wm-card wm-side-card">
          <div className="wm-side-head"><Clock /><h2>Planning de 8 h</h2></div>
          {session.morning_plan.length ? <ul className="wm-plan">{session.morning_plan.map((item, i) => <li key={i}>{item}</li>)}</ul> :
            <p>Aucune affectation inscrite au planning de référence.</p>}
        </section>
        <section className="wm-card wm-side-card">
          <div className="wm-side-head"><Info /><h2>Disponibilité des données</h2></div>
          <p>{session.context.feed === "full" ? "Les deux composantes de la file sont attendues pour chaque unité." :
            session.context.feed === "partial" ? "Certains relevés d’unité peuvent rester incomplets. La file totale exige les deux composantes de chaque unité." :
            `La file est mesurée à 16 h. Dans ce contexte, le relevé est publié à ${time(session.publication_hour)}.`}</p>
          <p className="wm-model-version">Version du modèle <span>{session.model_version}</span></p>
        </section>
      </aside>
    </div>
  </>;
}

function Projection({ session, option, reference }: { session: WmSession; option: WmOption; reference: WmOption }) {
  const diff = option.forecast - reference.forecast;
  return <section className="wm-card wm-projection" aria-label="Détail de la projection à midi">
    <div className="wm-projection__head"><p className="wm-eyebrow">Estimation à midi</p><h2>File attendue à 16 h</h2></div>
    <div className="wm-projection__value"><strong>{n(option.forecast)}</strong><span>patients</span></div>
    <p className="wm-projection__option">{option.label}</p>
    {option.id !== reference.id && <p className="wm-delta">{signed.format(diff)} patient{Math.abs(diff) > 1 ? "s" : ""} par rapport à la référence de {n(reference.forecast)}</p>}
    <details className="wm-details"><summary>Détail par unité</summary>
      <table><thead><tr><th>Unité</th><th>Référence</th><th>Option</th></tr></thead>
        <tbody>{session.wards.map((w, i) => <tr key={w.id}><th scope="row">{w.label}</th><td>{n(reference.by_ward[i]!)}</td><td>{n(option.by_ward[i]!)}</td></tr>)}</tbody>
      </table>
    </details>
    <details className="wm-details"><summary>Projection secondaire JEPA</summary><p>Pour cette affectation, JEPA prévoyait <strong>{n(option.jepa_forecast)} patients</strong> à 16 h.</p></details>
  </section>;
}

function Observed({ session, selected }: { session: WmSession; selected: WmOption }) {
  const alternatives = session.options.filter((o) => o.id !== selected.id);
  const [other, setOther] = useState(alternatives.find((o) => o.id === session.reference_id)?.id ?? alternatives[0]?.id);
  const option = alternatives.find((o) => o.id === other);
  const reading = session.observation!;
  const out = (value: number | null | undefined) => value == null ? "Non renseignée" : n(value);
  return <section className="wm-card" aria-label="Comparaison après relevé">
    <div className="wm-card-head"><div><p className="wm-eyebrow">Relevé publié à {time(reading.published_hour)}</p><h2>La file observée à 16 h</h2></div><Check size={20} /></div>
    <div className="wm-results">
      <div><span className="wm-eyebrow">Observée en simulation</span><strong>{out(reading.observed_stock)}</strong><small>{selected.label}</small></div>
      <div><span className="wm-eyebrow">Autre option estimée</span><strong>{out(option?.reconstruction)}</strong><small>{option?.label ?? "Aucune autre option"}</small></div>
    </div>
    <p className="wm-coverage">{reading.visible_components} composantes du relevé publiées sur {reading.total_components}. {reading.observed_stock === null ? "Le total observé reste inconnu." : "Les flux simulés sont exprimés en équivalents patients."}</p>
    {option && <label className="wm-alt">Estimer la file avec une autre affectation
      <select className="select" value={option.id} onChange={(e) => setOther(e.target.value)}>
        {alternatives.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </label>}
    <p className="wm-intro">Le modèle utilise les composantes publiées pour estimer la file de l’autre affectation.</p>
    <div className="wm-table-wrap"><table className="wm-reading"><caption className="visually-hidden">File de transfert à 16 h par unité, en patients</caption>
      <thead><tr><th scope="col">Unité</th><th scope="col">Observée</th><th scope="col">Autre option estimée</th></tr></thead>
      <tbody>{session.wards.map((w,i) => <tr key={w.id}><th scope="row">{w.label}</th><td>{out(reading.by_ward[i])}</td><td>{out(option?.reconstructed_by_ward?.[i])}</td></tr>)}</tbody>
    </table></div>
  </section>;
}

function Journal({ session }: { session: WmSession }) {
  return <section className="wm-card wm-journal" aria-label="Journal du parcours">
    <div className="wm-side-head"><BookIcon /><h2>Journal du parcours</h2></div>
    <ol>{session.journal.map((entry,i) => {
      const option = session.options.find((o) => o.id === entry.option_id);
      return <li key={i}><span className="wm-journal__at">{time(entry.hour)}</span><span><strong>{journalName[entry.event]}</strong>{option && <small>{option.label}</small>}</span></li>;
    })}</ol>
  </section>;
}
