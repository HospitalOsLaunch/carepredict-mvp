import { useEffect, useState } from "react";
import { worldApi, type WmCatalogue, type WmContext, type WmSession } from "../api/worldModel";
import { remember, remembered, useWorldSession } from "../data/worldModel";
import { objectives, time } from "../domain/worldModel";
import { BoardIcon, BookIcon, Mark, PulseIcon } from "./icons";
import { UnitDecision } from "./UnitDecision";
import "../styles/hospitalUnit.css";

type View = "unite" | "journal" | "donnees";
const sections = [
  { id: "unite", label: "Unité", href: "#/", Icon: BoardIcon },
  { id: "journal", label: "Journal", href: "#/journal", Icon: BookIcon },
  { id: "donnees", label: "Données", href: "#/donnees", Icon: PulseIcon },
] as const;
const feeds = { full: "Relevé complet", partial: "Relevé partiel", delayed: "Relevé différé" };
const events = {
  opened: "État de l’établissement chargé", confirmed: "Décision validée",
  awaiting_report: "Relevé en attente", report_received: "Relevé disponible",
};

function Navigation({ view, mobile }: { view: View; mobile?: boolean }) {
  return <nav className={mobile ? "tabbar unit-tabbar" : "nav"} aria-label="Sections">
    {sections.map(({ id, label, href, Icon }) => <a key={id} href={href} aria-current={id === view ? "page" : undefined}>
      {mobile && <span className="tabbar__icon"><Icon /></span>}{label}
    </a>)}
  </nav>;
}

export function HospitalUnit({ view }: { view: View }) {
  const [catalogue, setCatalogue] = useState<WmCatalogue | null>(null);
  const [contextId, chooseContext] = useState(() => remembered("unit-context"));
  const [failure, setFailure] = useState(false);
  const [attempt, retry] = useState(0);
  useEffect(() => {
    const ctrl = new AbortController();
    setFailure(false);
    worldApi.contexts(ctrl.signal).then(result => {
      if (!ctrl.signal.aborted) setCatalogue(result);
    }).catch(() => { if (!ctrl.signal.aborted) setFailure(true); });
    return () => ctrl.abort();
  }, [attempt]);
  const context = catalogue?.contexts.find(c => c.id === contextId) ?? catalogue?.contexts[0];
  const title = sections.find(s => s.id === view)!.label;
  useEffect(() => { document.title = title + " · HospitalOS"; }, [title]);
  return <div className="shell">
    <a href="#contenu" className="skip" onClick={e => { e.preventDefault(); document.getElementById("contenu")?.focus(); }}>Aller au contenu</a>
    <header className="topbar"><div className="topbar__row">
      <a href="#/" className="brand" aria-label="HospitalOS, vue unité"><Mark /><span>HospitalOS</span></a>
      <Navigation view={view} />
      <span className="unit-source">Données synthétiques</span>
    </div></header>
    <main className="main unit-workspace" id="contenu" tabIndex={-1}>
      <div className="unit-context-bar">
        <h1>{title}</h1>
        {catalogue && context && <label>Établissement
          <select className="select" value={context.id} onChange={e => {
            remember("unit-context", e.target.value); chooseContext(e.target.value);
          }}>{catalogue.contexts.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}</select>
        </label>}
      </div>
      {failure ? <div className="wm-card unit-information"><p role="alert">Le moteur de recommandation est indisponible. Reconnectez le cockpit pour charger les données de l’unité.</p>
        <button type="button" className="btn" onClick={() => retry(v => v + 1)}>Réessayer</button>
        <a href="#/dossiers" className="linkbtn">Ouvrir les dossiers patients de démonstration</a></div>
      : context ? <UnitWorkspace key={context.id} context={context} view={view} />
      : <p role="status">Chargement des établissements…</p>}
    </main>
    <Navigation view={view} mobile />
  </div>;
}

function UnitWorkspace({ context, view }: { context: WmContext; view: View }) {
  const work = useWorldSession(context.id, "unit");
  const [preferred, chooseWard] = useState(() => remembered("ward." + context.id) ?? (context.id === "rives" ? "u6" : null));
  const state = work.state;
  if (work.error) return <div className="wm-card unit-information"><p role="alert">{work.error}</p>
    <button className="btn" onClick={work.reload}>Réessayer</button>
    <button className="btn" onClick={work.restart}>Ouvrir un nouvel épisode de démonstration</button></div>;
  if (!state || state.context.id !== context.id) return <p role="status">Chargement de l’état de l’établissement…</p>;
  const ward = state.wards.find(w => w.id === preferred) ?? state.wards[0]!;
  return <>
    <div className="unit-context-bar unit-ward-bar">
      <label>Unité suivie<select className="select" value={ward.id} onChange={e => {
        remember("ward." + context.id, e.target.value); chooseWard(e.target.value);
      }}>{state.wards.map(w => <option key={w.id} value={w.id}>{w.label}</option>)}</select></label>
      <span>État de décision <strong>{time(state.decision_hour)}</strong></span>
    </div>
    <div hidden={view !== "unite"}>
      <UnitDecision key={state.id + ":" + ward.id} session={state} ward={ward} onConfirmed={work.recordDecision} />
    </div>
    {view === "unite" ? null : view === "journal" ? <DecisionJournal session={state} busy={Boolean(work.busy)} advance={() => void work.advance()} /> :
      <section className="wm-card unit-information"><h2>Données de {ward.label}</h2>
        <dl className="unit-facts"><div><dt>Établissement</dt><dd>{context.label}</dd></div>
        <div><dt>Lits équipés au planning</dt><dd>{ward.beds}</dd></div>
        <div><dt>Disponibilité du suivi</dt><dd>{feeds[context.feed]} · {time(state.publication_hour)}</dd></div>
        <div><dt>Version du moteur de plans</dt><dd>{state.plan_version ?? "Indisponible"}</dd></div></dl>
        <details><summary>Autres jeux de démonstration</summary>
          <p>Ces parcours utilisent leurs propres dossiers et ressources.</p>
          <a className="linkbtn" href="#/dossiers">Dossiers patients</a> <a className="linkbtn" href="#/plan">Plan à 24 h</a>
        </details>
        {state.phase !== "planning" && <button className="btn" disabled={Boolean(work.busy)} onClick={work.restart}>Ouvrir un nouvel épisode de démonstration</button>}
      </section>}
  </>;
}

function DecisionJournal({ session, busy, advance }: { session: WmSession; busy: boolean; advance: () => void }) {
  const plan = session.confirmed_plan;
  const ward = session.wards.find(w => w.id === session.decision_ward_id);
  const observed = ward && session.observation?.by_ward[session.wards.indexOf(ward)];
  return <section className="wm-card unit-information" aria-label="Journal des décisions">
    <h2>Décisions de {session.context.label}</h2>
    <ol className="unit-event-list">{session.journal.map((entry, index) => <li key={index}>
      <time>{time(entry.hour)}</time><div><strong>{events[entry.event]}</strong>
      {entry.event === "opened" && <p>{session.wards.length} unités suivies dans cet épisode.</p>}
      {entry.event === "confirmed" && <>
        <p>{ward?.label ?? session.context.label}{session.decision_objective && " · " + objectives[session.decision_objective].label}</p>
        {plan?.action_ids.length ? <ul>{plan.action_ids.map(id => {
          const act = session.plan_snapshot?.actions.find(a => a.id === id);
          return <li key={id}>{act ? act.label + " · " + act.quantity + " " + act.unit + " · " + time(act.start_hour) + "–" + time(act.end_hour) : id}</li>;
        })}</ul> : <p>{session.options.find(o => o.id === entry.option_id)?.label ?? "Maintenir le planning en cours"}</p>}
      </>}
      </div></li>)}</ol>
    {session.phase === "planning" && <a href="#/" className="linkbtn">Voir la recommandation de l’unité</a>}
    {(session.phase === "confirmed" || session.phase === "awaiting_report") && <button className="btn" disabled={busy} onClick={advance}>
      Consulter le relevé de démonstration de {time(session.hour === 12 ? 16 : session.publication_hour)}
    </button>}
    {session.observation && <p>{feeds[session.context.feed]} publié à {time(session.observation.published_hour)}.
      {ward && (observed == null ? " File de transfert de l’unité non renseignée." :
        ` File de transfert de ${ward.label} à 16 h · ${observed.toLocaleString("fr-FR", { maximumFractionDigits: 2 })} patients équivalents.`)}</p>}
  </section>;
}
