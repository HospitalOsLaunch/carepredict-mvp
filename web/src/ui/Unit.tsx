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
  nextStep,
  oldestFact,
  queueEntries,
  releaseChains,
  situation,
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
    <section
      className="panel flow flow--release"
      aria-labelledby="releases-title"
      id="zone-liberer"
      tabIndex={-1}
    >
      <header className="panel__head">
        <h2 className="panel__title" id="releases-title">
          Libérer
        </h2>
        <span className="panel__aside">
          {plural(chains.length, "sortie en préparation", "sorties en préparation")}
        </span>
      </header>
      {chains.length === 0 ? (
        <p className="empty">
          Aucune sortie en préparation. Elles apparaissent dès qu'une autorisation médicale ou une logistique
          de sortie est saisie.
        </p>
      ) : (
        <ol className="releases">
          {chains.map((c) => {
            const proposed =
              target?.patient_id === c.patient.id || (target?.bed_id && target.bed_id === c.bed?.id);
            const f = fresh.get(`discharge:${c.patient.id}`) ?? fresh.get(`patient:${c.patient.id}`);
            const next = nextStep(c.links);
            const more = c.nextCandidates.length - 2;
            return (
              <li key={c.patient.id} className={`release${proposed ? " release--proposed" : ""}`}>
                <div className="release__who">
                  <span className="id">{c.patient.id}</span>
                  <span className="bedtag">{c.bed?.id ?? "?"}</span>
                  <span className="release__age">
                    <Fresh f={f} />
                  </span>
                </div>
                <ol className="chain" aria-label={`Étapes de sortie de ${c.patient.id}`}>
                  {c.links.map((l) => (
                    <LinkNode key={l.id} link={l} />
                  ))}
                </ol>
                <p
                  className={`release__next release__next--${next.tone}`}
                  title={c.readiness?.blockers.map(explain).join(" ; ")}
                >
                  {next.text}
                </p>
                <p className="release__handoff">
                  {c.nextCandidates.length
                    ? `Libère ${c.bed?.id} pour ${c.nextCandidates
                        .slice(0, 2)
                        .map((p) => p.id)
                        .join(", ")}${more > 0 ? ` et ${more} autre${more > 1 ? "s" : ""}` : ""}`
                    : "Aucun patient en attente compatible"}
                </p>
              </li>
            );
          })}
        </ol>
      )}
      {stays > 0 ? (
        <p className="stays">
          {plural(stays, "autre patient hospitalisé", "autres patients hospitalisés")} sans sortie prévue.
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
    <section
      className="panel flow flow--assign"
      aria-labelledby="queue-title"
      id="zone-attribuer"
      tabIndex={-1}
    >
      <header className="panel__head">
        <h2 className="panel__title" id="queue-title">
          Attribuer
        </h2>
        <span className="panel__aside">
          {plural(entries.length, "patient à placer", "patients à placer")}
        </span>
      </header>
      {entries.length === 0 ? (
        <p className="empty">Aucun patient en attente de lit pour cette unité.</p>
      ) : (
        <ul className="queue">
          {entries.map((e) => {
            const needs = e.patient.requirements.map(capability);
            const bedLine = e.reservedBed
              ? { text: `Lit ${e.reservedBed.id} réservé`, tone: "ok" }
              : e.usableNow.length
                ? { text: `Utilisable maintenant : ${e.usableNow.map((b) => b.id).join(", ")}`, tone: "ok" }
                : target?.patient_id === e.patient.id
                  ? { text: "Concerné par la proposition", tone: "go" }
                  : targetBed && target?.kind !== "reserve_bed" && compatibleBed(e.patient, targetBed)
                    ? { text: `${targetBed.id} serait libéré par la proposition`, tone: "go" }
                    : { text: "Aucun lit compatible maintenant", tone: "none" };
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
                    {needs.length ? needs.join(", ") : "Sans besoin particulier"}
                  </span>
                </span>
                <span className="queue__wait">
                  <b className="num">{duration(e.waitedMinutes)}</b>
                  <span>depuis {clock(e.patient.waiting_since)}</span>
                </span>
                <span className={`queue__bed queue__bed--${bedLine.tone}`}>{bedLine.text}</span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- tension strip

export interface StripTarget {
  zone: "liberer" | "lits" | "attribuer" | "donnees";
}

export function TensionStrip({ a, onJump }: { a: Assessment; onJump: (zone: StripTarget["zone"]) => void }) {
  const s = situation(a.state, a.plan);
  const q = queueEntries(a.state);
  const longest = q.length ? Math.max(...q.map((e) => e.waitedMinutes)) : null;
  const chains = releaseChains(a.state, a.plan);
  const steps = chains.map((c) => nextStep(c.links).tone);
  const ready = steps.filter((t) => t === "ok").length;
  const todo = steps.filter((t) => t === "todo").length;
  const blocked = steps.filter((t) => t === "blocked").length;
  const unknown = steps.filter((t) => t === "unknown").length;
  const sortieDetail = [
    "prêtes",
    todo ? `${todo} à faire` : "",
    unknown ? `${unknown} à renseigner` : "",
    blocked ? `${blocked} ${blocked > 1 ? "bloquées" : "bloquée"}` : "",
  ]
    .filter(Boolean)
    .join(", ");
  const checks = [...new Set([...a.state.issues, ...a.gateReasons])].length;
  const oldest = oldestFact(a);
  const cells: Array<{
    zone: StripTarget["zone"];
    label: string;
    value: string;
    detail: string;
    tone?: "warn" | "go";
  }> = [
    {
      zone: "attribuer",
      label: "À placer",
      value: String(s.waiting),
      detail: longest != null ? `jusqu'à ${duration(longest)}` : "aucune attente",
    },
    {
      zone: "lits",
      label: "Lits utilisables",
      value: String(s.usable),
      detail: s.dirty ? `${s.dirty} à nettoyer` : "aucun à nettoyer",
      tone: s.usable > 0 ? "go" : undefined,
    },
    {
      zone: "liberer",
      label: "Sorties",
      value: `${ready}/${chains.length}`,
      detail: chains.length ? sortieDetail : "aucune en préparation",
    },
    {
      zone: "donnees",
      label: "Données",
      value: checks ? String(checks) : "OK",
      detail: checks
        ? `contrôle${checks > 1 ? "s" : ""} en échec`
        : oldest
          ? `plus ancienne : ${duration(oldest.minutes)}`
          : "à jour",
      tone: checks ? "warn" : undefined,
    },
  ];
  return (
    <nav className="strip" aria-label="Situation de l'unité">
      {cells.map((c) => (
        <button
          key={c.zone}
          type="button"
          className={`strip__cell${c.tone ? ` strip__cell--${c.tone}` : ""}`}
          onClick={() => onJump(c.zone)}
        >
          <span className="strip__label">{c.label}</span>
          <span className="strip__value num">{c.value}</span>
          <span className="strip__detail">{c.detail}</span>
        </button>
      ))}
    </nav>
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
    <section className="panel flow flow--beds" aria-labelledby="beds-title" id="zone-lits" tabIndex={-1}>
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
