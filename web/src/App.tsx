import { useCallback, useEffect, useState } from "react";
import { type Connection, useAssessment } from "./data/useAssessment";
import { entityLabel } from "./domain/labels";
import { type Assessment, clock, longClock, oldestFact, situation } from "./domain/view";
import { DataQuality } from "./ui/DataQuality";
import { Proposal } from "./ui/Proposal";
import { ProposalDetail } from "./ui/ProposalDetail";
import { BedBoard, Queue, ReleaseBoard } from "./ui/Unit";
import { Fresh, Toast, plural, useNow } from "./ui/common";
import { Alert, BoardIcon, Info, Mark, PulseIcon, ScalesIcon } from "./ui/icons";

type Route = "unite" | "proposition" | "donnees";

function readRoute(): Route {
  const hash = window.location.hash.replace(/^#\/?/, "");
  return hash === "proposition" || hash === "donnees" ? hash : "unite";
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

const ROUTES: Array<{ id: Route; href: string; label: string; Icon: () => JSX.Element }> = [
  { id: "unite", href: "#/", label: "Unité", Icon: () => <BoardIcon /> },
  { id: "proposition", href: "#/proposition", label: "Proposition", Icon: () => <ScalesIcon /> },
  { id: "donnees", href: "#/donnees", label: "Données", Icon: () => <PulseIcon /> },
];

const ORIGIN: Record<Connection, string> = {
  probing: "Connexion…",
  "api-live": "API locale, unité en direct",
  "api-plan": "API locale, scénarios fictifs",
  fixture: "Démonstration, données fictives",
};

const TITLES: Record<Route, string> = {
  unite: "Unité",
  proposition: "Proposition",
  donnees: "Qualité des données",
};

export function App() {
  const store = useAssessment();
  const route = useRoute();
  const [toast, setToast] = useState<string | null>(null);
  const clearToast = useCallback(() => setToast(null), []);
  const a = store.assessment;
  const now = useNow(a, store.loadedAt);

  useEffect(() => {
    document.title = `${TITLES[route]} · Cockpit HospitalOS`;
  }, [route]);

  const unitName = "Médecine polyvalente";

  return (
    <div className="shell">
      <a className="skip" href="#contenu">
        Aller au contenu
      </a>
      <header className="topbar">
        <div className="topbar__row">
          <div className="brand">
            <Mark />
            <span translate="no">HospitalOS</span>
          </div>
          <div className="unitname">
            <strong>{unitName}</strong>
            <span>{a ? `État de ${clock(a.state.at)}` : "Chargement…"}</span>
          </div>
          <nav className="nav" aria-label="Sections">
            {ROUTES.map((r) => (
              <a key={r.id} href={r.href} aria-current={route === r.id ? "page" : undefined}>
                {r.label}
              </a>
            ))}
          </nav>
          <div className="topbar__end">
            <div className="origin">
              <label className="origin__label" htmlFor="scenario">
                {ORIGIN[store.connection]}
              </label>
              {store.scenarios.length > 1 ? (
                <select
                  id="scenario"
                  className="select"
                  value={store.scenarioId}
                  onChange={(e) => store.setScenario(e.target.value)}
                  aria-label={`Source : ${ORIGIN[store.connection]}. Scénario`}
                >
                  {store.scenarios.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
              ) : null}
            </div>
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
        {store.connection === "fixture" && a ? (
          <div className="notice">
            <Info />
            <span>
              Démonstration : unité et patients fictifs. Les propositions, étapes de sortie et contrôles sont
              ceux calculés par le vrai planificateur sur ces données.
            </span>
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
        <span>Prototype local, mode observation. Recommandations hors décision de soin.</span>
        <span>Identifiants pseudonymes ; aucune donnée nominative.</span>
      </footer>

      <nav className="tabbar" aria-label="Sections">
        {ROUTES.map(({ id, href, label, Icon }) => (
          <a key={id} href={href} aria-current={route === id ? "page" : undefined}>
            <Icon />
            {label}
          </a>
        ))}
      </nav>
      <Toast message={toast} onDone={clearToast} />
    </div>
  );
}

function UnitPage(props: {
  a: Assessment;
  now: string;
  busy: boolean;
  awaitingEvaluation: boolean;
  onEvaluate: () => void;
  onToast: (m: string) => void;
}) {
  const { a } = props;
  const s = situation(a.state, a.plan);
  const oldest = oldestFact(a);
  return (
    <>
      <div className="situation">
        <h1 className="situation__line">
          <b>{plural(s.waiting, "patient attend", "patients attendent")}</b> un lit.{" "}
          {s.usable === 0 ? (
            <>Aucun lit n'est utilisable maintenant</>
          ) : (
            <>
              <b>{plural(s.usable, "lit est utilisable", "lits sont utilisables")}</b> maintenant
            </>
          )}
          {s.dirty ? <>, {plural(s.dirty, "est à nettoyer", "sont à nettoyer")}</> : null}.{" "}
          <b>{plural(s.departuresPrepared, "sortie", "sorties")}</b> en préparation.
        </h1>
        <p className="situation__meta">
          État reconstruit pour le <strong>{longClock(a.state.at)}</strong>
          {oldest ? (
            <>
              <br />
              Information la plus ancienne : {entityLabel(oldest.key)}, <Fresh f={oldest} />
            </>
          ) : null}
        </p>
      </div>
      <div className="cockpit">
        <div className="stack">
          <Proposal {...props} />
          <ReleaseBoard a={a} />
        </div>
        <div className="stack">
          <Queue a={a} />
          <BedBoard a={a} />
        </div>
      </div>
    </>
  );
}
