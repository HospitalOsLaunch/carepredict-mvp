import {
  Area,
  CartesianGrid,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  LineChart
} from "recharts";

import type { ScenarioPoint } from "../domain/insights";

interface ScenarioTrajectoryChartProps {
  points: ScenarioPoint[];
  showCustom?: boolean;
  compact?: boolean;
  ariaLabel?: string;
}

export function ScenarioTrajectoryChart({ points, showCustom = true, compact = false, ariaLabel = "Évolution prévue de la charge en soins" }: ScenarioTrajectoryChartProps) {
  const customDiffers = points.some((point) => point.custom !== point.recommended);
  const includesCriticalWindow = points.some((point) => point.timeLabel === "16h") && points.some((point) => point.timeLabel === "20h");
  return (
    <div className="min-w-0 space-y-3" aria-label={ariaLabel}>
      <div className="h-[260px] min-w-0 w-full" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 18, right: 18, bottom: 4, left: -12 }}>
            <CartesianGrid stroke="#d9dee8" strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="timeLabel" tick={{ fill: "#657181", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "#b9c4d3" }} />
            <YAxis domain={[1300, 1900]} ticks={[1400, 1600, 1800]} tick={{ fill: "#657181", fontSize: 11 }} tickLine={false} axisLine={false} width={42} />
            <Tooltip content={<ScenarioTooltip />} cursor={{ stroke: "#8a96a6", strokeDasharray: "3 3" }} />
            {includesCriticalWindow ? <ReferenceArea x1="16h" x2="20h" fill="#f36b5f" fillOpacity={0.08} ifOverflow="extendDomain" /> : null}
            <ReferenceLine y={1600} stroke="#c94040" strokeDasharray="5 5" label={{ value: "Seuil du scénario · 1 600 SIIPS", position: "insideTopRight", fill: "#9b3333", fontSize: 10 }} />
            <Area type="monotone" dataKey="upperBound" stroke="none" fill="#b9dfe1" fillOpacity={0.24} />
            <Area type="monotone" dataKey="lowerBound" stroke="none" fill="#ffffff" fillOpacity={1} />
            <Line type="monotone" dataKey="baseline" name="Plan actuel" stroke="#697586" strokeWidth={2.5} dot={{ r: compact ? 0 : 2, fill: "#697586" }} activeDot={{ r: 5 }} />
            <Line type="monotone" dataKey="recommended" name="HospitalOS" stroke="#169c9a" strokeWidth={3} dot={{ r: compact ? 0 : 2, fill: "#169c9a" }} activeDot={{ r: 5 }} />
            {showCustom && customDiffers ? <Line type="monotone" dataKey="custom" name="Votre option" stroke="#d47b35" strokeWidth={2.5} strokeDasharray="6 4" dot={{ r: compact ? 0 : 2, fill: "#d47b35" }} activeDot={{ r: 5 }} /> : null}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-caption">
        <span className="font-medium text-text-body">Charge en soins · SIIPS</span>
        <span><i className="mr-2 inline-block h-2 w-6 rounded-full bg-[#697586]" />Plan actuel</span>
        <span><i className="mr-2 inline-block h-2 w-6 rounded-full bg-[#169c9a]" />Recommandation HospitalOS</span>
        {showCustom && customDiffers ? <span><i className="mr-2 inline-block h-0.5 w-6 border-t-2 border-dashed border-[#d47b35]" />Votre option</span> : null}
        {includesCriticalWindow ? <span className="text-status-critical">Fenêtre critique · 16h–20h</span> : null}
      </div>
      <p className="sr-only">{includesCriticalWindow ? "Le pic du plan actuel est à 18h. La zone rouge indique la fenêtre critique de 16h à 20h. " : "La fenêtre critique se situe au-delà de l’horizon affiché. "}Le seuil du scénario est fixé à 1 600 SIIPS pour cette recherche.</p>
    </div>
  );
}

function ScenarioTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name?: string; value?: number; color?: string }>; label?: string }) {
  if (!active || !payload?.length) return null;
  const siipsEntries = payload.filter((entry) => ["Plan actuel", "HospitalOS", "Votre option"].includes(entry.name ?? "") && typeof entry.value === "number");
  return (
    <div className="chart-tooltip" role="tooltip">
      <p className="font-semibold text-text-strong">{label}</p>
      {siipsEntries.map((entry) => <p key={entry.name} style={{ color: entry.color }}>{entry.name} · {formatSiipsTooltipValue(entry.value as number)}</p>)}
    </div>
  );
}

export function formatSiipsTooltipValue(value: number): string {
  return `${value.toLocaleString("fr-FR")} SIIPS`;
}
