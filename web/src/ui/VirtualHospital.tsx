import { useEffect, useState } from "react";
import type { Workspace } from "../data/useVirtualHospitals";
import { clock } from "../domain/view";
const STATUS = { accepted: "Transmission en cours", refusal_recorded: "Refus enregistré",
  executed: "Prise en charge confirmée", refused: "Commande non retenue", failed: "Échec de la commande" };
export function VirtualProposal({ workspace: w }: { workspace: Workspace }) {
  const [refusing, setRefusing] = useState(false);
  const [reason, setReason] = useState("");
  const v = w.view, p = v?.episode?.assessment.plan;
  const action = p?.selected;
  const label = action?.kind === "prioritize_cleaning" ? `Prioriser le nettoyage du lit ${action.bed_id}`
    : action?.kind === "reserve_bed" ? `Réserver le lit ${action.bed_id} pour ${action.patient_id}` : "Aucune action à valider pour le moment";
  const disabled = !v?.can_decide || w.store.busy || !!w.store.error;
  return <section className="virtual-proposal" aria-labelledby="virtual-proposal-title">
    <p className="eyebrow">Proposition · {v?.hospital_name}</p>
    <h2 id="virtual-proposal-title">{label}</h2>
    <p>La décision vous appartient. La prise en charge sera suivie dans le journal ; l’effet apparaîtra après confirmation du flux de l’établissement.</p>
    {p ? <a href="#/proposition">Consulter les éléments de décision</a> : <p>Analyse actualisée automatiquement à partir des observations reçues.</p>}
    {v?.can_decide ? <div className="virtual-actions">
      <button className="btn btn--primary" disabled={disabled} onClick={() => w.decide(true)}>Valider la proposition</button>
      <button className="btn" disabled={disabled} onClick={() => setRefusing(!refusing)}>Refuser</button>
    </div> : null}
    {refusing && v?.can_decide ? <form onSubmit={e => { e.preventDefault(); w.decide(false, reason.trim()); setRefusing(false); setReason(""); }}>
      <label>Motif du refus<input className="input" value={reason} maxLength={300} required onChange={e => setReason(e.target.value)} /></label>
      <button className="btn" disabled={disabled || !reason.trim()}>Enregistrer le refus</button>
    </form> : null}
    <button className="btn virtual-refresh" onClick={w.store.evaluate} disabled={w.store.busy}>Actualiser l’unité</button>
  </section>;
}
export function VirtualActivity({ workspace: { view: v } }: { workspace: Workspace }) {
  if (!v) return null;
  return <div className="virtual-activity" aria-label="Activité observée">
    <span><b>{v.activity.arrivals}</b> nouvelles attentes</span>
    <span><b>{v.activity.admissions}</b> installations observées</span>
    <span><b>{v.activity.departures}</b> sorties observées</span>
    <small>Depuis la dernière reprise du flux de cette unité</small>
  </div>;
}
export function VirtualJournal({ workspace: { view: v } }: { workspace: Workspace }) {
  return <section><h1>Journal des décisions · {v?.unit_name}</h1>
    <p>Les 50 dernières décisions de cette unité. « Prise en charge » confirme la commande, pas la fin du nettoyage ou l’installation du patient.</p>
    {!v?.decisions.length ? <p>Aucune décision enregistrée pour cet établissement.</p> : <ol className="virtual-journal">{[...v.decisions].reverse().map(d => <li key={d.request_id}>
      <strong>{clock(d.at)} · {d.action === "prioritize_cleaning" ? "Nettoyage prioritaire" : "Réservation"} · {d.bed_id}</strong>
      <p>{d.patient_id ? `${d.patient_id} · ` : ""}{d.accepted ? "Validation" : "Refus"} · {d.actor}</p>
      <p>{!d.accepted ? "Refus enregistré" : STATUS[d.status]}{d.outcome_at ? ` à ${clock(d.outcome_at)}` : ""}</p>
      {d.reason ? <p>Motif : {d.reason}</p> : null}
    </li>)}</ol>}
  </section>;
}

const dateLabel = (at: string) => new Intl.DateTimeFormat("fr-FR", { timeZone: "Europe/Paris", day: "numeric", month: "short" }).format(new Date(at));
export function CampusOverview({ workspace: w }: { workspace: Workspace }) {
  const o = w.overview;
  if (!o) return null;
  const occupied = o.units.reduce((n, u) => n + u.occupied, 0);
  const capacity = o.units.reduce((n, u) => n + u.capacity, 0);
  return <section className="campus-overview" aria-labelledby="campus-title">
    <div className="campus-heading"><div><p className="eyebrow">Votre établissement · {dateLabel(o.now)}</p>
      <h2 id="campus-title">{o.name}</h2><p>4 unités · Une situation partagée · Heure de Paris</p></div>
      <div className="campus-total"><strong>{occupied}<small> / {capacity}</small></strong><span>lits occupés observés</span></div></div>
    {w.historyError ? <p role="status">{w.historyError} Dernières observations conservées.</p> : null}
    <div className="campus-grid">{o.units.map(u => <button key={u.id} className="campus-unit"
      aria-pressed={w.store.unitId === `H1/${u.id}`} onClick={() => w.store.setUnit(`H1/${u.id}`)}>
      <span>{u.name}</span><strong>{u.occupied}<small> / {u.capacity} lits</small></strong>
      <meter min={0} max={u.capacity} value={u.occupied} aria-label={`Occupation ${u.name}`} />
      <span>{u.available ? `${u.waiting} patient${u.waiting > 1 ? "s" : ""} en attente` : "Flux indisponible"}</span>
      <small>Observation à {clock(u.observed_at)}</small>
    </button>)}</div>
  </section>;
}
export function HospitalHistory({ workspace: w }: { workspace: Workspace }) {
  const h = w.history;
  if (!h) return w.historyError ? <p role="status">{w.historyError}</p> : null;
  const m = h.model;
  const forecastAt = new Date(new Date(h.forecast.origin).getTime() + 3600000).toISOString();
  return <section className="hospital-history" aria-labelledby="history-title">
    <div className="campus-heading"><div><p className="eyebrow">Mémoire de l’unité · {w.view?.unit_name}</p>
      <h2 id="history-title">L’activité dans la durée</h2>
      <p>Du {dateLabel(h.from)} au {dateLabel(h.until)} · {h.samples} observations horaires conservées</p></div>
      <div className="campus-total"><strong>{h.forecast.occupied}<small> lits</small></strong>
        <span>Occupation prévue à {clock(forecastAt)}</span><small>À partir de l’observation de {clock(h.forecast.origin)}</small></div></div>
    <figure className="history-figure"><figcaption>Occupation moyenne par jour · {h.capacity} lits dotés</figcaption>
      <div className="history-bars" role="img" aria-label="Évolution de l’occupation quotidienne. Les valeurs exactes figurent dans le tableau ci-dessous.">
        {h.daily.map(d => <div key={d.date} title={`${d.date} : ${d.mean_occupied} lits occupés en moyenne`}>
          <span style={{ height: `${Math.max(2, d.mean_occupied / h.capacity * 100)}%` }} /></div>)}
      </div><div className="history-axis"><span>{dateLabel(h.from)}</span><span>{dateLabel(h.until)}</span></div>
    </figure>
    <p className="history-method">{m.selected === "ridge" ? "Prévision apprise sur l’historique de cette unité." : "Prévision de référence retenue : le modèle entraîné n’a pas amélioré la persistance sur la validation."} Données entièrement synthétiques.</p>
    <details><summary>Historique, apprentissage et qualité de prévision</summary>
      <p>HospitalOS a observé ce passé simulé. Les décisions humaines du journal commencent avec votre utilisation ; aucune validation passée n’est inventée.</p>
      <dl className="history-metrics"><div><dt>Apprentissage</dt><dd>{dateLabel(m.train_from)} – {dateLabel(m.train_until)} · {m.training_pairs} paires</dd></div>
        <div><dt>Validation chronologique</dt><dd>{dateLabel(m.validation_from)} – {dateLabel(m.validation_until)} · {m.validation_pairs} paires</dd></div>
        <div><dt>Erreur moyenne du modèle</dt><dd>{m.mae_beds.toFixed(2)} lits</dd></div><div><dt>Erreur de la persistance</dt><dd>{m.persistence_mae_beds.toFixed(2)} lits</dd></div></dl>
      <p>Prévision à une heure, modèle linéaire régularisé. La persistance reprend la dernière occupation observée. La validation sert au choix du modèle ; ce n’est pas un test clinique indépendant. Le planificateur des actions reste séparé de cette prévision.</p>
      <p className="history-version">Version {m.version} · Empreinte des données {m.data_sha256.slice(0, 16)}</p>
      <p><a href={`/api/product/hospitals/H1/units/${encodeURIComponent(w.view?.unit_id ?? "")}/history/export`} download>Télécharger les observations horaires (CSV)</a></p>
      <div className="history-table" tabIndex={0} role="region" aria-label="Observations quotidiennes"><table><caption>Observations quotidiennes — moyennes des mesures horaires</caption><thead><tr><th scope="col">Jour (Paris)</th><th scope="col">Lits occupés</th><th scope="col">Mesures</th></tr></thead>
        <tbody>{[...h.daily].reverse().map(d => <tr key={d.date}><th scope="row">{d.date}</th><td>{d.mean_occupied}</td><td>{d.samples}</td></tr>)}</tbody></table></div>
    </details>
  </section>;
}

export function ParisClock({ now, stale }: { now: string; stale: boolean }) {
  const [at, setAt] = useState(now);
  useEffect(() => {
    const start = performance.now();
    setAt(now);
    if (stale) return;
    const timer = window.setInterval(() => setAt(new Date(new Date(now).getTime() + performance.now() - start).toISOString()), 1000);
    return () => window.clearInterval(timer);
  }, [now, stale]);
  return <span title={stale ? "Dernière heure reçue — connexion interrompue" : "Heure de Paris"}>{new Intl.DateTimeFormat("fr-FR", {
    timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).format(new Date(at))}</span>;
}
