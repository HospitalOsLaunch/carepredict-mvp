import {
  Activity,
  BedDouble,
  Bot,
  BedSingle,
  Building2,
  FileUp,
  Gauge,
  Inbox,
  LogOut,
  RadioTower,
  Settings,
  Siren,
  TrendingUp
} from "lucide-react";
import { Suspense, useEffect } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "./auth";
import { LegacyAgentsRedirect } from "./components/LegacyAgentsRedirect";
import { Mark } from "./components/Mark";
import { MobileNav, primaryFor, type NavItem } from "./components/MobileNav";
import { PageBoundary } from "./components/PageBoundary";
import { Spinner } from "./components/common";
import { lazyPage, whenIdle, type LazyPage } from "./lib/lazyPage";
import { LoginPage } from "./pages/LoginPage";

// Each screen is its own file, downloaded when it is first opened: the first screen after
// login no longer waits for the code of the eleven others (règle 22 de l'audit).
const RequestsPage = lazyPage(() => import("./pages/RequestsPage"), "RequestsPage");
const BedsPage = lazyPage(() => import("./pages/BedsPage"), "BedsPage");
const BedBoardPage = lazyPage(() => import("./pages/BedBoardPage"), "BedBoardPage");
const UrgencesPage = lazyPage(() => import("./pages/UrgencesPage"), "UrgencesPage");
const PrevisionPage = lazyPage(() => import("./pages/PrevisionPage"), "PrevisionPage");
const ChargePage = lazyPage(() => import("./pages/ChargePage"), "ChargePage");
const GroupPage = lazyPage(() => import("./pages/GroupPage"), "GroupPage");
const MetricsPage = lazyPage(() => import("./pages/MetricsPage"), "MetricsPage");
const RorPage = lazyPage(() => import("./pages/RorPage"), "RorPage");
const AgentsPage = lazyPage(() => import("./pages/AgentsPage"), "AgentsPage");
const AgentReplayPage = lazyPage(() => import("./pages/AgentReplayPage"), "AgentReplayPage");
const ImportsPage = lazyPage(() => import("./pages/ImportsPage"), "ImportsPage");
const SettingsPage = lazyPage(() => import("./pages/SettingsPage"), "SettingsPage");

/** The file of each menu entry, fetched ahead on hover or focus of its link. */
const PAGE_OF: Record<string, LazyPage> = {
  "/demandes": RequestsPage,
  "/lits": BedsPage,
  "/plan-des-lits": BedBoardPage,
  "/urgences": UrgencesPage,
  "/prevision": PrevisionPage,
  "/charge": ChargePage,
  "/groupe": GroupPage,
  "/indicateurs": MetricsPage,
  "/ror": RorPage,
  "/agents": AgentsPage,
  "/imports": ImportsPage,
  "/parametres": SettingsPage
};

function preloadPage(to: string) {
  void PAGE_OF[to]?.preload().catch(() => undefined);
  // From Agents, the next step is watching a passage: its player comes along.
  if (to === "/agents") void AgentReplayPage.preload().catch(() => undefined);
}

const NAV: NavItem[] = [
  { to: "/demandes", label: "Demandes", icon: Inbox },
  { to: "/lits", label: "Lits et sorties", short: "Sorties", icon: BedDouble },
  { to: "/plan-des-lits", label: "Plan des lits", short: "Lits", icon: BedSingle },
  { to: "/urgences", label: "Urgences et tension", short: "Urgences", icon: Siren },
  { to: "/prevision", label: "Prévision", icon: TrendingUp },
  { to: "/charge", label: "Charge en soins", icon: Activity },
  { to: "/groupe", label: "Vue groupe", short: "Groupe", icon: Building2 },
  { to: "/indicateurs", label: "Indicateurs pilote", short: "Indicateurs", icon: Gauge },
  { to: "/ror", label: "Remontée ROR", icon: RadioTower },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/imports", label: "Imports", icon: FileUp, admin: true },
  { to: "/parametres", label: "Paramètres", icon: Settings, admin: true }
];

export function App() {
  const { user, ready, groupName, logout, isAdmin } = useAuth();
  const { pathname } = useLocation();
  const primary = primaryFor(user?.role);
  // Once the first screen is shown, the persona's other daily screens are fetched in the background.
  useEffect(() => {
    if (!user || user.role === "ingestion") return;
    return whenIdle(() => primary.forEach(preloadPage));
  }, [user, primary]);
  if (!ready) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner />
      </div>
    );
  }
  if (!user) return <LoginPage />;
  if (user.role === "ingestion") {
    return (
      <div className="grid min-h-screen place-items-center p-6">
        <div className="panel max-w-md p-8">
          <h1>Compte de service</h1>
          <p className="mt-3 text-ink-soft">
            Ce compte sert à l'agent qui dépose les demandes reçues. Il n'a pas accès à l'interface.
          </p>
          <button className="btn-quiet mt-6" onClick={logout}>
            Se déconnecter
          </button>
        </div>
      </div>
    );
  }
  const items = NAV.filter((item) => !item.admin || isAdmin);
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[248px_1fr]">
      <a href="#contenu" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-xl focus:bg-paper focus:px-4 focus:py-2">
        Aller au contenu
      </a>
      <aside className="sticky top-0 z-20 flex flex-col border-b border-line bg-paper/90 backdrop-blur lg:h-screen lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-3 px-4 py-3 lg:px-5 lg:py-6">
          <Mark />
          <div className="min-w-0">
            <p className="font-display text-[17px] font-bold leading-tight">HospitalOS</p>
            <p className="truncate text-[13px] text-ink-faint">{groupName}</p>
          </div>
          <button className="btn-ghost ml-auto h-9 w-9 p-0 lg:hidden" onClick={logout} aria-label="Se déconnecter">
            <LogOut className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <nav aria-label="Navigation principale" className="hidden px-3 lg:block lg:flex-1">
          <ul className="flex gap-1 lg:flex-col">
            {items.map(({ to, label, icon: Icon }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  onPointerEnter={() => preloadPage(to)}
                  onFocus={() => preloadPage(to)}
                  className={({ isActive }) =>
                    `flex items-center gap-3 whitespace-nowrap rounded-xl px-3 py-2.5 text-[15px] font-bold transition-colors ${
                      isActive ? "bg-violet text-white" : "text-ink-soft hover:bg-sky hover:text-ink"
                    }`
                  }
                >
                  <Icon className="h-[18px] w-[18px]" aria-hidden />
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="hidden border-t border-line px-5 py-4 lg:block">
          <p className="truncate text-[15px] font-bold">{user.full_name}</p>
          <p className="truncate text-[13px] text-ink-faint">{user.email}</p>
          <button className="btn-quiet mt-3 w-full" onClick={logout}>
            <LogOut className="h-4 w-4" aria-hidden /> Se déconnecter
          </button>
        </div>
      </aside>
      <MobileNav items={items} primary={primary} onIntent={preloadPage} />
      <main id="contenu" className="min-w-0 px-4 pb-28 pt-6 sm:px-6 lg:px-10 lg:py-9">
        <PageBoundary resetKey={pathname}>
          <Suspense fallback={<Spinner label="Chargement de l'écran" />}>
            <Routes>
              <Route path="/" element={<Navigate to="/demandes" replace />} />
              <Route path="/demandes" element={<RequestsPage />} />
              <Route path="/demandes/:id" element={<RequestsPage />} />
              <Route path="/lits" element={<BedsPage />} />
              <Route path="/plan-des-lits" element={<BedBoardPage />} />
              <Route path="/urgences" element={<UrgencesPage />} />
              <Route path="/prevision" element={<PrevisionPage />} />
              <Route path="/charge" element={<ChargePage />} />
              <Route path="/groupe" element={<GroupPage />} />
              <Route path="/indicateurs" element={<MetricsPage />} />
              <Route path="/ror" element={<RorPage />} />
              {/* The player opens in a window over the Agents screen; its address can be shared.
                  Its own Suspense keeps the Agents screen in place while the player file arrives. */}
              <Route path="/agents" element={<AgentsPage />}>
                <Route
                  path="passages/:taskId"
                  element={
                    <Suspense fallback={null}>
                      <AgentReplayPage />
                    </Suspense>
                  }
                />
              </Route>
              <Route path="/computer-use/*" element={<LegacyAgentsRedirect />} />
              {isAdmin && <Route path="/imports" element={<ImportsPage />} />}
              {isAdmin && <Route path="/parametres" element={<SettingsPage />} />}
              <Route path="*" element={<Navigate to="/demandes" replace />} />
            </Routes>
          </Suspense>
        </PageBoundary>
      </main>
    </div>
  );
}
