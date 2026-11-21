import { useId, useState, type ReactNode } from "react";
import type { UnitIntake } from "../api/worldPlans";
import type { WmWard } from "../api/worldModel";
import { n, time } from "../domain/worldModel";
import { Illu } from "./illustrations";

type Flow = "liberer" | "lits" | "attribuer";
const flows = [
  { id: "liberer", label: "Libérer", icon: "door", style: "release" },
  { id: "lits", label: "Lits", icon: "bed", style: "beds" },
  { id: "attribuer", label: "Attribuer", icon: "key", style: "assign" },
] as const;

function CaseList({ cases, selected }: { cases: UnitIntake["cases"]; selected: string[] }) {
  if (!cases.length) return <p className="ward-empty">Aucun dossier identifié dans le registre de cette unité.</p>;
  return <ul className="ward-cases">{cases.map(c =>
    <li key={c.id} className={selected.includes(c.id) ? "ward-case-picked" : undefined}>
      <div><strong className="id">{c.id}</strong><span>{c.eligible ? "Accord confirmé" : "Accord en attente"}</span></div>
      {c.scheduled_hour !== null && <p>Créneau du planning · {time(c.scheduled_hour)}</p>}
      {selected.includes(c.id) && <small>Inclus dans le plan</small>}
    </li>
  )}</ul>;
}

export function WardOverview({ state, ward, selectedIds, children }: {
  state: UnitIntake | null; ward: WmWard; selectedIds: string[]; children: ReactNode;
}) {
  const [zone, setZone] = useState<Flow>("liberer");
  const prefix = useId();
  const withUnit = (s: number | undefined) => s === undefined ? "—" : n(s);
  const outs = state?.cases.filter(c => c.kind === "discharge") ?? [];
  const ins = state?.cases.filter(c => c.kind === "admission") ?? [];
  const cells: { zone: Flow; label: string; value: string; detail: string }[] = [
    { zone: "attribuer", label: "À placer", value: withUnit(state?.admission_queue), detail: "File d’entrée estimée" },
    { zone: "lits", label: "Lits utilisables", value: withUnit(state?.available_beds), detail: "Propres et libres estimés" },
    { zone: "liberer", label: "Sorties identifiées", value: withUnit(state ? outs.length : undefined), detail: "Dossiers du service" },
    { zone: "attribuer", label: "En attente de transfert", value: withUnit(state?.transfer_queue), detail: "Patients équivalents" },
  ];
  function jump(id: Flow) {
    setZone(id);
    requestAnimationFrame(() => {
      const panel = document.getElementById(prefix + id);
      panel?.focus({ preventScroll: true });
      panel?.scrollIntoView({ block: "nearest" });
    });
  }
  const availablePercent = state && state.capacity_beds > 0 ? (100 * state.available_beds / state.capacity_beds) : 0;
  return <div className="ward-overview">
    <nav aria-label="Situation de l'unité" className="strip">
      {cells.map(c => <button key={c.label} className="strip__cell" disabled={!state} onClick={() => jump(c.zone)}>
        <span className="strip__label">{c.label}</span><strong className="strip__value num">{c.value}</strong>
        <span className="strip__detail">{c.detail}</span>
      </button>)}
    </nav>
    {children}
    <div className="flowtabs" role="group" aria-label="Colonne affichée">{flows.map(f =>
      <button key={f.id} type="button" className="flowtabs__tab" aria-pressed={f.id === zone}
        aria-controls={prefix + f.id} onClick={() => setZone(f.id)}>{f.label}</button>)}</div>
    <div className={`flowgrid flowgrid--show-${zone}`}>
      {flows.map(f => <section key={f.id} id={prefix + f.id} className={`panel flow flow--${f.style}`}
        aria-labelledby={prefix + f.id + "-caption"} tabIndex={-1}>
        <header className="panel__head"><h2 className="panel__title" id={prefix + f.id + "-caption"}>
          <Illu name={f.icon} size={36} />{f.label}</h2></header>
        {!state ? <p className="ward-empty">Données du service indisponibles.</p> : f.id === "lits" ?
          <div className="ward-beds"><strong>{n(state.available_beds)} <small>lits disponibles estimés</small></strong>
            <div className="ward-capacity" aria-hidden="true"><i style={{ width: `${availablePercent}%` }}/></div>
            <p>{state.capacity_beds} lits équipés · {ward.label}</p>
          </div> : <CaseList cases={f.id === "liberer" ? outs : ins} selected={selectedIds} />}
      </section>)}
    </div>
  </div>;
}
