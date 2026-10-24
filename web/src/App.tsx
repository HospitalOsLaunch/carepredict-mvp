import { useCallback, useEffect, useRef, useState } from "react";
import { demoHistory, journal, statusOf, useJournal } from "./data/journal";
import { type Connection, type Store, useAssessment } from "./data/useAssessment";
import { type Assessment, clock, longClock, oldestFact } from "./domain/view";
import { DataQuality } from "./ui/DataQuality";
import { Journal } from "./ui/Journal";
import { InProgress, Proposal, type ToastFn } from "./ui/Proposal";
import { ProposalDetail } from "./ui/ProposalDetail";
import { BedBoard, Queue, ReleaseBoard, type StripTarget, TensionStrip } from "./ui/Unit";
import { UnitSwitcher } from "./ui/UnitSwitcher";
import { Fresh, Toast, type ToastState, useNow } from "./ui/common";
import { Alert, BoardIcon, BookIcon, Info, Mark, PulseIcon, ScalesIcon } from "./ui/icons";
import { Illu, momentIllu } from "./ui/illustrations";

type Route = "unite" | "proposition" | "journal" | "donnees";

interface Location {
  route: Route;
  /** Journal entry opened from a shared link: #/journal/<id>. */
  param: string | null;
}

function readRoute(): Location {
  const [head = "", ...rest] = window.location.hash.replace(/^#\/?/, "").split("/");
  const route = head === "proposition" || head === "donnees" || head === "journal" ? head : "unite";
  return { route, param: rest.length ? decodeURIComponent(rest.join("/")) : null };
}

function go(route: Route) {
  window.location.hash = route === "unite" ? "/" : `/${route}`;
}

function useRoute(): Location {
  const [route, setRoute] = useState(readRoute);
  useEffect(() => {
    const on = () => {
      setRoute(readRoute());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

const ROUTES: Array<{ id: Route; href: string; label: string; key: string; Icon: () => JSX.Element }> = [
  { id: "unite", href: "#/", label: "Unité", key: "A", Icon: () => <BoardIcon /> },
  { id: "proposition", href: "#/proposition", label: "Proposition", key: "D", Icon: () => <ScalesIcon /> },
  { id: "journal", href: "#/journal", label: "Journal", key: "J", Icon: () => <BookIcon /> },
  { id: "donnees", href: "#/donnees", label: "Données", key: "Q", Icon: () => <PulseIcon /> },
];

const ORIGIN: Record<Connection, string> = {
  probing: "Connexion…",
  "api-live": "API locale, unité en direct",
  "api-plan": "API locale, unités fictives",
  fixture: "Démonstration : unités et patients fictifs",
};

const TITLES: Record<Route, string> = {
  unite: "Unité",
  proposition: "Proposition",
  journal: "Journal des décisions",
  donnees: "Qualité des données",
};

const SHORTCUTS: Array<[string, string]> = [
  ["U", "Changer d'unité"],
  ["1 à 9", "Aller directement à l'unité n"],
  ["O", "Valider la proposition"],
  ["N", "Refuser, puis 1 à 6 pour le motif"],
  ["F", "C'est fait (proposition validée)"],
  ["R", "Réévaluer l'unité"],
  ["A", "Vue unité"],
  ["D", "Détail de la proposition"],
  ["J", "Journal des décisions"],
  ["Q", "Qualité des données"],
  ["?", "Afficher cette aide"],
];

/** Single-key shortcuts, ignored while typing or with a modifier held. */
function useShortcuts(
  store: Store,
  selectUnit: (id: string) => void,
  openSwitcher: () => void,
  openHelp: () => void,
) {
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return;
      const t = e.target instanceof HTMLElement ? e.target : null;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      if (t?.closest('[role="listbox"], dialog[open]')) return;
      const k = e.key.toLowerCase();
      const emit = (detail: string) => window.dispatchEvent(new CustomEvent("hos:shortcut", { detail }));
      const digit = Number(e.key);
      if (k === "u") openSwitcher();
      else if (k === "?") openHelp();
      else if (k === "o") emit("yes");
      else if (k === "n") emit("no");
      else if (k === "f") emit("done");
      else if (k === "j") go("journal");
      else if (k === "r") store.evaluate();
      else if (k === "a") go("unite");
      else if (k === "d") go("proposition");
      else if (k === "q") go("donnees");
      else if (digit >= 1 && digit <= 9) {
        // While the "why not" reasons are open, digits pick a reason instead of a unit.
        if (document.querySelector(".feedback")) emit(e.key);
        else if (store.units[digit - 1]) selectUnit(store.units[digit - 1]!.id);
        else return;
      } else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [store, selectUnit, openSwitcher, openHelp]);
}

export function App() {
  const store = useAssessment();
  const { route, param } = useRoute();
  const [toast, setToast] = useState<ToastState | null>(null);
  const [switcherSignal, setSwitcherSignal] = useState(0);
  const help = useRef<HTMLDialogElement>(null);
  const clearToast = useCallback(() => setToast(null), []);
  const openSwitcher = useCallback(() => setSwitcherSignal((n) => n + 1), []);
  const openHelp = useCallback(() => help.current?.showModal(), []);
  const a = store.assessment;
  const now = useNow(a, store.loadedAt);
  const notify = useCallback((message: string, undo?: () => void) => setToast({ message, undo }), []);
  const { records, me } = useJournal();
  const todo = now ? records.filter((r) => !r.sample && statusOf(r, now) === "validated").length : 0;

  // Demonstration: a plausible shift of earlier decisions, read-only, never stored.
  const stateAt = a?.state.at;
  useEffect(() => {
    if (store.connection === "fixture" || store.connection === "api-plan") {
      if (stateAt) journal.setSamples(demoHistory(stateAt, store.units));
    } else journal.setSamples([]);
  }, [store.connection, stateAt, store.units]);

  useEffect(() => {
    document.title = `${store.unitName} · ${TITLES[route]} · HospitalOS`;
  }, [route, store.unitName]);

  // Announce a unit change made by the person (switcher or digit key), not the initial load.
  const selectUnit = useCallback(
    (id: string) => {
      if (id === store.unitId) return;
      store.setUnit(id);
      const name = store.units.find((u) => u.id === id)?.name;
      if (name) setToast({ message: `Vous êtes sur ${name}` });
    },
    [store],
  );
  useShortcuts(store, selectUnit, openSwitcher, openHelp);

  return (
    <div className="shell">
      <a className="skip" href="#contenu">
        Aller au contenu
      </a>
      <header className="topbar">
        <div className="topbar__row">
          <a className="brand" href="#/" aria-label="HospitalOS, vue unité">
            <Mark />
            <span translate="no">HospitalOS</span>
          </a>
          <UnitSwitcher
            summaries={store.summaries}
            unitId={store.unitId}
            onSelect={selectUnit}
            openSignal={switcherSignal}
          />
          <nav className="nav" aria-label="Sections">
            {ROUTES.map((r) => (
              <a key={r.id} href={r.href} aria-current={route === r.id ? "page" : undefined}>
                {r.label}
                {r.id === "journal" && todo ? <Badge n={todo} /> : null}
              </a>
            ))}
          </nav>
          <div className="topbar__end">
            {a ? (
              <span className="stateclock" title={`État reconstruit pour le ${longClock(a.state.at)}`}>
                <span className="stateclock__label">État</span>
                <span className="stateclock__time num">{clock(a.state.at)}</span>
              </span>
            ) : null}
            <span
              className="mode"
              title="Mode observation : HospitalOS propose, vous décidez. Rien n'est envoyé ni réservé."
            >
              <span className="mode__dot" aria-hidden="true" />
              <span className="mode__text">Observation seule</span>
              <span className="mode__short" aria-hidden="true">
                Observation
              </span>
              <span className="visually-hidden">: aucune commande envoyée</span>
            </span>
            <button type="button" className="helpbtn" onClick={openHelp} aria-label="Raccourcis clavier">
              ?
            </button>
          </div>
        </div>
      </header>

      <main className="main" id="contenu" tabIndex={-1}>
        {store.error ? (
          <div className="notice notice--error" role="alert">
            <Alert />
            <span>{store.error}</span>
          </div>
        ) : null}
        {store.connection !== "api-live" && store.connection !== "probing" && a ? (
          <div className="notice notice--demo">
            <Info />
            <span className="notice__text">
              {ORIGIN[store.connection]}. Chaque proposition sort du vrai planificateur.
            </span>
            {store.situations.length > 1 ? (
              <label className="notice__select">
                <span>Situation</span>
                <select
                  id="situation"
                  className="select"
                  value={store.situationId}
                  onChange={(e) => store.setSituation(e.target.value)}
                >
                  {store.situations.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </div>
        ) : null}
        {!a || !now ? (
          <div className="skeleton" aria-busy="true" aria-label="Chargement de l'unité" />
        ) : route === "proposition" ? (
          <ProposalDetail a={a} />
        ) : route === "journal" ? (
          <Journal
            records={records}
            me={me}
            now={now}
            openId={param}
            units={store.units}
            unitId={store.unitId}
            onToast={notify}
          />
        ) : route === "donnees" ? (
          <DataQuality a={a} quality={store.quality} summary={store.shadowSummary} />
        ) : (
          <UnitPage
            key={store.unitId}
            a={a}
            now={now}
            busy={store.busy}
            awaitingEvaluation={store.awaitingEvaluation}
            onEvaluate={store.evaluate}
            unit={{ id: store.unitId, name: store.unitName }}
            onToast={notify}
          />
        )}
      </main>

      <footer className="foot">
        <span>
          HospitalOS propose, vous décidez. Mode observation : rien n'est envoyé au dossier patient.
        </span>
        <span>Identifiants pseudonymes, aucune donnée nominative.</span>
      </footer>

      <nav className="tabbar" aria-label="Sections">
        {ROUTES.map(({ id, href, label, Icon }) => (
          <a key={id} href={href} aria-current={route === id ? "page" : undefined}>
            <span className="tabbar__icon">
              <Icon />
              {id === "journal" && todo ? <Badge n={todo} /> : null}
            </span>
            {label}
          </a>
        ))}
      </nav>

      <dialog ref={help} className="help" aria-labelledby="help-title">
        <Illu name="keys" size={64} />
        <h2 id="help-title">Raccourcis pour aller vite</h2>
        <p className="help__lead">Une touche, une action. Vos mains restent où elles sont.</p>
        <dl>
          {SHORTCUTS.map(([k, v]) => (
            <div key={k}>
              <dt>
                <kbd className="kbd">{k}</kbd>
              </dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
        <form method="dialog">
          <button className="btn" type="submit">
            Fermer
          </button>
        </form>
      </dialog>
      <Toast toast={toast} onDone={clearToast} />
    </div>
  );
}

function Badge({ n }: { n: number }) {
  return (
    <span className="badge" aria-label={`${n} à faire`}>
      {n}
    </span>
  );
}

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

function UnitPage(props: {
  a: Assessment;
  now: string;
  busy: boolean;
  awaitingEvaluation: boolean;
  onEvaluate: () => void;
  unit: { id: string; name: string };
  onToast: ToastFn;
}) {
  const { a } = props;
  const oldest = oldestFact(a);
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
    if (target === "donnees") return go("donnees");
    setZone(target);
    const el = document.getElementById(`zone-${target}`);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
    el?.focus({ preventScroll: true });
  };

  return (
    <>
      <h1 className="hello">
        <Illu name={momentIllu(hour)} size={56} className="hello__illu" />
        <span>
          {greeting(hour)} <span className="hello__rest">Voici votre unité à {clock(a.state.at)}.</span>
        </span>
      </h1>
      <TensionStrip a={a} onJump={jump} />
      <Proposal {...props} />
      <InProgress
        unitId={props.unit.id}
        excludePlan={a.plan?.plan_id ?? null}
        now={props.now}
        onToast={props.onToast}
      />
      <p className="freshline">
        État reconstruit le {longClock(a.state.at)}.
        {oldest ? (
          <>
            {" "}
            Information la plus ancienne : <Fresh f={oldest} />.
          </>
        ) : null}
      </p>
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
