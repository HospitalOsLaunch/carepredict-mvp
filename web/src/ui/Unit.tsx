import type { Bed } from "../api/types";
import { BED_STATE, STAGE, capability, explain } from "../domain/labels";
import {
  type Assessment,
  type ChainLink,
  type Freshness,
  clock,
  compatibleBed,
  duration,
  freshnessIndex,
  queueEntries,
  releaseChains,
  stayCount,
} from "../domain/view";
import { Fresh, plural } from "./common";
import { Check, Clock, Cross, Dash, Question } from "./icons";

// ---------------------------------------------------------------- release chains

const MARK = { ok: Check, todo: Clock, blocked: Cross, unknown: Question, na: Dash } as const;
const SHORT: Record<ChainLink["id"], string> = {
  medical: "Médical",
  documents: "Docs",
  escort: "Accomp.",
  downstream: "Aval",
  transport: "Transp.",
};
const STATUS_WORD = {
  ok: "fait",
  todo: "à faire",
  blocked: "bloqué",
  unknown: "non renseigné",
  na: "non requis",
} as const;

function LinkNode({ link }: { link: ChainLink }) {
  const Icon = MARK[link.status];
  return (
    <li className={`link-node link-node--${link.status}`}>
      <span className="link-node__mark" aria-hidden="true">
        <Icon size={12} />
      </span>
      <span className="link-node__label" title={`${link.label} : ${link.detail}`}>
        <span className="long">{link.label}</span>
        <span className="short">{SHORT[link.id]}</span>
      </span>
      <span className="link-node__detail">{link.detail}</span>
      <span className="visually-hidden">
        {link.label} : {STATUS_WORD[link.status]}, {link.detail}.
      </span>
    </li>
  );
}

export function ReleaseBoard({ a }: { a: Assessment }) {
  const chains = releaseChains(a.state, a.plan);
  const stays = stayCount(a.state, a.plan);
  const fresh = freshnessIndex(a);
  const target = a.plan?.decision === "recommend" ? a.plan.selected : null;
  return (
    <section className="panel" aria-labelledby="releases-title">
      <header className="panel__head">
        <h2 className="panel__title" id="releases-title">
          Sorties à libérer
        </h2>
        <span className="panel__aside">
          {plural(chains.length, "sortie en préparation", "sorties en préparation")}
        </span>
      </header>
      {chains.length === 0 ? (
        <p className="empty">
          Aucune sortie en préparation. Les sorties apparaissent dès qu'une autorisation médicale ou une
          logistique est saisie.
        </p>
      ) : (
        <ol className="releases">
          {chains.map((c) => {
            const stage = c.readiness?.stage;
            const proposed = target?.patient_id === c.patient.id;
            const f = fresh.get(`discharge:${c.patient.id}`) ?? fresh.get(`patient:${c.patient.id}`);
            const stageTone =
              stage === "ready_for_simulation" ? "ok" : stage === "transport_to_request" ? "todo" : "";
            return (
              <li key={c.patient.id} className={`release${proposed ? " release--proposed" : ""}`}>
                <div className="release__who">
                  <span>
                    <span className="id">{c.patient.id}</span>{" "}
                    <span className="mute">lit {c.bed?.id ?? "?"}</span>
                  </span>
                  <span
                    className={`release__stage${stageTone ? ` release__stage--${stageTone}` : ""}`}
                    title={c.readiness?.blockers.map(explain).join(" ; ")}
                  >
                    {stage ? STAGE[stage].label : "Non évaluée"}
                  </span>
                  <span className="release__stage">
                    <Fresh f={f} prefix="Saisie " />
                  </span>
                </div>
                <ol className="chain" aria-label={`Étapes de sortie de ${c.patient.id}`}>
                  {c.links.map((l) => (
                    <LinkNode key={l.id} link={l} />
                  ))}
                </ol>
                <div className="handoff">
                  {c.nextCandidates.length ? (
                    <>
                      <span>Une fois libéré, {c.bed?.id} convient à</span>
                      <b>{c.nextCandidates.map((p) => p.id).join(", ")}</b>
                    </>
                  ) : (
                    <span>Aucun patient en attente n'est compatible avec ce lit</span>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {stays > 0 ? (
        <p className="stays">
          {plural(stays, "autre patient hospitalisé", "autres patients hospitalisés")} sans sortie prévue :
          aucune autorisation ni logistique saisie.
        </p>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------- waiting queue

export function Queue({ a }: { a: Assessment }) {
  const entries = queueEntries(a.state);
  const target = a.plan?.decision === "recommend" ? a.plan.selected : null;
  const targetBed = a.state.beds.find((b) => b.id === target?.bed_id) ?? null;
  return (
    <section className="panel" aria-labelledby="queue-title">
      <header className="panel__head">
        <h2 className="panel__title" id="queue-title">
          Patients à placer
        </h2>
        <span className="panel__aside">par priorité soignante</span>
      </header>
      {entries.length === 0 ? (
        <p className="empty">Aucun patient en attente de lit pour cette unité.</p>
      ) : (
        <ul className="queue">
          {entries.map((e) => {
            const needs = e.patient.requirements.map(capability);
            return (
              <li key={e.patient.id}>
                <span
                  className={`prio${e.patient.priority >= 4 ? " prio--high" : ""}`}
                  aria-label={`Priorité ${e.patient.priority} sur 5`}
                >
                  <span>
                    {e.patient.priority}
                    <small>/5</small>
                  </span>
                </span>
                <span className="queue__who">
                  <span className="id">{e.patient.id}</span>
                  <span className="queue__need">
                    {needs.length ? `Besoin : ${needs.join(", ")}` : "Sans besoin particulier"}
                  </span>
                </span>
                <span className="queue__wait">
                  <b className="num">{duration(e.waitedMinutes)}</b>
                  <span>depuis {clock(e.patient.waiting_since)}</span>
                </span>
                <span className={`queue__bed${e.usableNow.length || e.reservedBed ? " queue__bed--ok" : ""}`}>
                  {e.reservedBed
                    ? `Lit ${e.reservedBed.id} réservé`
                    : e.usableNow.length
                      ? `Utilisable maintenant : ${e.usableNow.map((b) => b.id).join(", ")}`
                      : target?.patient_id === e.patient.id
                        ? "Concerné par la proposition"
                        : targetBed && target?.kind !== "reserve_bed" && compatibleBed(e.patient, targetBed)
                          ? `Aucun lit maintenant ; ${targetBed.id} serait libéré par la proposition`
                          : "Aucun lit compatible utilisable maintenant"}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- bed board

function bedClass(bed: Bed, leaving: string | undefined, target: boolean, f: Freshness | undefined) {
  const state = bed.reserved_for ? "reserved" : bed.state;
  return [
    "magnet",
    `magnet--${state}`,
    leaving
      ? leaving === "ready_for_simulation"
        ? "magnet--leaving magnet--leaving-ready"
        : "magnet--leaving"
      : "",
    target ? "magnet--target" : "",
    f?.stale ? "magnet--stale" : "",
  ]
    .filter(Boolean)
    .join(" ");
}

export function BedBoard({ a }: { a: Assessment }) {
  const fresh = freshnessIndex(a);
  const readiness = new Map((a.plan?.discharge_readiness ?? []).map((r) => [r.patient_id, r.stage]));
  const leavingIds = new Set(releaseChains(a.state, a.plan).map((c) => c.patient.id));
  const target = a.plan?.decision === "recommend" ? a.plan.selected.bed_id : null;
  const unit = a.state.units[0];
  const beds = [...a.state.beds].sort((x, y) => x.id.localeCompare(y.id, "fr", { numeric: true }));
  // Beds the backend excluded (stale or missing) stay on the board, explicitly unknown.
  const known = new Set(beds.map((b) => b.id));
  const ghosts = [...new Set([...a.state.issues, ...a.gateReasons])]
    .map((c) => c.match(/^(stale|missing):bed:(.+)$/))
    .filter((m): m is RegExpMatchArray => !!m && !known.has(m[2]!))
    .map((m) => ({ id: m[2]!, why: m[1] === "stale" ? "Périmé" : "Manquant" }));
  type Slot =
    | { id: string; ghost: (typeof ghosts)[number]; bed?: undefined }
    | { id: string; ghost?: undefined; bed: Bed };
  const slots: Slot[] = [
    ...ghosts.map((g) => ({ id: g.id, ghost: g })),
    ...beds.map((b) => ({ id: b.id, bed: b })),
  ].sort((x, y) => x.id.localeCompare(y.id, "fr", { numeric: true }));
  const renderBed = (bed: Bed) => {
    const f = fresh.get(`bed:${bed.id}`);
    const leaving =
      bed.occupant && leavingIds.has(bed.occupant)
        ? (readiness.get(bed.occupant) ?? "logistics_blocked")
        : undefined;
    const label = bed.reserved_for ? `→ ${bed.reserved_for}` : (bed.occupant ?? BED_STATE[bed.state]);
    const description = [
      `Lit ${bed.id}`,
      bed.reserved_for ? `réservé pour ${bed.reserved_for}` : BED_STATE[bed.state].toLowerCase(),
      bed.occupant ? `occupé par ${bed.occupant}` : "",
      leaving ? `sortie : ${STAGE[leaving as keyof typeof STAGE].label.toLowerCase()}` : "",
      bed.capabilities.length ? `équipement : ${bed.capabilities.map(capability).join(", ")}` : "",
      f ? (f.stale ? "information périmée" : `mis à jour il y a ${duration(f.minutes)}`) : "",
      target === bed.id ? "concerné par la proposition" : "",
    ]
      .filter(Boolean)
      .join(", ");
    return (
      <li key={bed.id} className={bedClass(bed, leaving, target === bed.id, f)} title={description}>
        <span className="visually-hidden">{description}</span>
        <span className="magnet__id" aria-hidden="true">
          {bed.id}
        </span>
        {bed.capabilities.includes("oxygene") ? (
          <span className="magnet__cap" aria-hidden="true">
            O₂
          </span>
        ) : null}
        <span className="magnet__state" aria-hidden="true">
          {label}
        </span>
      </li>
    );
  };
  return (
    <section className="panel" aria-labelledby="beds-title">
      <header className="panel__head">
        <h2 className="panel__title" id="beds-title">
          Lits
        </h2>
        <span className="panel__aside">
          {unit?.staffed_beds != null
            ? `${unit.staffed_beds} armés sur ${beds.length + ghosts.length}`
            : "lits armés inconnus"}
        </span>
      </header>
      <ul className="board">
        {slots.map((slot) =>
          slot.ghost ? (
            <li
              key={slot.ghost.id}
              className="magnet magnet--unknown magnet--stale"
              title={`Lit ${slot.ghost.id} : ${slot.ghost.why}`}
            >
              <span className="visually-hidden">{`Lit ${slot.ghost.id} : ${slot.ghost.why}, état non utilisé.`}</span>
              <span className="magnet__id" aria-hidden="true">
                {slot.ghost.id}
              </span>
              <span className="magnet__state" aria-hidden="true">
                {slot.ghost.why}
              </span>
            </li>
          ) : (
            renderBed(slot.bed)
          ),
        )}
      </ul>
      <div className="legend" aria-hidden="true">
        <span>
          <i style={{ background: "var(--bloc-wash)", borderColor: "var(--bloc)" }} /> Propre
        </span>
        <span>
          <i style={{ background: "var(--sac-wash)", borderColor: "var(--sac-mark)" }} /> À nettoyer
        </span>
        <span>
          <i style={{ background: "var(--magnet)", borderColor: "var(--magnet)" }} /> Occupé
        </span>
        <span>
          <i style={{ background: "var(--well)", borderStyle: "dashed" }} /> Fermé
        </span>
        <span>
          <i style={{ background: "var(--sac-mark)", height: 3, border: 0 }} /> Sortie en préparation
        </span>
        <span>
          <i style={{ outline: "2px solid var(--bloc)", outlineOffset: 1 }} /> Proposition
        </span>
      </div>
    </section>
  );
}
