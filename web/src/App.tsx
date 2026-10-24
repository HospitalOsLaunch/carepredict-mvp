import { useCallback, useEffect, useRef, useState } from "react";
import { type Connection, type Store, useAssessment } from "./data/useAssessment";
import { type Assessment, clock, longClock, oldestFact } from "./domain/view";
import { DataQuality } from "./ui/DataQuality";
import { Proposal } from "./ui/Proposal";
import { ProposalDetail } from "./ui/ProposalDetail";
import { BedBoard, Queue, ReleaseBoard, type StripTarget, TensionStrip } from "./ui/Unit";
import { UnitSwitcher } from "./ui/UnitSwitcher";
import { Fresh, Toast, useNow } from "./ui/common";
import { Alert, BoardIcon, Info, Mark, PulseIcon, ScalesIcon } from "./ui/icons";

type Route = "unite" | "proposition" | "donnees";

function readRoute(): Route {
  const hash = window.location.hash.replace(/^#\/?/, "");
  return hash === "proposition" || hash === "donnees" ? hash : "unite";
}

function go(route: Route) {
  window.location.hash = route === "unite" ? "/" : `/${route}`;
}

function useRoute(): Route {
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
  { id: "donnees", href: "#/donnees", label: "Données", key: "Q", Icon: () => <PulseIcon /> },
];

const ORIGIN: Record<Connection, string> = {
  probing: "Connexion…",
  "api-live": "API locale, unité en direct",
  "api-plan": "API locale, unités fictives",
  fixture: "Démonstration, données fictives",
};

const TITLES: Record<Route, string> = {
  unite: "Unité",
  proposition: "Proposition",
  donnees: "Qualité des données",
};

const SHORTCUTS: Array<[string, string]> = [
  ["U", "Changer d'unité"],
  ["1 à 9", "Aller directement à l'unité n"],
  ["O", "Je l'aurais fait"],
  ["N", "Je ne l'aurais pas fait, puis 1 à 6 pour le motif"],
  ["R", "Réévaluer l'unité"],
  ["A", "Vue unité"],
  ["D", "Détail de la proposition"],
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
  const route = useRoute();
  const [toast, setToast] = useState<string | null>(null);
  const [switcherSignal, setSwitcherSignal] = useState(0);
  const help = useRef<HTMLDialogElement>(null);
  const clearToast = useCallback(() => setToast(null), []);
  const openSwitcher = useCallback(() => setSwitcherSignal((n) => n + 1), []);
  const openHelp = useCallback(() => help.current?.showModal(), []);
  const a = store.assessment;
  const now = useNow(a, store.loadedAt);

  useEffect(() => {
    document.title = `${store.unitName} · ${TITLES[route]} · HospitalOS`;
  }, [route, store.unitName]);

  // Announce a unit change made by the person (switcher or digit key), not the initial load.
  const selectUnit = useCallback(
    (id: string) => {
      if (id === store.unitId) return;
      store.setUnit(id);
      const name = store.units.find((u) => u.id === id)?.name;
      if (name) setToast(`Unité affichée : ${name}`);
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
              title="Mode observation : HospitalOS propose, n'envoie rien et ne réserve rien."
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
              {ORIGIN[store.connection]}. Propositions et contrôles calculés par le vrai planificateur.
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
            onToast={setToast}
          />
        )}
      </main>

      <footer className="foot">
        <span>Prototype local en mode observation. Les propositions restent hors décision de soin.</span>
        <span>Identifiants pseudonymes, aucune donnée nominative.</span>
      </footer>

      <nav className="tabbar" aria-label="Sections">
        {ROUTES.map(({ id, href, label, Icon }) => (
          <a key={id} href={href} aria-current={route === id ? "page" : undefined}>
            <Icon />
            {label}
          </a>
        ))}
      </nav>

      <dialog ref={help} className="help" aria-labelledby="help-title">
        <h2 id="help-title">Raccourcis clavier</h2>
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
      <Toast message={toast} onDone={clearToast} />
    </div>
  );
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
  onToast: (m: string) => void;
}) {
  const { a } = props;
  const oldest = oldestFact(a);
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
      <h1 className="visually-hidden">Unité, état de {clock(a.state.at)}</h1>
      <TensionStrip a={a} onJump={jump} />
      <Proposal {...props} />
      <p className="freshline">
        État reconstruit pour le {longClock(a.state.at)}
        {oldest ? (
          <>
            {" "}
            · information la plus ancienne <Fresh f={oldest} />
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
