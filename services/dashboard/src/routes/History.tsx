import { useMemo, useState } from "react";
import type { ReactNode } from "react";

import { useScenarioContext, type DecisionRecord } from "../domain/ScenarioContext";
import {
  classifyRiskLevel,
  formatRiskLevel,
  simulateDischargeScenario,
  type InsightRiskLevel
} from "../domain/insights";

type DecisionFilter = "all" | "accepted" | "modified" | "refused";
type SortKey = "created_desc" | "service_asc" | "risk_desc" | "siips_asc" | "hours_asc";

interface HistoryRow {
  record: DecisionRecord;
  initialRisk: InsightRiskLevel;
  decisionLabel: "Acceptée" | "Modifiée puis validée" | "Refusée";
  statusLabel: "Validée" | "Refusée";
  peakDelta: number;
  hoursDelta: number;
}

export function History() {
  const { insight, auditEvents, researchSessionId } = useScenarioContext();
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [service, setService] = useState("all");
  const [decisionFilter, setDecisionFilter] = useState<DecisionFilter>("all");
  const [status, setStatus] = useState("all");
  const [risk, setRisk] = useState("all");
  const [reason, setReason] = useState("all");
  const [session, setSession] = useState("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("created_desc");
  const [selectedRow, setSelectedRow] = useState<HistoryRow | null>(null);

  const rows = useMemo<HistoryRow[]>(() => auditEvents.map((record) => {
    const baseline = simulateDischargeScenario(0).summary;
    const selected = simulateDischargeScenario(record.selectedParameters.confirmed_discharges ?? 0).summary;
    return {
      record,
      initialRisk: classifyRiskLevel(insight.peakPressureSiips, insight.criticalHours),
      decisionLabel: record.decision === "dismissed"
        ? "Refusée"
        : record.decisionSource === "modified_scenario" ? "Modifiée puis validée" : "Acceptée",
      statusLabel: record.decision === "dismissed" ? "Refusée" : "Validée",
      peakDelta: selected.peak - baseline.peak,
      hoursDelta: selected.criticalHours - baseline.criticalHours
    };
  }), [auditEvents, insight]);

  const filteredRows = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    const filtered = rows.filter((row) => {
      const recordDate = row.record.createdAt.slice(0, 10);
      const matchesDateFrom = !dateFrom || recordDate >= dateFrom;
      const matchesDateTo = !dateTo || recordDate <= dateTo;
      const matchesService = service === "all" || service === insight.context.serviceId;
      const matchesDecision = decisionFilter === "all"
        || (decisionFilter === "accepted" && row.record.decision === "accepted" && row.record.decisionSource === "recommendation")
        || (decisionFilter === "modified" && row.record.decisionSource === "modified_scenario")
        || (decisionFilter === "refused" && row.record.decision === "dismissed");
      const matchesStatus = status === "all" || (status === "validated" ? row.statusLabel === "Validée" : row.statusLabel === "Refusée");
      const matchesRisk = risk === "all" || row.initialRisk === risk;
      const matchesReason = reason === "all" || row.record.reason === reason;
      const matchesSession = session === "all" || row.record.researchSessionId === session;
      const haystack = `${insight.title} ${insight.recommendation.title} ${row.record.insightId} ${row.record.researchSessionId} ${insight.context.scenarioId}`.toLowerCase();
      return matchesDateFrom && matchesDateTo && matchesService && matchesDecision && matchesStatus && matchesRisk && matchesReason && matchesSession && (!normalizedSearch || haystack.includes(normalizedSearch));
    });
    return filtered.sort((left, right) => {
      if (sort === "service_asc") return insight.context.serviceLabel.localeCompare(insight.context.serviceLabel);
      if (sort === "risk_desc") return riskRank(right.initialRisk) - riskRank(left.initialRisk);
      if (sort === "siips_asc") return left.peakDelta - right.peakDelta;
      if (sort === "hours_asc") return left.hoursDelta - right.hoursDelta;
      return right.record.createdAt.localeCompare(left.record.createdAt);
    });
  }, [dateFrom, dateTo, decisionFilter, insight, reason, risk, rows, search, service, session, sort, status]);

  const refusalReasons = Array.from(new Set(rows.map((row) => row.record.reason).filter((value): value is string => Boolean(value))));
  const sessions = Array.from(new Set(rows.map((row) => row.record.researchSessionId)));

  return (
    <section className="space-y-6" aria-labelledby="history-title">
      <header>
        <p className="text-card-label text-brand-primary">Décisions enregistrées</p>
        <h1 id="history-title" className="text-screen mt-2 text-text-strong">Historique</h1>
        <p className="text-caption mt-2">Lecture seule · session de recherche {researchSessionId}</p>
      </header>

      <section className="rounded-card border border-border-subtle bg-bg-card p-5 shadow-card" aria-label="Filtres de l'historique">
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <label className="text-caption">Du<input aria-label="Date de début" type="date" value={dateFrom} onChange={(event) => setDateFrom(event.currentTarget.value)} className="mt-1 h-10 w-full rounded-lg border border-border-subtle bg-bg-card px-3 text-text-body" /></label>
          <label className="text-caption">Au<input aria-label="Date de fin" type="date" value={dateTo} onChange={(event) => setDateTo(event.currentTarget.value)} className="mt-1 h-10 w-full rounded-lg border border-border-subtle bg-bg-card px-3 text-text-body" /></label>
          <FilterSelect label="Service / unité" value={service} onChange={setService} options={[["all", "Tous les services"], [insight.context.serviceId, insight.context.serviceLabel]]} />
          <FilterSelect label="Type de décision" value={decisionFilter} onChange={(value) => setDecisionFilter(value as DecisionFilter)} options={[["all", "Toutes"], ["accepted", "Acceptée"], ["modified", "Modifiée puis validée"], ["refused", "Refusée"]]} />
          <FilterSelect label="Statut" value={status} onChange={setStatus} options={[["all", "Tous"], ["validated", "Validée"], ["refused", "Refusée"]]} />
          <FilterSelect label="Risque initial" value={risk} onChange={setRisk} options={[["all", "Tous"], ["low", "Faible"], ["moderate", "Modérée"], ["high", "Élevée"], ["critical", "Critique"]]} />
          <FilterSelect label="Motif de refus" value={reason} onChange={setReason} options={[["all", "Tous"], ...refusalReasons.map((item) => [item, item] as [string, string])]} />
          <FilterSelect label="Session de recherche" value={session} onChange={setSession} options={[["all", "Toutes"], ...sessions.map((item) => [item, item] as [string, string])]} />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
          <label className="text-caption">Recherche<input aria-label="Rechercher dans l'historique" type="search" value={search} onChange={(event) => setSearch(event.currentTarget.value)} placeholder="Recommandation, insight ou identifiant de scénario" className="mt-1 h-10 w-full rounded-lg border border-border-subtle bg-bg-card px-3 text-text-body" /></label>
          <label className="text-caption">Trier par<select aria-label="Trier l'historique" value={sort} onChange={(event) => setSort(event.currentTarget.value as SortKey)} className="mt-1 h-10 rounded-lg border border-border-subtle bg-bg-card px-3 text-text-body"><option value="created_desc">Date · plus récent</option><option value="service_asc">Service</option><option value="risk_desc">Risque initial</option><option value="siips_asc">Impact SIIPS</option><option value="hours_asc">Impact heures en tension</option></select></label>
        </div>
      </section>

      <div className="overflow-x-auto rounded-card border border-border-subtle bg-bg-card shadow-card">
        <table className="min-w-[1100px] w-full text-left text-body-copy">
          <caption className="sr-only">Historique des décisions de recherche</caption>
          <thead className="border-b border-border-subtle bg-bg-app text-caption"><tr><th className="px-4 py-3 font-semibold">Date / heure</th><th className="px-4 py-3 font-semibold">Service</th><th className="px-4 py-3 font-semibold">Insight / tension</th><th className="px-4 py-3 font-semibold">Recommandation initiale</th><th className="px-4 py-3 font-semibold">Décision</th><th className="px-4 py-3 font-semibold">Scénario retenu</th><th className="px-4 py-3 font-semibold">Impact estimé</th><th className="px-4 py-3 font-semibold">Motif</th><th className="px-4 py-3 font-semibold">Statut</th></tr></thead>
          <tbody>{filteredRows.map((row) => <tr key={`${row.record.researchSessionId}-${row.record.timestamp}`} tabIndex={0} className="cursor-pointer border-b border-border-subtle outline-none last:border-b-0 hover:bg-bg-app focus-visible:bg-bg-app" onClick={() => setSelectedRow(row)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedRow(row); } }} aria-label={`Détail ${row.decisionLabel}`}><td className="whitespace-nowrap px-4 py-4 text-caption">{new Date(row.record.createdAt).toLocaleString("fr-FR")}</td><td className="px-4 py-4">{insight.context.serviceLabel}</td><td className="px-4 py-4"><strong className="text-text-strong">{insight.title}</strong><span className="mt-1 block text-caption">{insight.context.scenarioId}</span></td><td className="px-4 py-4">{insight.recommendation.title}</td><td className="px-4 py-4 font-medium">{row.decisionLabel}</td><td className="px-4 py-4">{row.record.selectedParameters.confirmed_discharges ?? 0} sorties</td><td className="whitespace-nowrap px-4 py-4">{formatSigned(row.peakDelta)} SIIPS · {formatSigned(row.hoursDelta)} h</td><td className="px-4 py-4">{row.record.reason ?? "—"}</td><td className="px-4 py-4"><span className="rounded-full border border-border-subtle px-2 py-1 text-badge">{row.statusLabel}</span></td></tr>)}</tbody>
        </table>
        {filteredRows.length === 0 ? <p className="p-8 text-center text-caption">Aucune décision ne correspond aux filtres.</p> : null}
      </div>

      {selectedRow ? <HistoryDrawer row={selectedRow} insight={insight} onClose={() => setSelectedRow(null)} /> : null}
    </section>
  );
}

function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: [string, string][] }) {
  return <label className="text-caption">{label}<select aria-label={label} value={value} onChange={(event) => onChange(event.currentTarget.value)} className="mt-1 h-10 w-full rounded-lg border border-border-subtle bg-bg-card px-3 text-text-body">{options.map(([optionValue, optionLabel]) => <option key={optionValue} value={optionValue}>{optionLabel}</option>)}</select></label>;
}

function HistoryDrawer({ row, insight, onClose }: { row: HistoryRow; insight: ReturnType<typeof useScenarioContext>["insight"]; onClose: () => void }) {
  const baseline = simulateDischargeScenario(0).summary;
  const original = simulateDischargeScenario(row.record.originalParameters.confirmed_discharges ?? 0).summary;
  const selected = simulateDischargeScenario(row.record.selectedParameters.confirmed_discharges ?? 0).summary;
  return <div className="fixed inset-0 z-50 flex justify-end bg-brand-navy/40" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><aside className="h-full w-full max-w-xl overflow-y-auto border-l border-border-subtle bg-bg-card p-6 shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="history-drawer-title"><div className="flex items-start justify-between gap-4"><div><p className="text-card-label text-brand-primary">Détail en lecture seule</p><h2 id="history-drawer-title" className="text-section mt-2 text-xl text-text-strong">{row.decisionLabel}</h2></div><button type="button" autoFocus aria-label="Fermer le détail" className="rounded-full p-2 text-text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary" onClick={onClose}>×</button></div><div className="mt-6 space-y-5 text-body-copy"><DetailBlock title="Insight original"><p className="font-semibold text-text-strong">{insight.title}</p><p className="mt-1">{insight.context.hospitalLabel} · {insight.context.serviceLabel}</p><p className="mt-1">Risque initial : {formatRiskLevel(row.initialRisk)}</p></DetailBlock><DetailBlock title="Recommandation originale"><p>{insight.recommendation.title}</p><p className="mt-1 text-caption">{insight.recommendation.rationale}</p></DetailBlock><DetailBlock title="Paramètres originaux"><p>{formatParameters(row.record.originalParameters)}</p></DetailBlock><DetailBlock title="Paramètres sélectionnés"><p>{formatParameters(row.record.selectedParameters)}</p></DetailBlock><DetailBlock title="Impact simulé"><p>Plan de référence : {baseline.peak} SIIPS · {baseline.criticalHours} h</p><p>Recommandation originale : {original.peak} SIIPS · {original.criticalHours} h</p><p>Scénario retenu : {selected.peak} SIIPS · {selected.criticalHours} h</p><p className="mt-1 font-semibold">Impact vs plan de référence : {formatSigned(selected.peak - baseline.peak)} SIIPS · {formatSigned(selected.criticalHours - baseline.criticalHours)} h</p></DetailBlock><DetailBlock title="Décision finale"><p>{row.decisionLabel} · {row.statusLabel}</p>{row.record.reason ? <p className="mt-1">Motif : {row.record.reason}</p> : null}<p className="mt-1">Date / heure : {new Date(row.record.timestamp).toLocaleString("fr-FR")}</p><p className="mt-1">Session : {row.record.researchSessionId}</p></DetailBlock></div></aside></div>;
}

function DetailBlock({ title, children }: { title: string; children: ReactNode }) { return <section className="rounded-xl border border-border-subtle bg-bg-app p-4"><h3 className="text-body-strong text-text-strong">{title}</h3><div className="mt-2">{children}</div></section>; }

function formatParameters(parameters: Record<string, number>): string { return `${parameters.confirmed_discharges ?? 0} sorties confirmées avant 15h`; }
function formatSigned(value: number): string { return value < 0 ? `−${Math.abs(value)}` : `+${value}`; }
function riskRank(level: InsightRiskLevel): number { return { low: 0, moderate: 1, high: 2, critical: 3 }[level]; }
