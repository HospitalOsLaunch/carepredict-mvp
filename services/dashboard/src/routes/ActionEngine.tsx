import { Activity, AlertTriangle, CheckCircle2, Euro, Target, Zap } from "lucide-react";

import type { ActionSeverity, Recommendation } from "../api/contracts";
import {
  DataTable,
  StatCard,
  type DataTableColumn,
  type DataTableRow,
  type SparklinePoint,
  type StatusVariant
} from "../components/design-system";
import { useRecommendations } from "../hooks/useActions";

const FACILITY_ID = "hosp-001";
const ORIGIN = "2025-07-08T00:00:00Z";
const HORIZON_H = 48;
const SERVICES = ["urg-001", "med-001", "chir-001", "rea-001", "ssr-001"];

const columns: DataTableColumn[] = [
  { key: "action", header: "Recommended action" },
  { key: "service", header: "Service" },
  { key: "severity", header: "Severity" },
  { key: "impact", header: "Impact", align: "right" },
  { key: "feasibility", header: "Feasibility", align: "right" },
  { key: "score", header: "Score", align: "right" },
  { key: "status", header: "Status" }
];

export function ActionEngine() {
  const query = useRecommendations(FACILITY_ID, HORIZON_H, SERVICES, ORIGIN);
  const opportunity = query.data?.opportunity;
  const recommendations = [...(query.data?.recommendations ?? [])].sort((left, right) => right.score - left.score);
  const sparkline = recommendationSparkline(recommendations);

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
          caption="Heuristic Gate A impact; simulate-based counterfactual comes in Gate B."
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
        </section>

        <aside className="space-y-4">
          {/* MOCK: selected-action drawer is Gate B; it needs persisted action detail and approval endpoints. */}
          <MockPanel
            title="Selected Action"
            badge="MOCK · Gate B"
            body="Drawer content remains illustrative: expected gains, risks if no action, and approval controls need live workflow endpoints."
          />
          {/* MOCK: execution pipeline is Gate C; no action status persistence exists yet. */}
          <MockPanel
            title="Execution Pipeline"
            badge="MOCK · Gate C"
            body="Kanban states are not wired in Gate A. Backend persistence and status transitions come later."
          />
          {/* MOCK: playbook timeline is Gate C; no scheduling endpoint exists yet. */}
          <MockPanel
            title="Today's Playbook"
            badge="MOCK · Gate C"
            body="Timeline remains sample copy until action execution and scheduling data are available."
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
          Gate A wires live Opportunity KPIs and the Recommendation table to POST /actions/recommend. Drawer, kanban and playbook remain explicitly mocked.
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

function MockPanel({ title, badge, body }: { title: string; badge: string; body: string }) {
  return (
    <article className="rounded-card border border-border-subtle bg-bg-card p-5 opacity-80 shadow-card">
      <span className="text-badge inline-flex rounded-full border border-status-elevated/30 bg-status-elevated/10 px-2 py-0.5 text-status-high">
        {badge}
      </span>
      <h2 className="text-section mt-3 text-text-strong">{title}</h2>
      <p className="text-caption mt-2">{body}</p>
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
