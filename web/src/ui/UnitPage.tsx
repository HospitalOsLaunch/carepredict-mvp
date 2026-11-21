import { useState } from "react";
import { type Assessment, clock } from "../domain/view";
import { InProgress, Proposal, type ToastFn } from "./Proposal";
import { BedBoard, Queue, ReleaseBoard, type StripTarget, TensionStrip } from "./Unit";
import { Illu, momentIllu } from "./illustrations";

/** Bonjour / Bonsoir / Bonne garde, from the hour of the reconstructed state in Paris. */
function parisHour(iso: string): number {
  const parts = new Intl.DateTimeFormat("fr-FR", {
    hour: "numeric",
    hourCycle: "h23",
    timeZone: "Europe/Paris",
  }).formatToParts(new Date(iso));
  return Number(parts.find((p) => p.type === "hour")?.value ?? 12);
}

function greeting(hour: number): string {
  if (hour >= 5 && hour < 18) return "Bonjour.";
  if (hour >= 18 && hour < 22) return "Bonsoir.";
  return "Bonne garde.";
}

type Zone = "liberer" | "lits" | "attribuer";
const ZONES: Array<[Zone, string]> = [
  ["liberer", "Libérer"],
  ["lits", "Lits"],
  ["attribuer", "Attribuer"],
];

export function UnitPage(props: {
  integrated?: boolean;
  a: Assessment;
  now: string;
  busy: boolean;
  awaitingEvaluation: boolean;
  onEvaluate: () => void;
  unit: { id: string; name: string };
  onToast: ToastFn;
}) {
  const { a } = props;
  const hour = parisHour(a.state.at);
  // Phone: one flow column at a time; the proposal decides which one opens first.
  const [zone, setZone] = useState<Zone>(() =>
    a.plan?.selected.kind === "request_transport"
      ? "liberer"
      : a.plan?.selected.kind === "prioritize_cleaning"
        ? "lits"
        : "attribuer",
  );

  const jump = (target: StripTarget["zone"]) => {
    if (target === "donnees") {
      window.location.hash = props.integrated ? "/donnees" : "/dossiers/donnees";
      return;
    }
    setZone(target);
    const el = document.getElementById(`zone-${target}`);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
    el?.focus({ preventScroll: true });
  };

  return (
    <>
      <div className="unit-heading">
        <h1 className="hello">
          <Illu name={momentIllu(hour)} size={44} className="hello__illu" />
          <span>
            {greeting(hour)} <span className="hello__rest">Voici votre unité à {clock(a.state.at)}.</span>
          </span>
        </h1>
        {!props.integrated && <a className="btn" href="#/">Ouvrir la vue Unité</a>}
      </div>
      {!props.integrated && <p className="demobar">Dossiers patients · Les propositions ci-dessous utilisent le flux de cet écran. Le classement multiressource est disponible pour les unités raccordées au moteur.</p>}
      <TensionStrip a={a} onJump={jump} />
      <Proposal {...props} />
      <InProgress
        unitId={props.unit.id}
        excludePlan={a.plan?.plan_id ?? null}
        now={props.now}
        onToast={props.onToast}
      />
      <div className="flowtabs" role="tablist" aria-label="Colonne affichée">
        {ZONES.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={zone === id}
            aria-controls={`zone-${id}`}
            className="flowtabs__tab"
            onClick={() => setZone(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className={`flowgrid flowgrid--show-${zone}`}>
        <ReleaseBoard a={a} />
        <BedBoard a={a} />
        <Queue a={a} />
      </div>
    </>
  );
}
