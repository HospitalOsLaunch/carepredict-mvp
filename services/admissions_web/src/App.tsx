import { Activity, BedDouble, Building2, FileUp, Gauge, Inbox, LogOut, Settings } from "lucide-react";
import { lazy, Suspense, type ComponentType } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";

import { useAuth } from "./auth";
import { Mark } from "./components/Mark";
import { Spinner } from "./components/ui";
import { BedsPage } from "./pages/BedsPage";
import { GroupPage } from "./pages/GroupPage";
import { ImportsPage } from "./pages/ImportsPage";
import { LoginPage } from "./pages/LoginPage";
import { RequestsPage } from "./pages/RequestsPage";
import { SettingsPage } from "./pages/SettingsPage";

const ChargePage = lazy(() => import("./pages/ChargePage").then((m) => ({ default: m.ChargePage })));
const MetricsPage = lazy(() => import("./pages/MetricsPage").then((m) => ({ default: m.MetricsPage })));

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  admin?: boolean;
}

const NAV: NavItem[] = [
  { to: "/demandes", label: "Demandes", icon: Inbox },
  { to: "/lits", label: "Lits et sorties", icon: BedDouble },
  { to: "/charge", label: "Charge en soins", icon: Activity },
  { to: "/groupe", label: "Vue groupe", icon: Building2 },
  { to: "/indicateurs", label: "Indicateurs pilote", icon: Gauge },
  { to: "/imports", label: "Imports", icon: FileUp, admin: true },
  { to: "/parametres", label: "Paramètres", icon: Settings, admin: true }
];

export function App() {
  const { user, ready, groupName, logout, isAdmin } = useAuth();
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
        <div className="flex items-center gap-3 px-5 py-4 lg:py-6">
          <Mark />
          <div className="min-w-0">
            <p className="font-display text-[17px] font-bold leading-tight">HospitalOS</p>
            <p className="truncate text-[13px] text-ink-faint">{groupName}</p>
          </div>
          <button className="btn-ghost ml-auto h-9 w-9 p-0 lg:hidden" onClick={logout} aria-label="Se déconnecter">
            <LogOut className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <nav aria-label="Navigation principale" className="overflow-x-auto px-3 pb-3 lg:flex-1 lg:pb-0">
          <ul className="flex gap-1 lg:flex-col">
            {items.map(({ to, label, icon: Icon }) => (
              <li key={to}>
                <NavLink
                  to={to}
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
      <main id="contenu" className="min-w-0 px-4 py-6 sm:px-6 lg:px-10 lg:py-9">
        <Routes>
          <Route path="/" element={<Navigate to="/demandes" replace />} />
          <Route path="/demandes" element={<RequestsPage />} />
          <Route path="/demandes/:id" element={<RequestsPage />} />
          <Route path="/lits" element={<BedsPage />} />
          <Route
            path="/charge"
            element={
              <Suspense fallback={<Spinner />}>
                <ChargePage />
              </Suspense>
            }
          />
          <Route path="/groupe" element={<GroupPage />} />
          <Route
            path="/indicateurs"
            element={
              <Suspense fallback={<Spinner />}>
                <MetricsPage />
              </Suspense>
            }
          />
          {isAdmin && <Route path="/imports" element={<ImportsPage />} />}
          {isAdmin && <Route path="/parametres" element={<SettingsPage />} />}
          <Route path="*" element={<Navigate to="/demandes" replace />} />
        </Routes>
      </main>
    </div>
  );
}
