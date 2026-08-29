import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Bell, Building2, ChevronDown, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Navigate, NavLink, Route, BrowserRouter as Router, Routes } from "react-router-dom";

import { formatHeaderDateTime } from "./app/dateTime";
import { isResearchMode } from "./app/research";
import { legacyNavigationItem, navigationItems, researchNavigationItems } from "./app/navigation";
import { ScenarioProvider, useScenarioContext } from "./domain/ScenarioContext";
import { LegacyDashboard } from "./legacy/LegacyDashboard";
import { ActionEngine } from "./routes/ActionEngine";
import { Actions } from "./routes/Actions";
import { Beds } from "./routes/Beds";
import { ComponentGallery } from "./routes/ComponentGallery";
import { ForecastDetail } from "./routes/ForecastDetail";
import { History } from "./routes/History";
import { Insights, Situations } from "./routes/Insights";
import { ModifyInsight } from "./routes/ModifyInsight";
import { OrEd } from "./routes/OrEd";
import { Overview } from "./routes/Overview";
import { PatientFlow } from "./routes/PatientFlow";
import { PressureForecast } from "./routes/PressureForecast";
import { Reports } from "./routes/Reports";
import { Simulation } from "./routes/Simulation";
import { Staffing } from "./routes/Staffing";
import { getResearchUnit, RESEARCH_HORIZONS, RESEARCH_UNITS, type ResearchHorizonHours, type ResearchUnitId } from "./research/hclTargetScenario";

const queryClient = new QueryClient();

export function AppShell() {
  const researchMode = isResearchMode();
  const items = researchMode ? researchNavigationItems : navigationItems;
  const LegacyIcon = legacyNavigationItem.icon;

  return (
    <div className="min-h-screen bg-bg-app text-text-body">
      <aside className={`fixed inset-y-0 left-0 flex ${researchMode ? "w-[204px]" : "w-[230px]"} flex-col bg-brand-navy text-white`} aria-label="Navigation principale">
        <div className="border-b border-white/10 px-6 py-6">
          <div className="text-card-label text-brand-primary">HospitalOS</div>
        </div>
        <nav className="flex-1 px-3 py-4" aria-label="Écrans HospitalOS">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === "/situations" || item.path === "/insights" || item.path === "/"}
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
          {!researchMode ? (
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
          ) : null}
        </nav>
        {researchMode ? (
          <div className="m-3 border-t border-white/10 px-2 pb-2 pt-4 text-[11px] leading-[1.45] text-white/70" role="note">
            <div className="font-semibold text-brand-primary">Prototype de recherche</div>
            <p className="mt-1">Scénario simulé · aucune donnée HCL · aucune action hospitalière exécutée</p>
          </div>
        ) : (
          <div className="m-4 rounded-card border border-white/10 bg-white/5 p-4 text-[12.5px] leading-[1.35] text-white/70">
            <div className="flex items-center gap-2 font-semibold text-white">
              <span className="h-2 w-2 rounded-full bg-status-good" aria-hidden="true" />
              All systems operational
            </div>
            <p className="mt-2">Data freshness 2 min ago</p>
            <a className="mt-4 block text-brand-primary hover:underline" href="mailto:feedback@hospitalos.local">Feedback</a>
          </div>
        )}
      </aside>

      <div className={researchMode ? "ml-[204px] min-h-screen" : "ml-[230px] min-h-screen"}>
        {researchMode ? (
          <ResearchContextHeader />
        ) : (
          <header className="flex h-20 items-center justify-between border-b border-border-subtle bg-bg-card px-8">
            <button className="flex items-center gap-2 rounded-full border border-border-subtle bg-bg-card px-4 py-2 text-[13px] font-medium text-text-strong shadow-sm">
              <Building2 className="h-4 w-4 text-brand-primary" aria-hidden="true" />
              Cityview Medical Center
              <ChevronDown className="h-4 w-4 text-text-muted" aria-hidden="true" />
            </button>
            <label className="sr-only" htmlFor="global-search">Search</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" aria-hidden="true" />
              <input id="global-search" className="h-11 w-[420px] rounded-full border border-border-subtle bg-bg-app px-11 text-[13px] text-text-body outline-none focus:border-brand-primary" placeholder="Search units, actions, reports..." type="search" />
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
        )}

        <main className="p-8">
          <Routes>
            <Route path="/" element={researchMode ? <Navigate to="/situations" replace /> : <Overview />} />
            <Route path="/situations" element={<Situations />} />
            <Route path="/situations/:insightId" element={<Situations />} />
            <Route path="/situations/:insightId/forecast" element={<ForecastDetail />} />
            <Route path="/situations/:insightId/modify" element={<ModifyInsight />} />
            <Route path="/insights" element={<Insights />} />
            <Route path="/insights/:insightId" element={<Insights />} />
            <Route path="/insights/:insightId/forecast" element={<ForecastDetail />} />
            <Route path="/insights/:insightId/modify" element={<ModifyInsight />} />
            <Route path="/actions" element={researchMode ? <Actions /> : <ActionEngine />} />
            <Route path="/history" element={<History />} />
            <Route path="/forecast" element={<PressureForecast />} />
            <Route path="/simulation" element={<Simulation />} />
            <Route path="/beds" element={<Beds />} />
            <Route path="/staffing" element={<Staffing />} />
            <Route path="/flow" element={<PatientFlow />} />
            <Route path="/or-ed" element={<OrEd />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/dev/components" element={<ComponentGallery />} />
            <Route path="/legacy" element={<LegacyDashboard />} />
            <Route path="/action-engine" element={<ActionEngine />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

function ResearchContextHeader() {
  const { selectedUnitId, horizonHours, setSelectedUnit, setHorizonHours } = useScenarioContext();
  const [now, setNow] = useState(() => new Date());
  const [openControl, setOpenControl] = useState<"unit" | "horizon" | null>(null);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <header className="flex min-h-20 flex-wrap items-center gap-x-8 gap-y-3 border-b border-border-subtle bg-bg-card px-8 py-3">
      <div className="min-w-[220px] space-y-2">
        <time className="text-card-label text-brand-primary" dateTime={now.toISOString()}>{formatHeaderDateTime(now)}</time>
        <ContextDropdown<ResearchUnitId>
          label="Unité"
          ariaLabel="Unité hospitalière"
          value={selectedUnitId}
          valueLabel={getResearchUnit(selectedUnitId).label}
          options={RESEARCH_UNITS.map((unit) => ({ value: unit.id, label: unit.label }))}
          open={openControl === "unit"}
          onToggle={() => setOpenControl((current) => current === "unit" ? null : "unit")}
          onChange={(value) => { setSelectedUnit(value); setOpenControl(null); }}
        />
      </div>
      <div className="ml-auto">
        <ContextDropdown<ResearchHorizonHours>
          label="Horizon"
          ariaLabel="Horizon de prévision"
          value={horizonHours}
          valueLabel={`${horizonHours} h`}
          options={RESEARCH_HORIZONS.map((horizon) => ({ value: horizon, label: `${horizon} h` }))}
          open={openControl === "horizon"}
          onToggle={() => setOpenControl((current) => current === "horizon" ? null : "horizon")}
          onChange={(value) => { setHorizonHours(value); setOpenControl(null); }}
        />
      </div>
    </header>
  );
}

function ContextDropdown<T extends string | number>({ label, ariaLabel, value, valueLabel, options, open, onToggle, onChange }: { label: string; ariaLabel: string; value: T; valueLabel: string; options: Array<{ value: T; label: string }>; open: boolean; onToggle: () => void; onChange: (value: T) => void }) {
  return <div className="relative min-w-[170px]" onKeyDown={(event) => { if (event.key === "Escape" && open) onToggle(); }}>
    <span className="pointer-events-none absolute -top-2 left-3 z-10 bg-bg-card px-1 text-[10px] font-medium text-brand-primary">{label}</span>
    <button type="button" aria-label={ariaLabel} aria-haspopup="listbox" aria-expanded={open} onClick={onToggle} className={`flex h-12 w-full items-center justify-between gap-3 rounded-xl border bg-bg-card px-4 pt-1 text-body-strong text-text-strong outline-none transition focus-visible:ring-2 focus-visible:ring-brand-primary/15 ${open ? "border-brand-primary" : "border-border-subtle"}`}>
      {valueLabel}<ChevronDown className={`h-4 w-4 text-text-muted transition ${open ? "rotate-180" : ""}`} aria-hidden="true" />
    </button>
    {open ? <div role="listbox" aria-label={`${label} disponible`} className="absolute right-0 top-14 z-40 min-w-[210px] overflow-hidden rounded-xl border border-border-subtle bg-bg-card py-1 shadow-xl">
      {options.map((option) => <button key={String(option.value)} type="button" role="option" aria-selected={option.value === value} onClick={() => onChange(option.value)} className={`block w-full px-4 py-2.5 text-left text-body-copy outline-none hover:bg-bg-app focus-visible:bg-bg-app ${option.value === value ? "font-semibold text-brand-primary" : "text-text-body"}`}>{option.label}</button>)}
    </div> : null}
  </div>;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <ScenarioProvider>
          <AppShell />
        </ScenarioProvider>
      </Router>
    </QueryClientProvider>
  );
}
