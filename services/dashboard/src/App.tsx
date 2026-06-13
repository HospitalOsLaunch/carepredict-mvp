import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Bell, Building2, ChevronDown, Search } from "lucide-react";
import { NavLink, Route, BrowserRouter as Router, Routes } from "react-router-dom";

import { legacyNavigationItem, navigationItems } from "./app/navigation";
import { LegacyDashboard } from "./legacy/LegacyDashboard";
import { ActionEngine } from "./routes/ActionEngine";
import { Beds } from "./routes/Beds";
import { ComponentGallery } from "./routes/ComponentGallery";
import { OrEd } from "./routes/OrEd";
import { Overview } from "./routes/Overview";
import { PatientFlow } from "./routes/PatientFlow";
import { PressureForecast } from "./routes/PressureForecast";
import { Reports } from "./routes/Reports";
import { Simulation } from "./routes/Simulation";
import { Staffing } from "./routes/Staffing";

const queryClient = new QueryClient();

function AppShell() {
  const LegacyIcon = legacyNavigationItem.icon;

  return (
    <div className="min-h-screen bg-bg-app text-text-body">
      <aside className="fixed inset-y-0 left-0 flex w-[230px] flex-col bg-brand-navy text-white" aria-label="Primary">
        <div className="border-b border-white/10 px-6 py-6">
          <div className="text-card-label text-brand-primary">HospitalOS</div>
          <div className="mt-1 text-lg font-bold text-white">Command</div>
        </div>
        <nav className="flex-1 px-3 py-4" aria-label="HospitalOS screens">
          {navigationItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === "/"}
                className={({ isActive }) =>
                  [
                    "mb-1 flex items-center gap-3 rounded-xl border-l-4 px-3 py-3 text-[13px] font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-brand-primary",
                    isActive
                      ? "border-brand-primary bg-white/10 text-white"
                      : "border-transparent text-white/70 hover:bg-white/5 hover:text-white"
                  ].join(" ")
                }
              >
                <Icon aria-hidden="true" className="h-[18px] w-[18px] text-brand-primary" strokeWidth={2.2} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
          <NavLink
            to={legacyNavigationItem.path}
            className={({ isActive }) =>
              [
                "mt-4 flex items-center gap-3 rounded-xl border-l-4 px-3 py-3 text-[13px] font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-brand-primary",
                isActive
                  ? "border-brand-primary bg-white/10 text-white"
                  : "border-transparent text-white/60 hover:bg-white/5 hover:text-white"
              ].join(" ")
            }
          >
            <LegacyIcon aria-hidden="true" className="h-[18px] w-[18px] text-brand-primary" strokeWidth={2.2} />
            <span>{legacyNavigationItem.label}</span>
          </NavLink>
        </nav>
        <div className="m-4 rounded-card border border-white/10 bg-white/5 p-4 text-[12.5px] leading-[1.35] text-white/70">
          <div className="flex items-center gap-2 font-semibold text-white">
            <span className="h-2 w-2 rounded-full bg-status-good" aria-hidden="true" />
            All systems operational
          </div>
          <p className="mt-2">Data freshness 2 min ago</p>
          <a className="mt-4 block text-brand-primary hover:underline" href="mailto:feedback@hospitalos.local">
            Feedback
          </a>
        </div>
      </aside>

      <div className="ml-[230px] min-h-screen">
        <header className="flex h-20 items-center justify-between border-b border-border-subtle bg-bg-card px-8">
          <button className="flex items-center gap-2 rounded-full border border-border-subtle bg-bg-card px-4 py-2 text-[13px] font-medium text-text-strong shadow-sm">
            <Building2 className="h-4 w-4 text-brand-primary" aria-hidden="true" />
            Cityview Medical Center
            <ChevronDown className="h-4 w-4 text-text-muted" aria-hidden="true" />
          </button>
          <label className="sr-only" htmlFor="global-search">
            Search
          </label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" aria-hidden="true" />
            <input
              id="global-search"
              className="h-11 w-[420px] rounded-full border border-border-subtle bg-bg-app px-11 text-[13px] text-text-body outline-none focus:border-brand-primary"
              placeholder="Search units, actions, reports..."
              type="search"
            />
          </div>
          <div className="flex items-center gap-4">
            <time className="text-caption">Today · Live operations</time>
            <button className="relative rounded-full border border-border-subtle p-2 text-text-body" aria-label="Notifications">
              <Bell className="h-5 w-5" aria-hidden="true" />
              <span className="numeric-tabular absolute -right-1 -top-1 rounded-full bg-status-critical px-1.5 text-[10px] font-bold text-white">3</span>
            </button>
            <div className="rounded-full border border-border-subtle px-4 py-2 text-[13px]">
              <strong className="font-semibold text-text-strong">Sarah Johnson</strong>
              <span className="ml-2 text-text-muted">COO</span>
            </div>
          </div>
        </header>

        <main className="p-8">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/forecast" element={<PressureForecast />} />
            <Route path="/actions" element={<ActionEngine />} />
            <Route path="/simulation" element={<Simulation />} />
            <Route path="/beds" element={<Beds />} />
            <Route path="/staffing" element={<Staffing />} />
            <Route path="/flow" element={<PatientFlow />} />
            <Route path="/or-ed" element={<OrEd />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/dev/components" element={<ComponentGallery />} />
            <Route path="/legacy" element={<LegacyDashboard />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <AppShell />
      </Router>
    </QueryClientProvider>
  );
}
