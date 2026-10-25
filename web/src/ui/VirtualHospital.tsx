import { useState } from "react";
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
    <small>Depuis le début de cette session hospitalière</small>
  </div>;
}
export function VirtualJournal({ workspace: { view: v } }: { workspace: Workspace }) {
  return <section><h1>Journal des décisions · {v?.hospital_name}</h1>
    <p>Les 50 dernières décisions de cet établissement. « Prise en charge » confirme la commande, pas la fin du nettoyage ou l’installation du patient.</p>
    {!v?.decisions.length ? <p>Aucune décision enregistrée pour cet établissement.</p> : <ol className="virtual-journal">{[...v.decisions].reverse().map(d => <li key={d.request_id}>
      <strong>{clock(d.at)} · {d.action === "prioritize_cleaning" ? "Nettoyage prioritaire" : "Réservation"} · {d.bed_id}</strong>
      <p>{d.patient_id ? `${d.patient_id} · ` : ""}{d.accepted ? "Validation" : "Refus"} · {d.actor}</p>
      <p>{!d.accepted ? "Refus enregistré" : STATUS[d.status]}{d.outcome_at ? ` à ${clock(d.outcome_at)}` : ""}</p>
      {d.reason ? <p>Motif : {d.reason}</p> : null}
    </li>)}</ol>}
  </section>;
}
