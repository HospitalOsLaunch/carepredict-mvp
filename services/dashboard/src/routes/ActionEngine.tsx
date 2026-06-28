import { useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Euro, History, Target, Zap } from "lucide-react";
import { Area, AreaChart, CartesianGrid, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { ActionEvent, ActionSeverity, ActionSimulationDelta, ActionStatus, Recommendation } from "../api/contracts";
import {
  DataTable,
  StatCard,
  type DataTableColumn,
  type DataTableRow,
  type SparklinePoint,
  type StatusVariant
} from "../components/design-system";
import { useActionEvents, useActionSimulation, useActionTransition, useRecommendations } from "../hooks/useActions";

const FACILITY_ID = "hosp-001";
const ORIGIN = "2025-09-10T00:00:00Z";
const HORIZON_H = 48;
const SERVICES = ["urg-001", "med-001", "chir-001", "rea-001", "ssr-001"];
const STATUS_COLUMNS: ActionStatus[] = ["proposed", "approved", "in_progress", "done", "dismissed"];
const NEXT_STATUSES: Record<ActionStatus, ActionStatus[]> = {
  proposed: ["approved", "dismissed"],
  approved: ["in_progress", "dismissed"],
  in_progress: ["done", "dismissed"],
  done: [],
  dismissed: []
};

const columns: DataTableColumn[] = [
  { key: "action", header: "Recommended action" },
  { key: "service", header: "Service" },
  { key: "severity", header: "Severity" },
  { key: "impact", header: "Impact", align: "right" },
  { key: "feasibility", header: "Feasibility", align: "right" },
  { key: "score", header: "Score", align: "right" },
  { key: "status", header: "Status" }
];

type ActionSimulationQuery = ReturnType<typeof useActionSimulation>;

export function ActionEngine() {
  const query = useRecommendations(FACILITY_ID, HORIZON_H, SERVICES, ORIGIN);
  const opportunity = query.data?.opportunity;
  const recommendations = [...(query.data?.recommendations ?? [])].sort((left, right) => right.score - left.score);
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const selectedRecommendation = useMemo(
    () => recommendations.find((recommendation) => recommendation.id === selectedId) ?? recommendations[0],
    [recommendations, selectedId]
  );
  const simulationQuery = useActionSimulation(selectedRecommendation, FACILITY_ID, ORIGIN);
  const eventsQuery = useActionEvents(selectedRecommendation?.id);
  const transition = useActionTransition();
  const sparkline = recommendationSparkline(recommendations);

  useEffect(() => {
    if (!selectedId && recommendations[0]) {
      setSelectedId(recommendations[0].id);
    }
  }, [recommendations, selectedId]);

  return (
    <section className="space-y-7" aria-labelledby="action-engine-title">
      <ScreenHeader />

      {query.error ? <ErrorBanner error={query.error} onRetry={() => void query.refetch()} /> : null}

      <div className="grid grid-cols-5 gap-4">
        <StatCard
          label="Actionable opportunities"
          icon={Zap}
          metric={query.isLoading ? "—" : String(recommendations.length)}
          unit="actions"
          caption="Live from POST /actions/recommend, ranked by heuristic Gate A score."
          variant={recommendations.length > 0 ? "high" : "optimal"}
          sparkline={sparkline}
        />
        <StatCard
          label="Pressure reduction potential"
          icon={Activity}
          metric={opportunity ? formatSigned(opportunity.total_projected_impact_siips) : "—"}
          unit="SIIPS"
          caption="Gate A opportunity total; drawer uses Gate B counterfactual where supported."
          variant={opportunity && opportunity.total_projected_impact_siips > 0 ? "good" : "neutral"}
          sparkline={sparkline}
        />
        <StatCard
          label="Critical actions"
          icon={AlertTriangle}
          metric={opportunity ? String(opportunity.critical_actions_count) : "—"}
          unit="critical"
          caption="Count of proposed actions attached to critical-risk services."
          variant={opportunity && opportunity.critical_actions_count > 0 ? "critical" : "optimal"}
          sparkline={sparkline}
        />
        <StatCard
          label="Services at risk"
          icon={Target}
          metric={opportunity ? String(opportunity.services_at_risk) : "—"}
          unit="services"
          caption="Derived from forecast peaks above the Gate A threshold."
          variant={opportunity && opportunity.services_at_risk > 0 ? "high" : "optimal"}
          sparkline={sparkline}
        />
        <StatCard
          label="Estimated savings"
          icon={Euro}
          metric="—"
          unit="pending"
          caption="MOCK: needs financial-impact endpoint; not inferred by Gate A."
          variant="neutral"
          badge="MOCK"
          sparkline={sparkline}
        />
      </div>

      <div className="grid grid-cols-[minmax(0,0.68fr)_minmax(360px,0.32fr)] gap-5">
        <section aria-labelledby="recommendations-title">
          <div className="mb-3 flex items-end justify-between gap-4">
            <div>
              <p className="text-card-label text-brand-primary">Live recommendations</p>
              <h2 id="recommendations-title" className="text-section mt-1 text-text-strong">
                Prioritized recommendations
              </h2>
            </div>
            <span className="text-badge rounded-full border border-border-subtle bg-bg-card px-3 py-1 text-text-muted shadow-card">
              {query.isLoading ? "Loading" : `${recommendations.length} proposed`}
            </span>
          </div>
          <DataTable
            columns={columns}
            rows={recommendations.length > 0 ? buildRows(recommendations) : emptyRows(query.isLoading)}
            footerLink="View all proposed actions"
          />
          <RecommendationDrivers recommendation={selectedRecommendation} />
        </section>

        <aside className="space-y-4">
          <ActionSimulationDrawer
            recommendation={selectedRecommendation}
            recommendations={recommendations}
            selectedId={selectedRecommendation?.id}
            onSelect={setSelectedId}
            simulation={simulationQuery}
          />
          <ActionKanban
            recommendations={recommendations}
            selectedId={selectedRecommendation?.id}
            onSelect={setSelectedId}
            onTransition={(recommendation, toStatus) =>
              transition.mutate({
                recommendationId: recommendation.id,
                toStatus,
                actor: "sarah.johnson",
                reason: `Kanban transition to ${toStatus}`
              })
            }
            isTransitioning={transition.isPending}
          />
          <ActionTimeline
            events={eventsQuery.data?.events ?? []}
            isLoading={eventsQuery.isLoading}
            error={eventsQuery.error}
            onRetry={() => void eventsQuery.refetch()}
          />
        </aside>
      </div>
    </section>
  );
}

function ScreenHeader() {
  return (
    <header className="flex items-start justify-between gap-6">
      <div>
        <div className="flex items-center gap-2">
          <h1 id="action-engine-title" className="text-screen text-text-strong">
            Action Engine
          </h1>
          <CheckCircle2 className="h-5 w-5 text-brand-primary" aria-hidden="true" />
        </div>
        <p className="text-caption mt-2 max-w-3xl">
          Live recommendations, model counterfactual drawer, and traced decision workflow. This page records approvals and status changes only; it does not execute work in hospital systems.
        </p>
      </div>
      <span className="rounded-full border border-border-subtle bg-bg-card px-4 py-2 text-badge text-text-muted shadow-card">
        {FACILITY_ID} · {HORIZON_H}h · {SERVICES.length} services
      </span>
    </header>
  );
}

function buildRows(recommendations: Recommendation[]): DataTableRow[] {
  return recommendations.map((recommendation) => ({
    id: recommendation.id,
    cells: {
      action: {
        type: "text",
        value: recommendation.title,
        muted: recommendation.rationale
      },
      service: { type: "text", value: recommendation.service_id, muted: recommendation.lever },
      severity: {
        type: "status",
        status: severityVariant(recommendation.severity),
        label: recommendation.severity,
        score: Math.round(recommendation.score * 100)
      },
      impact: {
        type: "delta",
        value: recommendation.projected_impact_siips,
        unit: "SIIPS",
        inverted: true
      },
      feasibility: {
        type: "miniBar",
        value: Math.round(recommendation.feasibility * 100),
        label: `${Math.round(recommendation.feasibility * 100)}%`
      },
      score: { type: "text", value: recommendation.score.toFixed(2) },
      status: { type: "text", value: recommendation.status }
    }
  }));
}

function emptyRows(isLoading: boolean): DataTableRow[] {
  return [
    {
      id: "empty",
      cells: {
        action: {
          type: "text",
          value: isLoading ? "Loading recommendations" : "No at-risk service detected",
          muted: isLoading ? "Calling POST /actions/recommend." : "Forecasts are below Gate A threshold."
        },
        service: { type: "text", value: "—" },
        severity: { type: "status", status: "optimal", label: "none" },
        impact: { type: "text", value: "—" },
        feasibility: { type: "text", value: "—" },
        score: { type: "text", value: "—" },
        status: { type: "text", value: "—" }
      }
    }
  ];
}

function ActionSimulationDrawer({
  recommendation,
  recommendations,
  selectedId,
  onSelect,
  simulation
}: {
  recommendation: Recommendation | undefined;
  recommendations: Recommendation[];
  selectedId: string | undefined;
  onSelect: (id: string) => void;
  simulation: ActionSimulationQuery;
}) {
  const data = simulation.data;
  const chartData = data?.mode === "counterfactual" ? actionSimulationChartData(data) : [];
  const modeLabel = data?.mode === "counterfactual" ? "COUNTERFACTUAL" : data?.mode === "heuristic" ? "HEURISTIC" : "GATE B";
  const modeClass =
    data?.mode === "counterfactual"
      ? "border-brand-primary/30 bg-brand-primary/10 text-brand-primary"
      : "border-status-elevated/30 bg-status-elevated/10 text-status-high";

  if (!recommendation) {
    return (
      <article className="rounded-card border border-border-subtle bg-bg-card p-5 shadow-card">
        <span className="text-badge inline-flex rounded-full border border-border-subtle bg-bg-app px-2 py-0.5 text-text-muted">
          GATE B
        </span>
        <h2 className="text-section mt-3 text-text-strong">Selected Action</h2>
        <p className="text-caption mt-2">No recommendation is available for simulation.</p>
      </article>
    );
  }

  return (
    <article className="rounded-card border border-border-subtle bg-bg-card p-5 shadow-card">
      <div className="flex items-start justify-between gap-3">
        <div>
          <span className={`text-badge inline-flex rounded-full border px-2 py-0.5 ${modeClass}`}>{modeLabel}</span>
          <h2 className="text-section mt-3 text-text-strong">Selected Action</h2>
          <p className="text-caption mt-1">{recommendation.title}</p>
        </div>
        <span className="text-badge rounded-full bg-bg-app px-2 py-0.5 text-text-muted">{recommendation.service_id}</span>
      </div>

      {recommendations.length > 1 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {recommendations.slice(0, 5).map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelect(item.id)}
              className={`rounded-full border px-3 py-1 text-badge transition ${
                selectedId === item.id
                  ? "border-brand-primary bg-brand-primary/10 text-brand-primary"
                  : "border-border-subtle bg-bg-app text-text-muted hover:text-text-body"
              }`}
            >
              {item.service_id} · {item.lever}
            </button>
          ))}
        </div>
      ) : null}

      {simulation.error ? (
        <div className="mt-4 rounded-card border border-status-critical/30 bg-status-critical/10 p-3 text-caption text-status-critical">
          <span className="block">Action simulation unavailable.</span>
          <span className="mt-1 block">{simulation.error instanceof Error ? simulation.error.message : "Unknown error"}</span>
          <button type="button" className="text-control mt-2 text-brand-primary hover:underline" onClick={() => void simulation.refetch()}>
            Retry simulation
          </button>
        </div>
      ) : null}

      {simulation.isLoading ? (
        <div className="mt-5 h-56 animate-pulse rounded-card bg-bg-app" aria-label="Loading action simulation" />
      ) : null}

      {!simulation.isLoading && data?.mode === "heuristic" ? (
        <div className="mt-5 rounded-card border border-status-elevated/30 bg-status-elevated/10 p-4">
          <p className="text-badge text-status-high">Estimation heuristique (pas de contrefactuel modèle)</p>
          <p className="text-caption mt-2 text-text-body">{data.summary.rationale}</p>
          <p className="text-hero mt-3 text-text-strong">
            {formatSigned(data.summary.delta_siips)}
            <span className="text-unit ml-1">SIIPS</span>
          </p>
        </div>
      ) : null}

      {!simulation.isLoading && data?.mode === "counterfactual" ? (
        <div className="mt-5">
          <div className="grid grid-cols-3 gap-3">
            <MetricChip label="Peak before" value={formatPeak(data.summary.peak_before)} />
            <MetricChip label="Peak after" value={formatPeak(data.summary.peak_after)} />
            <MetricChip label="Delta" value={formatSigned(data.summary.delta_siips)} tone={data.summary.delta_siips < 0 ? "good" : "bad"} />
          </div>
          <div className="mt-4 h-64 rounded-card border border-border-subtle bg-bg-app/60 p-3">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 12, right: 10, bottom: 0, left: -20 }}>
                <CartesianGrid stroke="var(--border-subtle)" strokeDasharray="3 3" />
                <XAxis dataKey="step" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={{
                    border: "1px solid var(--border-subtle)",
                    borderRadius: 12,
                    boxShadow: "var(--shadow-card)",
                    fontSize: 11
                  }}
                />
                <Area type="monotone" dataKey="upper" stroke="none" fill="var(--brand-primary)" fillOpacity={0.12} activeDot={false} />
                <Area type="monotone" dataKey="lower" stroke="none" fill="var(--bg-app)" fillOpacity={1} activeDot={false} />
                <Line type="monotone" dataKey="baseline" stroke="var(--text-muted)" strokeWidth={1.8} dot={false} name="baseline" />
                <Line type="monotone" dataKey="after" stroke="var(--brand-primary)" strokeWidth={2.2} dot={false} name="after" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <p className="text-caption mt-3">{data.summary.rationale}</p>
        </div>
      ) : null}
    </article>
  );
}

function RecommendationDrivers({ recommendation }: { recommendation: Recommendation | undefined }) {
  if (!recommendation) {
    return null;
  }
  const explanation = recommendation.explanation;
  return (
    <article className="mt-4 rounded-card border border-border-subtle bg-bg-card p-5 shadow-card">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-card-label text-brand-primary">Explainable drivers</p>
          <h3 className="text-section mt-1 text-text-strong">{recommendation.service_id} · forecast load risk</h3>
        </div>
        <span className="text-badge rounded-full bg-bg-app px-2 py-0.5 text-text-muted">{recommendation.severity}</span>
      </div>

      {explanation ? (
        <>
          <div className="mt-4 grid grid-cols-4 gap-3">
            <MetricChip label="Excess" value={`+${formatNumber(explanation.risk.excess_pts)} pts`} />
            <MetricChip label="Relative" value={`${Math.round(explanation.risk.excess_ratio * 100)}%`} />
            <MetricChip label="Duration" value={`${explanation.risk.duration_h}h`} />
            <MetricChip label="Peak" value={explanation.risk.peak_timing} />
          </div>
          <div className="mt-4 rounded-card border border-border-subtle bg-bg-app/70 p-4">
            <p className="text-body-copy text-text-strong">{explanation.risk.summary}</p>
            <p className="text-caption mt-2 text-text-body">{explanation.risk.severity_reason}</p>
          </div>
          <div className="mt-3 rounded-card border border-border-subtle bg-bg-app/70 p-4">
            <p className="text-body-copy text-text-strong">{explanation.priority.summary}</p>
            <p className="text-caption mt-2 text-text-body">
              Score {explanation.priority.score_component.toFixed(2)} · faisabilité{" "}
              {Math.round(explanation.priority.feasibility * 100)}% · coût relatif {explanation.priority.cost.toFixed(2)}
            </p>
          </div>
          <p className="text-caption mt-3 text-text-muted">{explanation.scope_note}</p>
        </>
      ) : (
        <div className="mt-4 rounded-card border border-border-subtle bg-bg-app/70 p-4">
          <p className="text-body-copy text-text-strong">{recommendation.rationale}</p>
          <p className="text-caption mt-2 text-text-muted">
            Explanation detail is unavailable for this response. Scope remains forecast-load only; downstream flow drivers need a later endpoint.
          </p>
        </div>
      )}
    </article>
  );
}

function MetricChip({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "good" | "bad" }) {
  const toneClass = tone === "good" ? "text-status-good" : tone === "bad" ? "text-status-critical" : "text-text-strong";
  return (
    <div className="rounded-card border border-border-subtle bg-bg-card p-3">
      <p className="text-card-label">{label}</p>
      <p className={`text-section mt-1 ${toneClass}`}>{value}</p>
    </div>
  );
}

function ActionKanban({
  recommendations,
  selectedId,
  onSelect,
  onTransition,
  isTransitioning
}: {
  recommendations: Recommendation[];
  selectedId: string | undefined;
  onSelect: (id: string) => void;
  onTransition: (recommendation: Recommendation, toStatus: ActionStatus) => void;
  isTransitioning: boolean;
}) {
  const [draggedId, setDraggedId] = useState<string | undefined>();
  return (
    <article className="rounded-card border border-border-subtle bg-bg-card p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <p className="text-card-label text-brand-primary">Live workflow</p>
          <h2 className="text-section mt-1 text-text-strong">Execution Pipeline</h2>
        </div>
        <span className="text-badge rounded-full bg-bg-app px-2 py-0.5 text-text-muted">decision only</span>
      </div>
      <div className="grid grid-cols-1 gap-3">
        {STATUS_COLUMNS.map((status) => {
          const items = recommendations.filter((recommendation) => recommendation.status === status);
          return (
            <div
              key={status}
              className="rounded-card border border-border-subtle bg-bg-app/70 p-3"
              onDragOver={(event) => event.preventDefault()}
              onDrop={() => {
                const recommendation = recommendations.find((item) => item.id === draggedId);
                if (recommendation && NEXT_STATUSES[recommendation.status].includes(status)) {
                  onTransition(recommendation, status);
                }
                setDraggedId(undefined);
              }}
            >
              <div className="mb-2 flex items-center justify-between">
                <span className="text-card-label">{statusLabel(status)}</span>
                <span className="text-badge text-text-muted">{items.length}</span>
              </div>
              <div className="space-y-2">
                {items.length === 0 ? <p className="text-caption">No actions</p> : null}
                {items.slice(0, 3).map((recommendation) => (
                  <button
                    key={recommendation.id}
                    type="button"
                    draggable
                    onDragStart={() => setDraggedId(recommendation.id)}
                    onClick={() => onSelect(recommendation.id)}
                    className={`w-full rounded-card border p-3 text-left transition ${
                      selectedId === recommendation.id
                        ? "border-brand-primary bg-brand-primary/10"
                        : "border-border-subtle bg-bg-card hover:border-brand-primary/40"
                    }`}
                  >
                    <span className="text-badge text-text-muted">{recommendation.service_id}</span>
                    <span className="text-body-copy mt-1 block text-text-strong">{recommendation.lever}</span>
                    <span className="text-caption mt-1 block">{formatSigned(recommendation.projected_impact_siips)} SIIPS</span>
                  </button>
                ))}
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {selectedId && recommendations.find((item) => item.id === selectedId)?.status !== status
                  ? null
                  : NEXT_STATUSES[status].map((next) => {
                      const selected = recommendations.find((item) => item.id === selectedId && item.status === status);
                      return selected ? (
                        <button
                          key={next}
                          type="button"
                          disabled={isTransitioning}
                          onClick={() => onTransition(selected, next)}
                          className="rounded-full border border-border-subtle bg-bg-card px-2 py-1 text-badge text-text-muted hover:text-brand-primary disabled:opacity-50"
                        >
                          {statusLabel(next)}
                        </button>
                      ) : null;
                    })}
              </div>
            </div>
          );
        })}
      </div>
    </article>
  );
}

function ActionTimeline({
  events,
  isLoading,
  error,
  onRetry
}: {
  events: ActionEvent[];
  isLoading: boolean;
  error: Error | null;
  onRetry: () => void;
}) {
  return (
    <article className="rounded-card border border-border-subtle bg-bg-card p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <p className="text-card-label text-brand-primary">Audit trail</p>
          <h2 className="text-section mt-1 text-text-strong">Action Timeline</h2>
        </div>
        <History className="h-5 w-5 text-brand-primary" aria-hidden="true" />
      </div>
      {isLoading ? <div className="h-24 animate-pulse rounded-card bg-bg-app" /> : null}
      {error ? (
        <div className="rounded-card border border-status-critical/30 bg-status-critical/10 p-3 text-caption text-status-critical">
          <span className="block">Audit trail unavailable.</span>
          <button type="button" className="text-control mt-2 text-brand-primary hover:underline" onClick={onRetry}>
            Retry timeline
          </button>
        </div>
      ) : null}
      {!isLoading && !error ? (
        <ol className="space-y-3">
          {events.length === 0 ? <li className="text-caption">No audit events yet.</li> : null}
          {events.map((event) => (
            <li key={event.event_id} className="rounded-card border border-border-subtle bg-bg-app/70 p-3">
              <p className="text-body-copy text-text-strong">
                {event.from_status ? `${statusLabel(event.from_status)} → ` : ""}
                {statusLabel(event.to_status)}
              </p>
              <p className="text-caption mt-1">
                {event.actor} · {formatDateTime(event.occurred_at)}
              </p>
              {event.reason ? <p className="text-caption mt-1 text-text-body">{event.reason}</p> : null}
            </li>
          ))}
        </ol>
      ) : null}
    </article>
  );
}

function ErrorBanner({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div className="rounded-card border border-status-critical/30 bg-status-critical/10 p-4 text-body-copy text-status-critical">
      <strong className="text-body-strong block">Recommendation endpoint unavailable.</strong>
      <span className="mt-1 block">{error.message}</span>
      <button type="button" className="text-control mt-2 text-brand-primary hover:underline" onClick={onRetry}>
        Retry recommendations
      </button>
    </div>
  );
}

function recommendationSparkline(recommendations: Recommendation[]): SparklinePoint[] {
  if (recommendations.length === 0) {
    return Array.from({ length: 8 }, (_, index) => ({ label: `T+${index}`, value: 0 }));
  }
  return recommendations.slice(0, 8).map((recommendation, index) => ({
    label: recommendation.service_id,
    value: Math.abs(recommendation.projected_impact_siips) + index
  }));
}

function severityVariant(severity: ActionSeverity): StatusVariant {
  if (severity === "critical") return "critical";
  if (severity === "high") return "high";
  if (severity === "elevated") return "elevated";
  return "optimal";
}

function formatSigned(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 1 });
}

function formatNumber(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function statusLabel(status: ActionStatus): string {
  return status.replace("_", " ");
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function formatPeak(value: number | null): string {
  if (value === null) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function actionSimulationChartData(data: ActionSimulationDelta) {
  return data.baseline.map((point, index) => {
    const after = data.after[index];
    return {
      step: `T+${point.step_index + 1}`,
      baseline: point.predicted_siips,
      after: after?.predicted_siips,
      lower: after?.lower_bound,
      upper: after?.upper_bound
    };
  });
}
