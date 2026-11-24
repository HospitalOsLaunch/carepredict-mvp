import { useMemo, useState } from "react";
import {
  type DecisionRecord,
  ORIGIN_LABEL,
  type Person,
  STATUS,
  type Space,
  type Status,
  handover,
  journal,
  noteRecord,
  type RecordOrigin,
  reasonLabel,
  statusOf,
  toCsv,
  deltaText,
  todoHint,
  who,
} from "../data/journal";
import { clock, longClock, minutesBetween } from "../domain/view";
import type { ToastFn } from "./Proposal";
import { NoteField } from "./Proposal";
import { Back, Check, Copy, Download, LinkIcon, Search } from "./icons";
import { Empty, Illu } from "./illustrations";

/*
  Journal des décisions: what HospitalOS proposed and what people did with it, for the
  person on duty and the colleague who takes over. Three questions, in order:
  1. What is still waiting for me? (À suivre)
  2. What happened, by whom and why? (Historique, filters, one record = one shareable page)
  3. What do I hand over? (Transmission: copy as text, export as CSV)
*/

type Filter = "all" | "todo" | "done" | "refused" | "unanswered";
const FILTERS: Array<[Filter, string, Status[]]> = [
  ["all", "Toutes", []],
  ["todo", "À faire", ["validated", "pending"]],
  ["done", "Faites", ["done"]],
  ["refused", "Refusées", ["refused", "abandoned"]],
  ["unanswered", "Sans réponse", ["expired", "superseded"]],
];
type Period = "12" | "24" | "168" | "all";
const PERIODS: Array<[Period, string]> = [
  ["12", "Cette garde (12 h)"],
  ["24", "24 heures"],
  ["168", "7 jours"],
  ["all", "Tout l'historique"],
];

const dayFmt = new Intl.DateTimeFormat("fr-FR", {
  weekday: "long",
  day: "numeric",
  month: "long",
  timeZone: "Europe/Paris",
});
const dayKey = (iso: string) =>
  new Intl.DateTimeFormat("fr-CA", { timeZone: "Europe/Paris" }).format(new Date(iso));

function dayLabel(iso: string, now: string): string {
  const d = dayKey(iso);
  if (d === dayKey(now)) return `Aujourd'hui · ${dayFmt.format(new Date(iso))}`;
  if (d === dayKey(new Date(Date.parse(now) - 86400000).toISOString()))
    return `Hier · ${dayFmt.format(new Date(iso))}`;
  const s = dayFmt.format(new Date(iso));
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const lastHuman = (r: DecisionRecord) => [...r.events].reverse().find((e) => e.by && e.type !== "note");

function matches(r: DecisionRecord, q: string): boolean {
  if (!q) return true;
  const hay = [
    r.title,
    r.unitName,
    r.action?.bed_id,
    r.action?.patient_id,
    ...r.events.map((e) => `${e.note ?? ""} ${e.by?.name ?? ""} ${reasonLabel(e.reason) ?? ""}`),
  ]
    .join(" ")
    .toLowerCase();
  return q
    .toLowerCase()
    .split(/\s+/)
    .every((w) => hay.includes(w));
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function Journal(props: {
  records: DecisionRecord[];
  me: Person;
  now: string;
  openId: string | null;
  units: { id: string; name: string }[];
  unitId: string;
  onToast: ToastFn;
  /** Journal shown, and whether the person may look at the other one (live connection only). */
  space: Space;
  canSwitch: boolean;
  /** Where a free note for the next shift is written, and the unit's state for the handover. */
  scope: { unitId: string; unitName: string; origin: RecordOrigin; situationId: string; state: string[] };
}) {
  const { records, me, now, openId } = props;
  // Units of the cockpit plus those met in the journal (e.g. the 24-hour plan's units).
  const units = useMemo(() => {
    const map = new Map(props.units.map((u) => [u.id, u.name]));
    for (const r of records) if (!map.has(r.unitId)) map.set(r.unitId, r.unitName);
    return [...map].map(([id, name]) => ({ id, name }));
  }, [props.units, records]);
  const [query, setQuery] = useState("");
  const [unit, setUnit] = useState("all");
  const [period, setPeriod] = useState<Period>("24");
  const [mineOnly, setMineOnly] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");

  const scoped = useMemo(
    () =>
      records.filter(
        (r) =>
          (unit === "all" || r.unitId === unit) &&
          (period === "all" || minutesBetween(r.proposedAt, now) <= Number(period) * 60) &&
          (!mineOnly || r.events.some((e) => e.by?.id === me.id)) &&
          matches(r, query.trim()),
      ),
    [records, unit, period, mineOnly, query, now, me.id],
  );
  const counts = useMemo(() => {
    const c = Object.fromEntries(FILTERS.map(([id]) => [id, 0])) as Record<Filter, number>;
    for (const r of scoped) {
      const s = statusOf(r, now);
      c.all += 1;
      for (const [id, , set] of FILTERS) if (set.includes(s)) c[id] += 1;
    }
    return c;
  }, [scoped, now]);
  const shown = useMemo(() => {
    const set = FILTERS.find(([id]) => id === filter)![2];
    return set.length ? scoped.filter((r) => set.includes(statusOf(r, now))) : scoped;
  }, [scoped, filter, now]);
  const days = useMemo(() => {
    const out: Array<[string, DecisionRecord[]]> = [];
    for (const r of shown) {
      const k = dayKey(r.proposedAt);
      const last = out[out.length - 1];
      if (last && last[0] === k) last[1].push(r);
      else out.push([k, [r]]);
    }
    return out;
  }, [shown]);

  const followUp = records.filter((r) => {
    const s = statusOf(r, now);
    return s === "validated" || s === "pending";
  });
  const opened = openId ? (records.find((r) => r.id === openId) ?? null) : null;
  const reset = () => {
    setQuery("");
    setUnit("all");
    setPeriod("all");
    setMineOnly(false);
    setFilter("all");
  };

  const detail = openId ? (
    opened ? (
      <Detail r={opened} me={me} now={now} onToast={props.onToast} />
    ) : (
      <section className="panel jdetail" aria-label="Décision introuvable">
        <Empty illu="cloud" title="Cette décision n'est pas dans ce journal.">
          Elle a peut-être été prise sur un autre poste : dans ce prototype, le journal reste sur le poste où
          il a été écrit.{" "}
          <a className="link" href="#/journal">
            Revenir au journal
          </a>
        </Empty>
      </section>
    )
  ) : null;

  return (
    <>
      <header className="page-head">
        <a className="back" href="#/">
          <Back size={14} /> Unité
        </a>
        <h1>
          <Illu name="notebook" size={64} />
          Journal des décisions
        </h1>
        <p>Ce qui a été proposé et décidé : par qui, quand, pourquoi.</p>
        <SpaceNote space={props.space} canSwitch={props.canSwitch} />
        <SignedAs me={me} />
        <ShiftNote scope={props.scope} now={now} onToast={props.onToast} />
      </header>

      <div className={`journal${openId ? " journal--open" : ""}`}>
        <div className="journal__main stack">
          {openId ? <div className="journal__detail-phone">{detail}</div> : null}
          <section className="panel" aria-labelledby="follow-title">
            <header className="panel__head">
              <h2 className="panel__title" id="follow-title">
                <Illu name="clipboard" size={32} />À suivre
              </h2>
              <span className="count" aria-hidden="true">
                {followUp.length}
              </span>
            </header>
            {followUp.length ? (
              <ul className="jlist">
                {followUp.map((r) => (
                  <Row
                    key={r.id}
                    r={r}
                    me={me}
                    now={now}
                    open={r.id === openId}
                    onToast={props.onToast}
                    quick
                  />
                ))}
              </ul>
            ) : (
              <Empty illu="coffee" title="Rien en suspens.">
                Chaque proposition a reçu une réponse. Les prochaines arriveront ici.
              </Empty>
            )}
          </section>

          <section className="panel" aria-labelledby="history-title">
            <header className="panel__head">
              <h2 className="panel__title" id="history-title">
                <Illu name="hourglass" size={32} />
                Historique
              </h2>
              <span className="panel__aside">
                {shown.length} décision{shown.length > 1 ? "s" : ""}
              </span>
            </header>
            <div className="jtools">
              <label className="jsearch">
                <Search />
                <span className="visually-hidden">Rechercher</span>
                <input
                  className="input"
                  type="search"
                  placeholder="Patient, lit, personne, motif…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>
              <label className="jselect">
                <span className="visually-hidden">Unité</span>
                <select className="select" value={unit} onChange={(e) => setUnit(e.target.value)}>
                  <option value="all">Toutes les unités</option>
                  {units.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="jselect">
                <span className="visually-hidden">Période</span>
                <select
                  className="select"
                  value={period}
                  onChange={(e) => setPeriod(e.target.value as Period)}
                >
                  {PERIODS.map(([id, label]) => (
                    <option key={id} value={id}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <div className="seg" role="group" aria-label="Auteur">
                <button type="button" aria-pressed={!mineOnly} onClick={() => setMineOnly(false)}>
                  Tout le monde
                </button>
                <button type="button" aria-pressed={mineOnly} onClick={() => setMineOnly(true)}>
                  Moi
                </button>
              </div>
            </div>
            <div className="jfilters" role="group" aria-label="Statut">
              {FILTERS.map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className="chip"
                  aria-pressed={filter === id}
                  onClick={() => setFilter(id)}
                >
                  {label} <span className="chip__count num">{counts[id]}</span>
                </button>
              ))}
            </div>
            {days.length ? (
              days.map(([k, list]) => (
                <div key={k} className="jday">
                  <h3 className="jday__title">{dayLabel(list[0]!.proposedAt, now)}</h3>
                  <ul className="jlist">
                    {list.map((r) => (
                      <Row
                        key={r.id}
                        r={r}
                        me={me}
                        now={now}
                        open={r.id === openId}
                        onToast={props.onToast}
                      />
                    ))}
                  </ul>
                </div>
              ))
            ) : (
              <Empty illu="magnifier" title="Aucune décision ne correspond.">
                Élargissez la période ou retirez un filtre.{" "}
                <button type="button" className="linkbtn" onClick={reset}>
                  Tout afficher
                </button>
              </Empty>
            )}
          </section>
        </div>

        <aside className="journal__side stack">
          {detail ? <div className="journal__detail-desk">{detail}</div> : null}
          <Handover records={records} me={me} now={now} units={units} scope={props.scope} onToast={props.onToast} />
        </aside>
      </div>
    </>
  );
}

function Pill({ s }: { s: Status }) {
  return <span className={`pill pill--${STATUS[s].tone}`}>{STATUS[s].label}</span>;
}

function Row({
  r,
  me,
  now,
  open,
  quick,
  onToast,
}: {
  r: DecisionRecord;
  me: Person;
  now: string;
  open: boolean;
  quick?: boolean;
  onToast: ToastFn;
}) {
  const s = statusOf(r, now);
  const human = lastHuman(r);
  const reason = reasonLabel(human?.reason);
  const note = [...r.events].reverse().find((e) => e.note)?.note;
  const meta = [
    r.unitName,
    r.origin !== "api-live" && r.situationId && !r.sample ? r.situation : null,
    human
      ? who(human.by, me)
      : s === "note"
        ? who(r.events[0]?.by ?? null, me)
        : s === "pending"
          ? `fraîche jusqu'à ${clock(r.expiresAt)}`
          : null,
    reason,
  ].filter(Boolean);
  return (
    <li className={`jrow${open ? " jrow--open" : ""}`}>
      <a
        className="jrow__link"
        href={`#/journal/${encodeURIComponent(r.id)}`}
        aria-current={open ? "true" : undefined}
      >
        <span className="jrow__time num">{clock(r.proposedAt)}</span>
        <span className="jrow__body">
          <span className="jrow__title">
            {r.title}
            {r.answerAt === "plan" ? <span className="jtag">Plan 24 h</span> : null}
            {r.origin === "unknown" ? <span className="jtag jtag--warn">origine non enregistrée</span> : null}
          </span>
          <span className="jrow__meta">{meta.join(" · ")}</span>
          {note ? <span className="jrow__note">« {note} »</span> : null}
        </span>
        <span className="jrow__end">
          <Pill s={s} />
        </span>
      </a>
      {quick && s === "validated" && !r.sample ? (
        <button
          type="button"
          className="btn btn--small jrow__quick"
          onClick={() => {
            journal.act(r.id, "done", now);
            onToast("C'est noté.", () => journal.undo(r.id));
          }}
        >
          <Check /> C'est fait
        </button>
      ) : null}
    </li>
  );
}

const STEP: Record<string, string> = {
  proposed: "Proposée par HospitalOS",
  abstained: "Pas de proposition : données à vérifier",
  validated: "Validée",
  done: "Faite",
  refused: "Refusée",
  abandoned: "Finalement non",
  expired: "Restée sans réponse",
  superseded: "Remplacée par une évaluation plus récente",
  note: "Note",
};

function Detail({ r, me, now, onToast }: { r: DecisionRecord; me: Person; now: string; onToast: ToastFn }) {
  const s = statusOf(r, now);
  const link = `${window.location.href.split("#")[0]}#/journal/${encodeURIComponent(r.id)}`;
  return (
    <section className="panel jdetail" aria-labelledby="jdetail-title">
      <header className="jdetail__head">
        <Pill s={s} />
        {r.sample ? <span className="jrow__sample">exemple de démonstration</span> : null}
        <span className="spacer" />
        <a className="linkbtn" href="#/journal" aria-label="Fermer la fiche">
          Fermer
        </a>
      </header>
      <h2 className="jdetail__title" id="jdetail-title">
        {r.title}
      </h2>
      <p className="jdetail__unit">
        {r.unitName} · {longClock(r.proposedAt)}
      </p>
      <dl className="jdetail__facts">
        {r.deltaRatio != null ? (
          <div>
            <dt>Effet simulé</dt>
            <dd className="num">
              {deltaText(r.deltaRatio)} d'attente d'ici {r.horizonEnd}
            </dd>
          </div>
        ) : null}
        {r.action ? (
          <div>
            <dt>Fraîche jusqu'à</dt>
            <dd className="num">{clock(r.expiresAt)}</dd>
          </div>
        ) : null}
        <div>
          <dt>Rang</dt>
          <dd>{r.rank === 0 ? "Premier choix de HospitalOS" : "Autre option choisie par l'équipe"}</dd>
        </div>
        <div>
          <dt>Origine</dt>
          <dd data-testid="jdetail-origin">{ORIGIN_LABEL[r.origin] ?? r.origin}</dd>
        </div>
        <div>
          <dt>Situation</dt>
          <dd>{r.situation}</dd>
        </div>
        {r.stateFingerprint ? (
          <div>
            <dt>État évalué</dt>
            <dd className="num" title={r.stateFingerprint}>
              {r.stateFingerprint.slice(0, 12)}
            </dd>
          </div>
        ) : null}
      </dl>
      {r.why.length ? (
        <>
          <h3 className="jdetail__h3">Pourquoi</h3>
          <ul className="facts">
            {r.why.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </>
      ) : null}
      <h3 className="jdetail__h3">Chronologie</h3>
      <ol className="jtimeline">
        {r.events.map((e, i) => (
          <li key={i} className={`jtimeline__item jtimeline__item--${e.type}`}>
            <span className="jtimeline__time num">{clock(e.at)}</span>
            <span className="jtimeline__body">
              <span className="jtimeline__what">
                {STEP[e.type]}
                {e.by ? (
                  <>
                    {" "}
                    · {who(e.by, me)}
                    {e.by.role ? <span className="mute">, {e.by.role.toLowerCase()}</span> : null}
                  </>
                ) : null}
              </span>
              {e.reason ? <span className="jtimeline__reason">{reasonLabel(e.reason)}</span> : null}
              {e.note ? <span className="jtimeline__note">« {e.note} »</span> : null}
            </span>
          </li>
        ))}
        {s === "pending" ? (
          <li className="jtimeline__item jtimeline__item--next">
            <span className="jtimeline__time num">{clock(r.expiresAt)}</span>
            <span className="jtimeline__body">
              <span className="jtimeline__what mute">Sans réponse d'ici là, elle sera close.</span>
            </span>
          </li>
        ) : null}
      </ol>
      {s === "validated" && !r.sample ? (
        <div className="jdetail__todo">
          <p>
            <strong>À faire :</strong> {todoHint(r.action, r)}
          </p>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => {
              journal.act(r.id, "done", now);
              onToast("C'est noté.", () => journal.undo(r.id));
            }}
          >
            <Check /> C'est fait
          </button>
        </div>
      ) : null}
      {s === "pending" ? (
        <p className="jdetail__hint">
          {r.answerAt === "plan" ? "Pour répondre, ouvrez le plan :" : "Pour répondre, ouvrez l'unité :"}{" "}
          <a className="link" href={r.answerAt === "plan" ? "#/plan" : "#/"}>
            {r.unitName}
          </a>
          .
        </p>
      ) : null}
      <NoteField record={r} now={now} compact hideNotes />
      <div className="jdetail__share">
        <button
          type="button"
          className="btn btn--small"
          onClick={async () =>
            onToast(
              (await copyText(link))
                ? "Lien copié vers cette fiche."
                : "Copie impossible ici : le lien est dans la barre d'adresse.",
            )
          }
        >
          <LinkIcon /> Copier le lien
        </button>
      </div>
    </section>
  );
}

function Handover({
  records: all,
  me,
  now,
  units,
  scope,
  onToast,
}: {
  records: DecisionRecord[];
  me: Person;
  now: string;
  units: { id: string; name: string }[];
  scope: { unitId: string; unitName: string; state: string[] };
  onToast: ToastFn;
}) {
  // The handover is for one unit by default (the one on screen), with its state: the next
  // shift needs who waits and what blocks, not only decisions (user testing).
  const [unitId, setUnitId] = useState(scope.unitId);
  const records = all.filter((r) => unitId === "all" || r.unitId === unitId);
  const unitName = unitId === "all" ? "Toutes unités" : (units.find((u) => u.id === unitId)?.name ?? scope.unitName);
  const [fallback, setFallback] = useState<string | null>(null);
  const count = (set: Status[]) => records.filter((r) => set.includes(statusOf(r, now))).length;
  const tiles: Array<[string, number, string]> = [
    ["À faire", count(["validated"]), "todo"],
    ["Faites", count(["done"]), "ok"],
    ["Refusées", count(["refused", "abandoned"]), "quiet"],
    ["Sans réponse", count(["expired", "superseded"]), "quiet"],
  ];
  const title = `Transmission HospitalOS · ${unitName} · ${longClock(now)}`;
  const text = handover(records, me, now, title, unitId === scope.unitId ? scope.state : []);
  const download = () => {
    const blob = new Blob([`﻿${toCsv(records, me, now)}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `hospitalos-journal-${now.slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    onToast(`${records.length} décisions exportées.`);
  };
  return (
    <section className="panel" aria-labelledby="handover-title">
      <header className="panel__head">
        <h2 className="panel__title" id="handover-title">
          <Illu name="envelope" size={32} />
          Transmission
        </h2>
      </header>
      <div className="panel__body">
        <label className="jselect hunit">
          <span className="visually-hidden">Unité de la transmission</span>
          <select className="select" value={unitId} onChange={(e) => setUnitId(e.target.value)}>
            {units.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
            <option value="all">Toutes les unités</option>
          </select>
        </label>
        <ul className="htiles">
          {tiles.map(([label, n, tone]) => (
            <li key={label} className={`htile htile--${tone}`}>
              <span className="htile__n num">{n}</span>
              <span className="htile__label">{label}</span>
            </li>
          ))}
        </ul>
        <div className="hactions">
          <button
            type="button"
            className="btn btn--primary"
            onClick={async () => {
              if (await copyText(text)) onToast("Transmission copiée. Prête à coller.");
              else setFallback(text);
            }}
          >
            <Copy /> Copier la transmission
          </button>
          <button type="button" className="btn" onClick={download} disabled={!records.length}>
            <Download /> Exporter (CSV)
          </button>
        </div>
        {fallback ? (
          <label className="hfallback">
            <span>Copie automatique indisponible ici : sélectionnez le texte.</span>
            <textarea
              className="input"
              readOnly
              rows={8}
              value={fallback}
              onFocus={(e) => e.target.select()}
            />
          </label>
        ) : null}
        <p className="note">Prototype : journal gardé sur ce poste.</p>
      </div>
    </section>
  );
}

/** Which journal is on screen. Real and fictitious decisions are never listed together. */
function SpaceNote({ space, canSwitch }: { space: Space; canSwitch: boolean }) {
  if (!canSwitch) {
    return space === "demo" ? (
      <p className="jspace jspace--demo" data-testid="journal-space">
        <strong>Journal de démonstration.</strong> Décisions prises sur des patients fictifs, gardées à part du
        journal de l'unité en observation.
      </p>
    ) : null;
  }
  return (
    <div className="jspace" data-testid="journal-space">
      <div className="seg" role="group" aria-label="Journal affiché">
        <button type="button" aria-pressed={space === "live"} onClick={() => journal.useSpace("live")}>
          Unité en observation
        </button>
        <button type="button" aria-pressed={space === "demo"} onClick={() => journal.useSpace("demo")}>
          Démonstration
        </button>
      </div>
      {space === "demo" ? (
        <span className="jspace__text">Patients fictifs : rien de ce qui suit ne concerne l'unité.</span>
      ) : null}
    </div>
  );
}

/** A note for the next shift, not tied to a proposal (« le fils de M. X appelle à 18 h »). */
function ShiftNote({
  scope,
  now,
  onToast,
}: {
  scope: { unitId: string; unitName: string; origin: RecordOrigin; situationId: string };
  now: string;
  onToast: ToastFn;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  if (!open) {
    return (
      <p className="shiftnote">
        <button type="button" className="btn btn--small" onClick={() => setOpen(true)} data-testid="shift-note">
          + Note pour la relève
        </button>
      </p>
    );
  }
  return (
    <form
      className="shiftnote shiftnote--form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!text.trim()) return setOpen(false);
        journal.record(noteRecord({ id: scope.unitId, name: scope.unitName }, scope.origin, scope.situationId, now, text.trim()));
        setText("");
        setOpen(false);
        onToast("Note ajoutée à la transmission.");
      }}
    >
      <label className="visually-hidden" htmlFor="shift-note-text">
        Note pour la relève, {scope.unitName}
      </label>
      <input
        id="shift-note-text"
        className="input"
        autoFocus
        maxLength={280}
        placeholder={`${scope.unitName} : ex. famille de P-0388 rappelle à 18 h`}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
      />
      <button className="btn btn--primary" type="submit">
        Ajouter
      </button>
    </form>
  );
}

/** Decisions are signed: colleagues see who validated or refused. */
function SignedAs({ me }: { me: Person }) {
  const [editing, setEditing] = useState(!me.name);
  const [name, setName] = useState(me.name);
  const [role, setRole] = useState(me.role || "Cadre de santé");
  if (!editing && !me.name) {
    return (
      <p className="signed">
        Vos décisions sont signées « Vous ».{" "}
        <button type="button" className="linkbtn" onClick={() => setEditing(true)}>
          Ajouter mon nom
        </button>
      </p>
    );
  }
  if (!editing) {
    return (
      <p className="signed">
        <span>
          Vous signez : <strong>{me.name}</strong>
          {me.role ? `, ${me.role.toLowerCase()}` : ""}.
        </span>
        <button type="button" className="linkbtn" onClick={() => setEditing(true)}>
          Modifier
        </button>
      </p>
    );
  }
  return (
    <form
      className="signed signed--form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!name.trim()) return;
        journal.setMe({ name, role });
        setEditing(false);
      }}
    >
      <span>Signez vos décisions pour que vos collègues sachent qui a tranché :</span>
      <label>
        <span className="visually-hidden">Votre nom</span>
        <input
          className="input"
          placeholder="Prénom N."
          value={name}
          maxLength={40}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label>
        <span className="visually-hidden">Votre rôle</span>
        <select className="select" value={role} onChange={(e) => setRole(e.target.value)}>
          {["Cadre de santé", "Gestionnaire de lits", "Cadre de nuit", "IDE", "IDE de nuit", "IDE de coordination", "AS", "Médecin"].map(
            (r) => (
              <option key={r}>{r}</option>
            ),
          )}
        </select>
      </label>
      <button className="btn btn--small" type="submit">
        Enregistrer
      </button>
      <button className="linkbtn" type="button" onClick={() => setEditing(false)}>
        Plus tard
      </button>
    </form>
  );
}
