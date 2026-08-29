import { useMemo, useState, type ReactNode } from "react";

import { useScenarioContext, type DecisionRecord } from "../domain/ScenarioContext";
import {
  classifyRiskLevel,
  formatRiskLevel,
  simulateDischargeScenario,
  type InsightRiskLevel,
} from "../domain/insights";
import {
  getResearchUnit,
  RESEARCH_UNITS,
  HCL_TARGET_PRODUCT_RESEARCH_SCENARIO as scenario,
} from "../research/hclTargetScenario";

type DecisionFilter = "all" | "accepted" | "modified" | "refused";
export type HistorySortKey = "created_desc" | "created_asc" | "impact_desc";

export interface HistoryRow {
  record: DecisionRecord;
  initialRisk: InsightRiskLevel;
  decisionLabel: "Acceptée" | "Modifiée puis validée" | "Refusée";
  peakDelta: number;
  hoursDelta: number;
}

export function History() {
  const { insight, auditEvents } = useScenarioContext();
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [draftDateFrom, setDraftDateFrom] = useState("");
  const [draftDateTo, setDraftDateTo] = useState("");
  const [periodOpen, setPeriodOpen] = useState(false);
  const [unitId, setUnitId] = useState("all");
  const [decisionFilter, setDecisionFilter] = useState<DecisionFilter>("all");
  const [risk, setRisk] = useState("all");
  const [reason, setReason] = useState("all");
  const [session, setSession] = useState("all");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<HistorySortKey>("created_desc");
  const [selectedRow, setSelectedRow] = useState<HistoryRow | null>(null);

  const rows = useMemo<HistoryRow[]>(() => auditEvents.map((record) => {
    const baseline = simulateDischargeScenario(0, record.horizonHours).summary;
    const selected = simulateDischargeScenario(
      record.selectedParameters.confirmed_discharges ?? 0,
      record.horizonHours,
    ).summary;
    return {
      record,
      initialRisk: classifyRiskLevel(insight.peakPressureSiips, insight.criticalHours),
      decisionLabel: record.decision === "dismissed"
        ? "Refusée"
        : record.decisionSource === "modified_scenario"
          ? "Modifiée puis validée"
          : "Acceptée",
      peakDelta: selected.peak - baseline.peak,
      hoursDelta: selected.criticalHours - baseline.criticalHours,
    };
  }), [auditEvents, insight]);

  const refusalReasons = useMemo(
    () => Array.from(new Set(rows.map((row) => row.record.reason).filter((value): value is string => Boolean(value)))),
    [rows],
  );
  const sessions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.record.researchSessionId))),
    [rows],
  );

  const filteredRows = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    return rows.filter((row) => {
      const recordDate = row.record.createdAt.slice(0, 10);
      const unit = getResearchUnit(row.record.unitId);
      const matchesDecision = decisionFilter === "all"
        || (decisionFilter === "accepted" && row.record.decision === "accepted" && row.record.decisionSource === "recommendation")
        || (decisionFilter === "modified" && row.record.decisionSource === "modified_scenario")
        || (decisionFilter === "refused" && row.record.decision === "dismissed");
      const matchesSearch = !normalizedSearch || `${insight.title} ${insight.recommendation.title} ${row.record.insightId} ${row.record.researchSessionId}`.toLowerCase().includes(normalizedSearch);
      return (!dateFrom || recordDate >= dateFrom)
        && (!dateTo || recordDate <= dateTo)
        && (unitId === "all" || unitId === unit.id)
        && matchesDecision
        && (risk === "all" || row.initialRisk === risk)
        && (reason === "all" || row.record.reason === reason)
        && (session === "all" || row.record.researchSessionId === session)
        && matchesSearch;
    });
  }, [dateFrom, dateTo, decisionFilter, insight, reason, risk, rows, search, session, unitId]);

  const sortedRows = useMemo(() => sortHistoryRows(filteredRows, sort), [filteredRows, sort]);
  const advancedFilterCount = [risk, reason, session].filter((value) => value !== "all").length;
  const filtersActive = Boolean(
    dateFrom || dateTo || unitId !== "all" || decisionFilter !== "all"
      || advancedFilterCount || search,
  );

  function resetAdvancedFilters() {
    setRisk("all");
    setReason("all");
    setSession("all");
  }

  function resetAllFilters() {
    setDateFrom("");
    setDateTo("");
    setDraftDateFrom("");
    setDraftDateTo("");
    setUnitId("all");
    setDecisionFilter("all");
    setSearch("");
    resetAdvancedFilters();
  }

  return <section className="mx-auto max-w-[1180px] space-y-7" aria-labelledby="history-title">
    <header className="flex flex-wrap items-end justify-between gap-5 border-b border-border-subtle pb-6">
      <div><p className="text-card-label text-brand-primary">Décisions enregistrées</p><h1 id="history-title" className="mt-2 text-3xl font-semibold tracking-tight text-text-strong">Historique</h1></div>
      <span className="text-caption">Lecture seule</span>
    </header>

    <div className="flex flex-wrap items-center gap-5 border-b border-border-subtle pb-3" role="tablist" aria-label="Type de décision">
      <HistoryTab label="Toutes" active={decisionFilter === "all"} onClick={() => setDecisionFilter("all")} />
      <HistoryTab label="Validées" active={decisionFilter === "accepted"} onClick={() => setDecisionFilter("accepted")} />
      <HistoryTab label="Modifiées" active={decisionFilter === "modified"} onClick={() => setDecisionFilter("modified")} />
      <HistoryTab label="Refusées" active={decisionFilter === "refused"} onClick={() => setDecisionFilter("refused")} />
    </div>

    <section className="space-y-4 border-b border-border-subtle pb-5" aria-label="Filtres de l'historique">
      <input
        aria-label="Rechercher dans l'historique"
        type="search"
        value={search}
        onChange={(event) => setSearch(event.currentTarget.value)}
        placeholder="Rechercher une situation ou une action"
        className="h-11 w-full rounded-lg border border-border-subtle bg-bg-card px-4 text-text-body"
      />
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative">
          <button type="button" aria-expanded={periodOpen} aria-controls="history-period-panel" onClick={() => setPeriodOpen((open) => !open)} className="h-10 rounded-lg border border-border-subtle bg-bg-card px-3 text-control text-text-body">
            {formatPeriodLabel(dateFrom, dateTo)} ▾
          </button>
          {periodOpen ? <div id="history-period-panel" className="absolute left-0 top-12 z-20 w-80 rounded-xl border border-border-subtle bg-bg-card p-4 shadow-xl">
            <h2 className="text-body-strong text-text-strong">Période</h2>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <label className="text-caption">Du<input aria-label="Du" type="date" value={draftDateFrom} onChange={(event) => setDraftDateFrom(event.currentTarget.value)} className="mt-1 h-10 w-full rounded-lg border border-border-subtle px-2 text-text-body" /></label>
              <label className="text-caption">Au<input aria-label="Au" type="date" value={draftDateTo} onChange={(event) => setDraftDateTo(event.currentTarget.value)} className="mt-1 h-10 w-full rounded-lg border border-border-subtle px-2 text-text-body" /></label>
            </div>
            <div className="mt-4 flex justify-end gap-3"><button type="button" className="text-control text-text-muted" onClick={() => { setDraftDateFrom(""); setDraftDateTo(""); setDateFrom(""); setDateTo(""); }}>Réinitialiser</button><button type="button" className="rounded-lg bg-brand-primary px-4 py-2 text-control text-white" onClick={() => { setDateFrom(draftDateFrom); setDateTo(draftDateTo); setPeriodOpen(false); }}>Appliquer</button></div>
          </div> : null}
        </div>
        <CompactSelect label="Unité" value={unitId} onChange={setUnitId} options={[["all", "Toutes les unités"], ...RESEARCH_UNITS.map((unit) => [unit.id, unit.label] as [string, string])]} />
        <CompactSelect label="Décision" value={decisionFilter} onChange={(value) => setDecisionFilter(value as DecisionFilter)} options={[["all", "Toutes"], ["accepted", "Validée"], ["modified", "Modifiée"], ["refused", "Refusée"]]} />
        <button type="button" aria-expanded={advancedOpen} onClick={() => { setPeriodOpen(false); setAdvancedOpen(true); }} className="h-10 rounded-lg border border-border-subtle bg-bg-card px-3 text-control text-text-body">+ Plus de filtres{advancedFilterCount ? ` · ${advancedFilterCount}` : ""}</button>
        <label className="ml-auto flex items-center gap-2 text-caption"><span className="sr-only">Trier l'historique</span><select aria-label="Trier l'historique" value={sort} onChange={(event) => setSort(event.currentTarget.value as HistorySortKey)} className="h-10 rounded-lg border border-border-subtle bg-bg-card px-3 text-text-body"><option value="created_desc">Plus récentes ↓</option><option value="created_asc">Plus anciennes ↑</option><option value="impact_desc">Impact le plus fort</option></select></label>
      </div>
    </section>

    <div className="overflow-x-auto border-y border-border-subtle bg-bg-card">
      <table className="min-w-[980px] w-full text-left text-body-copy">
        <caption className="sr-only">Journal des décisions</caption>
        <thead className="border-b border-border-subtle bg-bg-app text-caption"><tr><th className="px-4 py-3 font-semibold">Date</th><th className="px-4 py-3 font-semibold">Unité</th><th className="px-4 py-3 font-semibold">Situation</th><th className="px-4 py-3 font-semibold">Action</th><th className="px-4 py-3 font-semibold">Décision</th><th className="px-4 py-3 font-semibold">Option retenue</th><th className="px-4 py-3 font-semibold">Impact attendu</th></tr></thead>
        <tbody>{sortedRows.map((row) => <HistoryTableRow key={`${row.record.researchSessionId}-${row.record.timestamp}`} row={row} insight={insight} onOpen={() => setSelectedRow(row)} />)}</tbody>
      </table>
      {sortedRows.length === 0 ? <div className="p-8 text-center text-caption"><p className="font-medium text-text-strong">{filtersActive ? "Aucune décision ne correspond à ces filtres." : "Aucune décision enregistrée pour cette session."}</p>{filtersActive ? <><p className="mt-2">Modifiez ou réinitialisez les filtres pour élargir les résultats.</p><button type="button" className="mt-4 text-control text-brand-primary" onClick={resetAllFilters}>Réinitialiser les filtres</button></> : null}</div> : null}
    </div>

    {advancedOpen ? <AdvancedFiltersDrawer risk={risk} reason={reason} session={session} refusalReasons={refusalReasons} sessions={sessions} onRisk={setRisk} onReason={setReason} onSession={setSession} onReset={resetAdvancedFilters} onClose={() => setAdvancedOpen(false)} /> : null}
    {selectedRow ? <HistoryDrawer row={selectedRow} insight={insight} onClose={() => setSelectedRow(null)} /> : null}
  </section>;
}

export function sortHistoryRows(rows: HistoryRow[], sort: HistorySortKey): HistoryRow[] {
  return [...rows].sort((left, right) => {
    if (sort === "created_asc") return left.record.createdAt.localeCompare(right.record.createdAt);
    if (sort === "impact_desc") return Math.abs(right.peakDelta) - Math.abs(left.peakDelta);
    return right.record.createdAt.localeCompare(left.record.createdAt);
  });
}

function HistoryTableRow({ row, insight, onOpen }: { row: HistoryRow; insight: ReturnType<typeof useScenarioContext>["insight"]; onOpen: () => void }) {
  const selected = simulateDischargeScenario(row.record.selectedParameters.confirmed_discharges ?? 0, row.record.horizonHours).summary;
  const unit = getResearchUnit(row.record.unitId);
  return <tr tabIndex={0} className="cursor-pointer border-b border-border-subtle outline-none last:border-b-0 hover:bg-bg-app focus-visible:bg-bg-app" onClick={onOpen} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onOpen(); } }} aria-label={`Détail ${row.decisionLabel}`}><td className="whitespace-nowrap px-4 py-4 text-caption">{formatHistoryDate(row.record.createdAt)}</td><td className="px-4 py-4">{unit.label}</td><td className="px-4 py-4"><strong className="text-text-strong">{insight.title}</strong><span className="mt-1 block text-caption">{scenario.riskWindow.start}–{scenario.riskWindow.end}</span></td><td className="px-4 py-4">{insight.recommendation.title}</td><td className="px-4 py-4 font-medium">{row.decisionLabel}</td><td className="px-4 py-4">{row.record.selectedParameters.confirmed_discharges ?? 0} sorties</td><td className="px-4 py-4"><span className="block">Occupation {scenario.states.baseline.peakOccupancyPercent} → {selected.peakOccupancyPercent} %</span><span className="text-caption">{scenario.states.baseline.criticalHours} h → {selected.criticalHours} h · {formatSigned(row.peakDelta)} SIIPS</span></td></tr>;
}

function AdvancedFiltersDrawer({ risk, reason, session, refusalReasons, sessions, onRisk, onReason, onSession, onReset, onClose }: { risk: string; reason: string; session: string; refusalReasons: string[]; sessions: string[]; onRisk: (value: string) => void; onReason: (value: string) => void; onSession: (value: string) => void; onReset: () => void; onClose: () => void }) {
  return <div className="fixed inset-0 z-50 flex justify-end bg-brand-navy/40" role="presentation">
    <aside className="relative h-full w-full max-w-md border-l border-border-subtle bg-bg-card p-7 shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="advanced-filters-title">
      <div className="flex items-center justify-between">
        <h2 id="advanced-filters-title" className="text-xl font-semibold text-text-strong">Filtres avancés</h2>
        <button type="button" autoFocus aria-label="Fermer les filtres avancés" onClick={onClose} className="rounded-full p-2 text-text-muted focus-visible:ring-2 focus-visible:ring-brand-primary">×</button>
      </div>
      <div className="mt-7 space-y-5">
        <FilterSelect label="Risque initial" value={risk} onChange={onRisk} options={[["all", "Tous les risques"], ["low", "Faible"], ["moderate", "Modérée"], ["high", "Élevée"], ["critical", "Critique"]]} />
        <FilterSelect label="Motif de refus" value={reason} onChange={onReason} options={[["all", "Tous les motifs"], ...refusalReasons.map((item) => [item, item] as [string, string])]} />
        <FilterSelect label="Session de recherche" value={session} onChange={onSession} options={[["all", "Toutes les sessions"], ...sessions.map((item) => [item, "Session actuelle"] as [string, string])]} />
      </div>
      <footer className="absolute bottom-0 left-0 right-0 flex justify-end gap-3 border-t border-border-subtle bg-bg-card p-5">
        <button type="button" className="text-control text-text-muted" onClick={onReset}>Réinitialiser</button>
        <button type="button" className="rounded-lg bg-brand-primary px-4 py-2 text-control text-white" onClick={onClose}>Afficher les résultats</button>
      </footer>
    </aside>
  </div>;
}

function HistoryTab({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) { return <button type="button" role="tab" aria-selected={active} onClick={onClick} className={`border-b-2 pb-2 text-control ${active ? "border-brand-primary text-brand-primary" : "border-transparent text-text-muted"}`}>{label}</button>; }
function CompactSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: [string, string][] }) { return <label className="flex items-center gap-2 text-caption"><span>{label}</span><select aria-label={label} value={value} onChange={(event) => onChange(event.currentTarget.value)} className="h-10 rounded-lg border border-border-subtle bg-bg-card px-3 pr-8 text-control text-text-body">{options.map(([optionValue, optionLabel]) => <option key={optionValue} value={optionValue}>{optionLabel}</option>)}</select></label>; }
function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: [string, string][] }) { return <label className="block text-caption">{label}<select aria-label={label} value={value} onChange={(event) => onChange(event.currentTarget.value)} className="mt-1 h-10 w-full rounded-lg border border-border-subtle bg-bg-card px-3 text-text-body">{options.map(([optionValue, optionLabel]) => <option key={optionValue} value={optionValue}>{optionLabel}</option>)}</select></label>; }

function HistoryDrawer({ row, insight, onClose }: { row: HistoryRow; insight: ReturnType<typeof useScenarioContext>["insight"]; onClose: () => void }) {
  const baseline = simulateDischargeScenario(0, row.record.horizonHours).summary;
  const original = simulateDischargeScenario(row.record.originalParameters.confirmed_discharges ?? 0, row.record.horizonHours).summary;
  const selected = simulateDischargeScenario(row.record.selectedParameters.confirmed_discharges ?? 0, row.record.horizonHours).summary;
  const unit = getResearchUnit(row.record.unitId);
  return <div className="fixed inset-0 z-50 flex justify-end bg-brand-navy/40" role="presentation"><aside className="h-full w-full max-w-xl overflow-y-auto border-l border-border-subtle bg-bg-card p-7 shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="history-drawer-title"><div className="flex items-start justify-between gap-4"><div><p className="text-card-label text-brand-primary">Journal de décision</p><h2 id="history-drawer-title" className="mt-2 text-xl font-semibold text-text-strong">{row.decisionLabel}</h2></div><button type="button" autoFocus aria-label="Fermer le détail" className="rounded-full p-2 text-text-muted focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={onClose}>×</button></div><div className="mt-6 space-y-5 text-body-copy"><DetailBlock title="Situation initiale"><p className="font-semibold text-text-strong">{insight.title}</p><p className="mt-1">{unit.label} · tension {scenario.riskWindow.start}–{scenario.riskWindow.end}</p><p className="mt-1">Risque initial : {formatRiskLevel(row.initialRisk)}</p></DetailBlock><DetailBlock title="Recommandation originale"><p>{insight.recommendation.title}</p><p className="mt-1 text-caption">{insight.recommendation.rationale}</p></DetailBlock><DetailBlock title="Paramètres originaux"><p>{formatParameters(row.record.originalParameters)}</p></DetailBlock><DetailBlock title="Paramètres sélectionnés"><p>{formatParameters(row.record.selectedParameters)}</p></DetailBlock><DetailBlock title="Comparaison simulée"><p>Plan actuel : {baseline.peakOccupancyPercent} % d'occupation · {baseline.criticalHours} h</p><p>Recommandation : {original.peakOccupancyPercent} % · {original.criticalHours} h</p><p>Option retenue : {selected.peakOccupancyPercent} % · {selected.criticalHours} h · {selected.peakSiips} SIIPS</p></DetailBlock><DetailBlock title="Décision humaine"><p>{row.decisionLabel}</p>{row.record.reason ? <p className="mt-1">Motif : {row.record.reason}</p> : null}<p className="mt-1">Date / heure : {formatHistoryDateTime(row.record.timestamp)}</p></DetailBlock><details className="border-t border-border-subtle pt-4"><summary className="cursor-pointer text-body-strong text-text-strong">Détails techniques</summary><p className="mt-3 text-caption">Identifiant de situation : {scenario.scenarioId}</p><p className="mt-1 text-caption">Session de recherche : {row.record.researchSessionId}</p><p className="mt-1 text-caption">Horizon enregistré : {row.record.horizonHours} h</p><p className="mt-1 text-caption">Identifiant de recommandation : {row.record.recommendationId}</p></details></div></aside></div>;
}

function DetailBlock({ title, children }: { title: string; children: ReactNode }) { return <section className="border-t border-border-subtle pt-4"><h3 className="text-body-strong text-text-strong">{title}</h3><div className="mt-2">{children}</div></section>; }
function formatParameters(parameters: Record<string, number>): string { return `${parameters.confirmed_discharges ?? 0} sorties confirmées avant 15h`; }
function formatSigned(value: number): string { return value < 0 ? `−${Math.abs(value)}` : `+${value}`; }
function formatPeriodLabel(from: string, to: string): string { if (!from && !to) return "Période"; const format = (value: string) => value ? new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" }).format(new Date(`${value}T12:00:00`)) : "…"; return `${format(from)} → ${format(to)}`; }
function formatHistoryDate(value: string): string { const parts = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }).formatToParts(new Date(value)); const part = (type: string) => parts.find((item) => item.type === type)?.value ?? ""; return `${part("day")} ${part("month")} · ${part("hour")}:${part("minute")}`; }
function formatHistoryDateTime(value: string): string { return new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value)); }
