import {
  ArrowRight,
  Bed,
  Clock3,
  Euro,
  Info,
  Stethoscope,
  Unlock,
  Users
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import type { ForecastStep } from "../api/contracts";
import {
  DataTable,
  ExecutiveSummaryBand,
  GaugeCard,
  RecommendedActionCard,
  Sparkline,
  StatCard,
  type DataTableColumn,
  type DataTableRow,
  type SparklinePoint,
  type StatusVariant
} from "../components/design-system";
import { useForecast } from "../hooks/useForecast";

const PRIMARY_HOSPITAL_ID = "hosp-001";
const PRIMARY_SERVICE_ID = "urg-001";
const DEFAULT_ORIGIN = "2025-07-08T00:00:00Z";
const FORECAST_HORIZON = 48;
const NEAR_TERM_HOURS = 24;
const SATURATION_THRESHOLD = 1600;
const CANONICAL_P01 = 100;
const CANONICAL_P99 = 2000;

export function Overview() {
  const navigate = useNavigate();
  const forecastQuery = useForecast(PRIMARY_SERVICE_ID, DEFAULT_ORIGIN, FORECAST_HORIZON, PRIMARY_HOSPITAL_ID);
  const results = forecastQuery.data?.forecast.results ?? [];
  const summary = summarize(results);
  const trend = toSparkline(results.slice(0, NEAR_TERM_HOURS));
  const pressureScore = summary ? normalizePressureIndex(summary.nearTermMean) : 0;
  const pressureVariant = variantFromScore(pressureScore);

  return (
    <section className="space-y-7" aria-labelledby="overview-title">
      <OverviewHeader />

      {forecastQuery.error ? <ForecastError error={forecastQuery.error} onRetry={() => void forecastQuery.refetch()} /> : null}

      <DecisionHero
        isLoading={forecastQuery.isLoading}
        summary={summary}
        pressureScore={pressureScore}
        pressureVariant={pressureVariant}
        trend={trend}
      />

      <ActionsStrip onOpenSimulation={() => navigate("/simulation")} onOpenActions={() => navigate("/actions")} />

      <ForecastContext
        results={results}
        summary={summary}
        modelVersion={forecastQuery.data?.forecast.model_version}
      />

      <OperationalState results={results} pressureScore={pressureScore} />

      {/* MOCK: needs an operational synthesis endpoint combining beds, staffing, flow and forecast context. */}
      <ExecutiveSummaryBand
        summary="Illustrative executive synthesis pending a backend operational-state endpoint. The Emergency Department pressure signal is live; the action and financial values shown above are explicitly illustrative and are not model outputs."
        columns={[
          { label: "Where", value: "Live scope: urg-001 Emergency Department sentinel." },
          { label: "Why", value: "The v2 model forecasts SIIPS; the 0–100 score is a transparent normalization for executive scanning." },
          { label: "What to do", value: "Open Simulation to evaluate an intervention. Overview itself does not infer or recommend an action." }
        ]}
      />
    </section>
  );
}

function OverviewHeader() {
  return (
    <header className="flex items-start justify-between gap-6">
      <div>
        <div className="flex items-center gap-2">
          <h1 id="overview-title" className="text-screen text-text-strong">Operational Decision Cockpit</h1>
          <Stethoscope className="h-5 w-5 text-brand-primary" aria-hidden="true" />
        </div>
        <p className="text-caption mt-2 max-w-3xl">
          Decision-first view: act, quantify the illustrative opportunity, then inspect the live urg-001 world-model forecast supporting the decision context.
        </p>
      </div>
      <div className="rounded-full border border-border-subtle bg-bg-card px-4 py-2 text-badge text-text-muted shadow-card">
        Cityview Medical Center · replay origin 08 Jul 2025
      </div>
    </header>
  );
}

function DecisionHero({
  isLoading,
  summary,
  pressureScore,
  pressureVariant,
  trend
}: {
  isLoading: boolean;
  summary: ForecastSummary | null;
  pressureScore: number;
  pressureVariant: StatusVariant;
  trend: SparklinePoint[];
}) {
  return (
    <section className="rounded-card border border-border-subtle bg-bg-card p-6 shadow-card" aria-labelledby="decision-verdict-title">
      <div className="grid grid-cols-[minmax(0,1.45fr)_minmax(250px,0.78fr)_minmax(190px,0.52fr)_250px] items-stretch gap-6">
        <div className="flex flex-col justify-between border-r border-border-subtle pr-6">
          <div>
            <SourceBadge kind="live" />
            <p className="text-card-label mt-4">Decision signal · Emergency Department sentinel</p>
            <h2 id="decision-verdict-title" className="text-hero mt-3 max-w-3xl text-text-strong">
              {isLoading || !summary
                ? "Loading the live Emergency Department pressure outlook."
                : `Emergency Department is trending toward a pressure peak of ${formatNumber(summary.peak.predicted_siips)} SIIPS at T+${summary.peak.step_index}h.`}
            </h2>
          </div>
          <p className="text-caption mt-5 max-w-2xl">
            Live v2 forecast, action-free, from the canonical 120-hour feature window. It is a service sentinel, not a silent hospital-wide aggregate.
          </p>
        </div>

        <div className="flex flex-col justify-between rounded-card border border-status-elevated/25 bg-status-elevated/10 p-5">
          <div>
            <SourceBadge kind="illustrative" />
            <p className="text-card-label mt-4">Primary action</p>
            <h3 className="text-section mt-2 text-text-strong">Accelerate confirmed discharges</h3>
          </div>
          <div className="mt-5">
            <p className="text-screen numeric-tabular text-status-good">−18 pts</p>
            <p className="text-body-strong mt-1">Illustrative pressure impact · €12k</p>
            <p className="text-caption mt-2">Pending Action Engine and financial-impact endpoints.</p>
          </div>
        </div>

        <div className="flex flex-col justify-between rounded-card border border-status-elevated/25 bg-bg-app p-5">
          <SourceBadge kind="illustrative" />
          <div className="mt-5">
            <p className="text-card-label">Opportunity this week</p>
            <p className="text-hero numeric-tabular mt-2 text-text-strong">€18k</p>
            <p className="text-body-strong mt-2">across 2 sample actions</p>
            <p className="text-caption mt-2">Not a measured saving or model output.</p>
          </div>
        </div>

        <div className="relative">
          {isLoading ? <GaugeSkeleton /> : (
            <GaugeCard
              title="ED pressure index"
              value={pressureScore}
              label={statusLabel(pressureVariant)}
              variant={pressureVariant}
              trend={trend}
              context="Normalized from live 24h SIIPS"
              compact
            />
          )}
          <div className="absolute left-4 top-4 z-20"><SourceBadge kind="live" compact /></div>
          <PressureIndexTooltip />
        </div>
      </div>
    </section>
  );
}

function ActionsStrip({ onOpenSimulation, onOpenActions }: { onOpenSimulation: () => void; onOpenActions: () => void }) {
  return (
    <section aria-labelledby="actions-strip-title">
      <div className="mb-3 flex items-end justify-between gap-4">
        <div>
          <p className="text-card-label text-brand-primary">What to do now</p>
          <h2 id="actions-strip-title" className="text-section mt-1 text-text-strong">Decision options</h2>
        </div>
        <p className="text-caption">Illustrative action concepts are separated from the one runnable simulation affordance.</p>
      </div>
      <div className="grid grid-cols-3 gap-4">
        {/* MOCK: needs action recommendation endpoint; /forecast/charge returns no actions. */}
        <RecommendedActionCard
          rank={1}
          title="Accelerate confirmed discharges"
          subtitle="Sample action pending Action Engine"
          pressureDelta="↓ 18 pts"
          financialImpact="€12k"
          sourceLabel="ILLUSTRATIVE"
          source="illustrative"
          ctaLabel="Review sample action"
          onClick={onOpenActions}
        />
        {/* MOCK: needs staffing recommendation and financial-impact endpoints. */}
        <RecommendedActionCard
          rank={2}
          title="Rebalance float coverage"
          subtitle="Sample action pending staffing endpoints"
          pressureDelta="↓ 9 pts"
          financialImpact="€6k"
          sourceLabel="ILLUSTRATIVE"
          source="illustrative"
          ctaLabel="Review sample action"
          onClick={onOpenActions}
        />
        <RecommendedActionCard
          rank={3}
          title="What if we add 2 nurses?"
          subtitle="Opens the existing real world-model simulation workflow"
          pressureDelta="Run model"
          financialImpact="Not estimated"
          sourceLabel="LIVE · REAL SIMULATION"
          source="live"
          ctaLabel="Open Simulation"
          onClick={onOpenSimulation}
        />
      </div>
    </section>
  );
}

function ForecastContext({ results, summary, modelVersion }: { results: ForecastStep[]; summary: ForecastSummary | null; modelVersion?: string }) {
  return (
    <section className="rounded-card border border-border-subtle bg-bg-card p-5 shadow-card" aria-labelledby="forecast-context-title">
      <div className="grid grid-cols-[220px_minmax(0,1fr)_160px_160px_180px] items-center gap-6">
        <div>
          <SourceBadge kind="live" />
          <h2 id="forecast-context-title" className="text-section mt-3 text-text-strong">Live v2 forecast</h2>
          <p className="text-caption mt-1">urg-001 · next 48 hours</p>
        </div>
        <div className="h-14 border-x border-border-subtle px-6">
          <Sparkline data={toSparkline(results)} variant={summary ? variantFromSiips(summary.peak.predicted_siips) : "neutral"} height={56} label="Live Emergency Department 48-hour forecast" />
        </div>
        <ForecastMetric label="Peak" value={summary ? `${formatNumber(summary.peak.predicted_siips)} SIIPS` : "Pending"} />
        <ForecastMetric label="Time to peak" value={summary ? `T+${summary.peak.step_index}h` : "Pending"} />
        <div className="text-right">
          <span className="text-badge inline-flex rounded-full border border-status-good/30 bg-status-good/10 px-2.5 py-1 text-status-good">{modelVersion ?? "Connecting"}</span>
          <Link to="/forecast" className="text-control mt-3 inline-flex items-center gap-1 text-brand-primary">Open Pressure Forecast <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
        </div>
      </div>
    </section>
  );
}

function OperationalState({ results, pressureScore }: { results: ForecastStep[]; pressureScore: number }) {
  return (
    <section className="rounded-card border border-border-subtle bg-bg-app/70 p-5" aria-labelledby="operational-state-title">
      <div className="mb-4 flex items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 id="operational-state-title" className="text-section text-text-strong">Operational state</h2>
            <span className="text-badge rounded-full border border-status-elevated/30 bg-status-elevated/10 px-2.5 py-1 text-status-high">PENDING LIVE ENDPOINTS</span>
          </div>
          <p className="text-caption mt-1">Product-vision context kept deliberately secondary; every sample value is marked illustrative.</p>
        </div>
      </div>

      <div className="grid grid-cols-5 gap-4">
        {/* MOCK: needs canonical bed-state endpoint. */}
        <StatCard compact badge="ILLUSTRATIVE" label="Beds at risk" icon={Bed} metric="43" unit="beds" caption="Bed endpoint pending." variant="critical" sparkline={mockSparkline(43, 6)} />
        {/* MOCK: needs staffing coverage endpoint. */}
        <StatCard compact badge="ILLUSTRATIVE" label="Staffing gap" icon={Users} metric="8.4" unit="FTE" caption="Staffing endpoint pending." variant="high" sparkline={mockSparkline(8.4, 1.2)} />
        {/* MOCK: needs discharge readiness endpoint. */}
        <StatCard compact badge="ILLUSTRATIVE" label="Delayed discharges" icon={Clock3} metric="19" unit="patients" caption="Discharge endpoint pending." variant="elevated" sparkline={mockSparkline(19, -2)} />
        {/* MOCK: needs staffing/overtime endpoint. */}
        <StatCard compact badge="ILLUSTRATIVE" label="Overtime exposure" icon={Euro} metric="€31k" unit="week" caption="Overtime endpoint pending." variant="high" sparkline={mockSparkline(31, 4)} />
        {/* MOCK: needs capacity opportunity endpoint. */}
        <StatCard compact badge="ILLUSTRATIVE" label="Capacity unlock" icon={Unlock} metric="27" unit="beds" caption="Capacity endpoint pending." variant="good" sparkline={mockSparkline(27, 3)} />
      </div>

      <div className="mt-5">
        <UnitPressureOverview results={results} pressureScore={pressureScore} />
      </div>
    </section>
  );
}

function PressureIndexTooltip() {
  return (
    <div className="group absolute right-4 top-4 z-30">
      <button type="button" className="rounded-full p-1 text-text-muted outline-none hover:text-brand-primary focus-visible:ring-2 focus-visible:ring-brand-primary" aria-label="How the pressure index is calculated">
        <Info className="h-4 w-4" aria-hidden="true" />
      </button>
      <div className="chart-tooltip pointer-events-none absolute right-0 top-8 hidden w-72 group-hover:block group-focus-within:block">
        <p className="text-body-strong">Derived pressure index</p>
        <p className="text-caption mt-1">Not a raw model output. It normalizes the mean predicted SIIPS over 24h using the canonical anti-OOD band: clamp((SIIPS − 100) / (2000 − 100) × 100).</p>
      </div>
    </div>
  );
}

function SourceBadge({ kind, compact = false }: { kind: "live" | "illustrative"; compact?: boolean }) {
  const isLive = kind === "live";
  return (
    <span className={`text-badge inline-flex items-center gap-1.5 rounded-full border ${compact ? "px-2 py-0.5" : "px-2.5 py-1"} ${isLive ? "border-status-good/30 bg-status-good/10 text-status-good" : "border-status-elevated/30 bg-status-elevated/10 text-status-high"}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${isLive ? "bg-status-good" : "bg-status-elevated"}`} aria-hidden="true" />
      {isLive ? "LIVE" : "ILLUSTRATIVE"}
    </span>
  );
}

function ForecastMetric({ label, value }: { label: string; value: string }) {
  return <div><p className="text-card-label">{label}</p><p className="text-body-strong numeric-tabular mt-2">{value}</p></div>;
}

function UnitPressureOverview({ results, pressureScore }: { results: ForecastStep[]; pressureScore: number }) {
  const peak = results.length ? Math.max(...results.map((step) => step.predicted_siips)) : 0;
  const columns: DataTableColumn[] = [
    { key: "unit", header: "Unit" },
    { key: "score", header: "Pressure" },
    { key: "peak", header: "Forecast peak", align: "right" },
    { key: "trend", header: "48h trend" },
    { key: "source", header: "Source", align: "right" }
  ];
  const rows: DataTableRow[] = [
    {
      id: PRIMARY_SERVICE_ID,
      cells: {
        unit: { type: "text", value: "Emergency Department", muted: "urg-001 · LIVE" },
        score: { type: "status", status: variantFromScore(pressureScore), label: "LIVE", score: Math.round(pressureScore) },
        peak: { type: "text", value: results.length ? `${formatNumber(peak)} SIIPS` : "Pending" },
        trend: { type: "sparkline", data: toSparkline(results), variant: variantFromScore(pressureScore) },
        source: { type: "action", label: "Live forecast" }
      }
    },
    // MOCK: needs multi-service feature-window and forecast aggregation endpoint.
    ...["Medicine", "Surgery", "ICU", "Rehabilitation"].map((unit, index): DataTableRow => ({
      id: `mock-${index}`,
      cells: {
        unit: { type: "text", value: unit, muted: "ILLUSTRATIVE · endpoint pending" },
        score: { type: "status", status: "neutral", label: "ILLUSTRATIVE" },
        peak: { type: "text", value: "—", muted: "No live value" },
        trend: { type: "sparkline", data: mockSparkline(20 + index * 3, 1), variant: "neutral" },
        source: { type: "action", label: "Endpoint pending" }
      }
    }))
  ];
  return <DataTable columns={columns} rows={rows} footerLink="Open Pressure Forecast" />;
}

function ForecastError({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div className="rounded-card border border-status-critical/30 bg-status-critical/10 p-5" role="alert">
      <p className="text-body-strong text-status-critical">Live pressure forecast unavailable</p>
      <p className="text-body-copy mt-2">{error.message}</p>
      <button type="button" className="text-control mt-4 rounded-full bg-brand-primary px-4 py-2 text-white" onClick={onRetry}>Retry forecast chain</button>
    </div>
  );
}

function GaugeSkeleton() {
  return <div className="h-[190px] animate-pulse rounded-card border border-border-subtle bg-bg-card p-4 shadow-card"><div className="h-full rounded-card bg-bg-app" /></div>;
}

interface ForecastSummary {
  nearTermMean: number;
  peak: ForecastStep;
}

function summarize(results: ForecastStep[]): ForecastSummary | null {
  if (results.length === 0) return null;
  const nearTerm = results.slice(0, NEAR_TERM_HOURS);
  const nearTermMean = nearTerm.reduce((sum, step) => sum + step.predicted_siips, 0) / nearTerm.length;
  const peak = results.reduce((current, step) => step.predicted_siips > current.predicted_siips ? step : current, results[0]);
  return { nearTermMean, peak };
}

function normalizePressureIndex(siips: number): number {
  // The model outputs raw SIIPS, not a 0-100 score. This display index uses the same canonical anti-OOD guard band as the serving realism test.
  return clamp(((siips - CANONICAL_P01) / (CANONICAL_P99 - CANONICAL_P01)) * 100, 0, 100);
}

function variantFromScore(score: number): StatusVariant {
  if (score >= 85) return "critical";
  if (score >= 70) return "high";
  if (score >= 55) return "elevated";
  return "optimal";
}

function variantFromSiips(siips: number): StatusVariant {
  if (siips >= SATURATION_THRESHOLD) return "critical";
  if (siips >= SATURATION_THRESHOLD * 0.88) return "high";
  if (siips >= SATURATION_THRESHOLD * 0.72) return "elevated";
  return "optimal";
}

function statusLabel(variant: StatusVariant): string {
  if (variant === "critical") return "Very High";
  if (variant === "high") return "High";
  if (variant === "elevated") return "Elevated";
  return "Optimal";
}

function toSparkline(results: ForecastStep[]): SparklinePoint[] {
  return results.map((step) => ({ label: `T+${step.step_index}`, value: step.predicted_siips }));
}

function mockSparkline(start: number, delta: number): SparklinePoint[] {
  return Array.from({ length: 8 }, (_, index) => ({ label: `P${index + 1}`, value: start + Math.sin(index / 2) * Math.abs(delta) + (delta * index) / 8 }));
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
