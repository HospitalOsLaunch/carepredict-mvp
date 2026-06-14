import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Clock3,
  Hospital,
  LineChart,
  Target,
  TrendingUp
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

import type { ForecastStep } from "../api/contracts";
import {
  DataTable,
  HeatmapGrid,
  RecommendedActionCard,
  SegmentedToggle,
  StatCard,
  type DataTableColumn,
  type DataTableRow,
  type HeatmapCell,
  type HorizonOption,
  type SparklinePoint,
  type StatusVariant
} from "../components/design-system";
import { useForecast } from "../hooks/useForecast";

const DEFAULT_HOSPITAL_ID = "hosp-001";
const DEFAULT_SERVICE_ID = "urg-001";
const DEFAULT_ORIGIN_LOCAL = "2025-07-08T00:00";
// Constant reference line for the canonical synthetic urgent-care distribution; a future endpoint should expose per-service p95/p99 thresholds.
const SATURATION_THRESHOLD = 1600;

const SERVICE_OPTIONS = [
  { id: "urg-001", label: "Emergency Department", specialty: "Urgent care" },
  { id: "med-001", label: "Medicine", specialty: "Inpatient medicine" },
  { id: "chir-001", label: "Surgery", specialty: "Surgical ward" },
  { id: "rea-001", label: "ICU", specialty: "Critical care" },
  { id: "ssr-001", label: "Rehabilitation", specialty: "Step-down care" }
];

const HORIZON_TO_HOURS: Record<HorizonOption, number> = {
  "24H": 24,
  "48H": 48,
  "3D": 48,
  "7D": 48,
  "14D": 48
};

interface ForecastChartPoint {
  hour: number;
  predicted: number;
  lower: number;
  upper: number;
  intervalBase: number;
  intervalWidth: number;
  threshold: number;
}

export function PressureForecast() {
  const [serviceId, setServiceId] = useState(DEFAULT_SERVICE_ID);
  const [originLocal, setOriginLocal] = useState(DEFAULT_ORIGIN_LOCAL);
  const [horizonOption, setHorizonOption] = useState<HorizonOption>("48H");
  const horizon = HORIZON_TO_HOURS[horizonOption];
  const originTimestamp = toUtcTimestamp(originLocal);
  const forecastQuery = useForecast(serviceId, originTimestamp, horizon, DEFAULT_HOSPITAL_ID);
  const selectedService = SERVICE_OPTIONS.find((service) => service.id === serviceId) ?? SERVICE_OPTIONS[0];
  const results = forecastQuery.data?.forecast.results ?? [];
  const chartData = useMemo(() => buildChartData(results), [results]);
  const summary = useMemo(() => summarizeForecast(results), [results]);
  const sparkline = toSparkline(chartData);
  const cappedHorizon = horizonOption !== "24H" && horizonOption !== "48H";

  return (
    <section className="space-y-7" aria-labelledby="forecast-title">
      <ScreenHeader
        selectedService={selectedService}
        serviceId={serviceId}
        originLocal={originLocal}
        horizon={horizonOption}
        isCapped={cappedHorizon}
        onServiceChange={setServiceId}
        onOriginChange={setOriginLocal}
        onHorizonChange={setHorizonOption}
      />

      <div className="grid grid-cols-4 gap-4">
        <StatCard
          label="Peak pressure"
          icon={TrendingUp}
          metric={summary ? formatNumber(summary.peak.predicted_siips) : "—"}
          unit="SIIPS"
          caption={summary ? `Forecast peak at T+${summary.peak.step_index}h from POST /forecast/charge.` : "Waiting for live v2 forecast output."}
          variant={summary ? variantFromSiips(summary.peak.predicted_siips) : "neutral"}
          sparkline={sparkline}
        />
        <StatCard
          label="Time to peak"
          icon={Clock3}
          metric={summary ? `T+${summary.peak.step_index}` : "—"}
          unit="hours"
          caption="Computed directly from the returned multi-horizon forecast."
          variant={summary ? variantFromSiips(summary.peak.predicted_siips) : "neutral"}
          sparkline={sparkline}
        />
        <StatCard
          label="Above threshold"
          icon={AlertTriangle}
          metric={summary ? String(summary.hoursAboveThreshold) : "—"}
          unit="hours"
          caption={`Reference threshold ${formatNumber(SATURATION_THRESHOLD)} SIIPS; no action recommendation inferred.`}
          variant={summary ? (summary.hoursAboveThreshold > 0 ? "critical" : "optimal") : "neutral"}
          sparkline={sparkline}
        />
        <StatCard
          label="Interval width"
          icon={Target}
          metric={summary ? formatNumber(summary.meanIntervalWidth) : "—"}
          unit="SIIPS"
          caption="Mean conformal 90% band width in raw SIIPS space."
          variant="neutral"
          sparkline={sparkline}
        />
      </div>

      <div className="grid grid-cols-[minmax(0,0.66fr)_minmax(360px,0.34fr)] gap-5">
        <ForecastChartCard
          chartData={chartData}
          serviceLabel={selectedService.label}
          isLoading={forecastQuery.isLoading}
          error={forecastQuery.error}
          onRetry={() => void forecastQuery.refetch()}
        />
        <PressureDriversPanel />
      </div>

      <div className="grid grid-cols-[minmax(0,0.58fr)_minmax(380px,0.42fr)] gap-5">
        <UnitRiskPanel selectedService={selectedService.label} results={results} />
        <RecommendedActionsPanel />
      </div>
    </section>
  );
}

function ScreenHeader({
  selectedService,
  serviceId,
  originLocal,
  horizon,
  isCapped,
  onServiceChange,
  onOriginChange,
  onHorizonChange
}: {
  selectedService: { id: string; label: string; specialty: string };
  serviceId: string;
  originLocal: string;
  horizon: HorizonOption;
  isCapped: boolean;
  onServiceChange: (serviceId: string) => void;
  onOriginChange: (origin: string) => void;
  onHorizonChange: (horizon: HorizonOption) => void;
}) {
  return (
    <header className="flex items-start justify-between gap-6">
      <div>
        <div className="flex items-center gap-2">
          <h1 id="forecast-title" className="text-screen text-text-strong">Pressure Forecast</h1>
          <LineChart className="h-5 w-5 text-brand-primary" aria-hidden="true" />
        </div>
        <p className="text-caption mt-2 max-w-3xl">
          Live v2 world-model forecast for {selectedService.label}. The screen fetches a canonical 120-hour feature window, then calls POST /forecast/charge with no future actions.
        </p>
      </div>
      <div className="flex min-w-[460px] flex-col items-end gap-3">
        <div className="grid w-full grid-cols-[1fr_190px] gap-3">
          <label className="block">
            <span className="text-card-label">Service</span>
            <span className="mt-1.5 flex items-center gap-2 rounded-full border border-border-subtle bg-bg-card px-4 py-2 shadow-card">
              <Hospital className="h-4 w-4 text-brand-primary" aria-hidden="true" />
              <select
                className="w-full bg-transparent text-body-strong text-text-strong outline-none"
                value={serviceId}
                onChange={(event) => onServiceChange(event.currentTarget.value)}
              >
                {SERVICE_OPTIONS.map((service) => (
                  <option key={service.id} value={service.id}>
                    {service.label}
                  </option>
                ))}
              </select>
            </span>
            <span className="text-caption mt-1 block">{selectedService.specialty}</span>
          </label>
          <label className="block">
            <span className="text-card-label">Origin</span>
            <input
              className="mt-1.5 h-[42px] w-full rounded-full border border-border-subtle bg-bg-card px-4 text-body-strong text-text-strong shadow-card outline-none focus:border-brand-primary"
              type="datetime-local"
              value={originLocal}
              onChange={(event) => onOriginChange(event.currentTarget.value)}
            />
          </label>
        </div>
        <SegmentedToggle value={horizon} onChange={onHorizonChange} options={["24H", "48H", "3D", "7D"]} label="Forecast horizon" />
        {isCapped ? <span className="text-caption">Model horizon is 48h; longer controls are capped.</span> : null}
      </div>
      <div className="sr-only" aria-live="polite">Selected service {serviceId}</div>
    </header>
  );
}

function ForecastChartCard({
  chartData,
  serviceLabel,
  isLoading,
  error,
  onRetry
}: {
  chartData: ForecastChartPoint[];
  serviceLabel: string;
  isLoading: boolean;
  error: Error | null;
  onRetry: () => void;
}) {
  return (
    <article className="rounded-card border border-border-subtle bg-bg-card p-5 shadow-card" aria-labelledby="forecast-chart-title">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div>
          <p className="text-card-label text-brand-primary">Real v2 forecast</p>
          <h2 id="forecast-chart-title" className="text-section mt-1 text-text-strong">Predicted SIIPS pressure · {serviceLabel}</h2>
        </div>
        <span className="text-badge rounded-full border border-border-subtle bg-bg-app px-3 py-1 text-text-muted">
          /history → /forecast
        </span>
      </div>

      {isLoading ? <ChartSkeleton /> : null}
      {error ? <ChartError error={error} onRetry={onRetry} /> : null}
      {!isLoading && !error ? <ForecastChart chartData={chartData} /> : null}

      <div className="mt-4 flex flex-wrap gap-3 text-caption">
        <LegendSwatch className="bg-brand-primary" label="Predicted SIIPS" />
        <LegendSwatch className="bg-brand-primary/20" label="90% interval" />
        <LegendSwatch className="bg-status-critical" label="Saturation threshold" />
        <LegendSwatch className="bg-status-high" label="Peak marker" />
      </div>
    </article>
  );
}

function ForecastChart({ chartData }: { chartData: ForecastChartPoint[] }) {
  const peak = chartData.reduce<ForecastChartPoint | null>((current, point) => (!current || point.predicted > current.predicted ? point : current), null);
  return (
    <div className="h-[420px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 16, right: 22, bottom: 12, left: -4 }}>
          <defs>
            <linearGradient id="forecastIntervalBand" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="var(--brand-primary)" stopOpacity={0.18} />
              <stop offset="100%" stopColor="var(--brand-primary)" stopOpacity={0.03} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--border-subtle)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="hour"
            tickLine={false}
            axisLine={false}
            tick={{ fontSize: 11, fill: "var(--text-muted)" }}
            tickFormatter={(value) => `T+${value}`}
            label={{ value: "Operational horizon (hours)", position: "insideBottom", offset: -6, fill: "var(--text-muted)", fontSize: 11 }}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            tick={{ fontSize: 11, fill: "var(--text-muted)" }}
            label={{ value: "Predicted SIIPS", angle: -90, position: "insideLeft", fill: "var(--text-muted)", fontSize: 11 }}
          />
          <Tooltip
            cursor={{ stroke: "var(--brand-primary)", strokeDasharray: "3 3" }}
            content={<ForecastTooltip />}
          />
          <Area type="monotone" dataKey="intervalBase" stackId="forecast-band" stroke="transparent" fill="transparent" activeDot={false} />
          <Area type="monotone" dataKey="intervalWidth" stackId="forecast-band" stroke="transparent" fill="url(#forecastIntervalBand)" activeDot={false} />
          <ReferenceLine y={SATURATION_THRESHOLD} stroke="var(--status-critical)" strokeDasharray="6 6" strokeWidth={1.5} label={{ value: "Saturation threshold", position: "insideTopRight", fill: "var(--status-critical)", fontSize: 11 }} />
          <Line type="monotone" dataKey="predicted" name="Predicted SIIPS" stroke="var(--brand-primary)" strokeWidth={2.6} dot={false} activeDot={{ r: 5 }} />
          {peak ? <ReferenceDot x={peak.hour} y={peak.predicted} r={5} fill="var(--status-high)" stroke="var(--bg-card)" strokeWidth={2} /> : null}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function ForecastTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ payload: ForecastChartPoint }>; label?: number }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <div className="text-badge text-text-muted">T+{label}h</div>
      <div className="mt-1 text-body-strong numeric-tabular">{formatNumber(point.predicted)} SIIPS</div>
      <div className="text-caption">90% interval {formatNumber(point.lower)}–{formatNumber(point.upper)}</div>
    </div>
  );
}

function PressureDriversPanel() {
  // MOCK: needs feature-attribution endpoint for ED inflow, discharge deficit, LOS, acuity and staffing drivers.
  const drivers = [
    { label: "ED inflow", value: "+28%", variant: "critical" as StatusVariant },
    { label: "Discharge deficit", value: "-32 beds", variant: "high" as StatusVariant },
    { label: "Length-of-stay drag", value: "+11%", variant: "elevated" as StatusVariant },
    { label: "Staffing tension", value: "+7 pts", variant: "elevated" as StatusVariant }
  ];
  return (
    <aside className="rounded-card border border-border-subtle bg-bg-card p-5 shadow-card" aria-labelledby="drivers-title">
      <p className="text-card-label text-brand-primary">Pressure drivers</p>
      <h2 id="drivers-title" className="text-section mt-1 text-text-strong">Operational signals</h2>
      <p className="text-caption mt-2">Mocked until backend attribution is available; the main forecast chart is live.</p>
      <div className="mt-5 space-y-3">
        {drivers.map((driver) => (
          <div key={driver.label} className="flex items-center justify-between rounded-card border border-border-subtle bg-bg-app px-4 py-3">
            <span className="text-body-strong">{driver.label}</span>
            <span className={`text-badge numeric-tabular rounded-full px-2 py-1 ${variantTextClass(driver.variant)}`}>{driver.value}</span>
          </div>
        ))}
      </div>
    </aside>
  );
}

function UnitRiskPanel({ selectedService, results }: { selectedService: string; results: ForecastStep[] }) {
  const columns: DataTableColumn[] = [
    { key: "unit", header: "Unit" },
    { key: "status", header: "Risk" },
    { key: "peak", header: "Peak", align: "right" },
    { key: "trend", header: "Trend" },
    { key: "action", header: "Action", align: "right" }
  ];
  const rows: DataTableRow[] = [
    {
      id: "selected-service",
      cells: {
        unit: { type: "text", value: selectedService, muted: "Real selected-service forecast" },
        status: { type: "status", status: variantFromSiips(Math.max(...results.map((step) => step.predicted_siips), 0)) },
        peak: { type: "text", value: results.length ? `${formatNumber(Math.max(...results.map((step) => step.predicted_siips)))} SIIPS` : "Pending" },
        trend: { type: "sparkline", data: toSparkline(buildChartData(results)), variant: "optimal" },
        action: { type: "action", label: "View" }
      }
    },
    // MOCK: needs all-services forecast aggregation endpoint before table can be fully real.
    {
      id: "mock-service",
      cells: {
        unit: { type: "text", value: "All other services", muted: "Mock backlog row" },
        status: { type: "status", status: "neutral", label: "Needs endpoint" },
        peak: { type: "text", value: "—" },
        trend: { type: "sparkline", data: [{ label: "T+1", value: 0 }, { label: "T+2", value: 0 }], variant: "neutral" },
        action: { type: "action", label: "Backlog" }
      }
    }
  ];
  return (
    <div className="space-y-5">
      <div>
        <p className="text-card-label text-brand-primary">Unit risk heatmap</p>
        <div className="mt-3">
          <HeatmapGrid units={["ED", "Medicine", "Surgery"]} hours={["00", "06", "12", "18"]} cells={mockHeatmapCells()} />
        </div>
        <p className="text-caption mt-2">{/* MOCK: needs endpoint forecasting all services and binning risk by hour. */}Heatmap is mocked; selected-service table row uses live forecast output.</p>
      </div>
      <DataTable columns={columns} rows={rows} footerLink="View all units" />
    </div>
  );
}

function RecommendedActionsPanel() {
  return (
    <aside className="space-y-3" aria-label="Recommended actions">
      {/* MOCK: needs action recommendation endpoint; no action is inferred from /forecast/charge. */}
      <RecommendedActionCard rank={1} title="Accelerate confirmed discharges" subtitle="Needs backend action engine; shown as mock backlog" pressureDelta="↓ 18 pts" financialImpact="€12k" />
      <RecommendedActionCard rank={2} title="Open flex capacity pod" subtitle="Needs bed-state endpoint and operational rules" pressureDelta="↓ 11 pts" financialImpact="€8k" />
      <RecommendedActionCard rank={3} title="Rebalance float pool" subtitle="Needs staffing coverage endpoint" pressureDelta="↓ 7 pts" financialImpact="€5k" />
    </aside>
  );
}

function ChartSkeleton() {
  return (
    <div className="h-[420px] animate-pulse rounded-card bg-bg-app p-6">
      <div className="h-full rounded-card border border-border-subtle bg-bg-card/70" />
    </div>
  );
}

function ChartError({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div className="rounded-card border border-status-critical/30 bg-status-critical/10 p-5" role="alert">
      <p className="text-body-strong text-status-critical">Forecast unavailable</p>
      <p className="text-body-copy mt-2 text-text-body">{error.message}</p>
      <button type="button" className="text-control mt-4 rounded-full bg-brand-primary px-4 py-2 text-white" onClick={onRetry}>
        Retry forecast chain
      </button>
    </div>
  );
}

function LegendSwatch({ className, label }: { className: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className={`h-2.5 w-2.5 rounded-full ${className}`} aria-hidden="true" />
      {label}
    </span>
  );
}

function buildChartData(results: ForecastStep[]): ForecastChartPoint[] {
  return results.map((step) => ({
    hour: step.step_index,
    predicted: step.predicted_siips,
    lower: step.lower_90,
    upper: step.upper_90,
    intervalBase: step.lower_90,
    intervalWidth: Math.max(0, step.upper_90 - step.lower_90),
    threshold: SATURATION_THRESHOLD
  }));
}

function summarizeForecast(results: ForecastStep[]) {
  if (results.length === 0) return null;
  const peak = results.reduce((current, step) => (step.predicted_siips > current.predicted_siips ? step : current), results[0]);
  const meanIntervalWidth = results.reduce((sum, step) => sum + step.upper_90 - step.lower_90, 0) / results.length;
  const hoursAboveThreshold = results.filter((step) => step.predicted_siips >= SATURATION_THRESHOLD).length;
  return { peak, meanIntervalWidth, hoursAboveThreshold };
}

function toSparkline(chartData: ForecastChartPoint[]): SparklinePoint[] {
  return chartData.slice(0, 18).map((point) => ({ label: `T+${point.hour}`, value: point.predicted }));
}

function toUtcTimestamp(localValue: string): string {
  return `${localValue}:00Z`;
}

function variantFromSiips(value: number): StatusVariant {
  if (value >= SATURATION_THRESHOLD) return "critical";
  if (value >= SATURATION_THRESHOLD * 0.88) return "high";
  if (value >= SATURATION_THRESHOLD * 0.72) return "elevated";
  return "optimal";
}

function variantTextClass(variant: StatusVariant): string {
  if (variant === "critical") return "text-status-critical bg-status-critical/10";
  if (variant === "high") return "text-status-high bg-status-high/10";
  if (variant === "elevated") return "text-status-elevated bg-status-elevated/15";
  if (variant === "good" || variant === "optimal") return "text-status-good bg-status-good/10";
  return "text-text-muted bg-bg-card";
}

function mockHeatmapCells(): HeatmapCell[] {
  // MOCK: needs endpoint forecasting every service and hour; deterministic values keep the layout contract visible.
  const units = ["ED", "Medicine", "Surgery"];
  const hours = ["00", "06", "12", "18"];
  return units.flatMap((unit, unitIndex) =>
    hours.map((hour, hourIndex) => {
      const value = 48 + unitIndex * 16 + hourIndex * 9;
      return {
        unit,
        hour,
        value,
        status: value >= 88 ? "critical" : value >= 72 ? "high" : value >= 56 ? "elevated" : "optimal"
      };
    })
  );
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}
