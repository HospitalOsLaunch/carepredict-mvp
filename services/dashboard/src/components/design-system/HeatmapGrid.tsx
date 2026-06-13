import { statusBgClass } from "./status";
import type { StatusVariant } from "./types";

export interface HeatmapCell {
  unit: string;
  hour: string;
  value: number;
  status: StatusVariant;
}

interface HeatmapGridProps {
  units: string[];
  hours: string[];
  cells: HeatmapCell[];
}

export function HeatmapGrid({ units, hours, cells }: HeatmapGridProps) {
  const byKey = new Map(cells.map((cell) => [`${cell.unit}-${cell.hour}`, cell]));

  return (
    <div className="rounded-card border border-border-subtle bg-bg-card p-5 shadow-card">
      <div className="grid gap-2" style={{ gridTemplateColumns: `120px repeat(${hours.length}, minmax(28px, 1fr))` }}>
        <div />
        {hours.map((hour) => (
          <div key={hour} className="text-center text-xs font-semibold text-text-muted">
            {hour}
          </div>
        ))}
        {units.map((unit) => (
          <div key={unit} className="contents">
            <div className="py-1 text-sm font-semibold text-text-body">{unit}</div>
            {hours.map((hour) => {
              const cell = byKey.get(`${unit}-${hour}`);
              return (
                <div
                  key={`${unit}-${hour}`}
                  className={`h-8 rounded-lg ${cell ? statusBgClass[cell.status] : "bg-bg-app"}`}
                  aria-label={`${unit} ${hour}: ${cell?.value ?? 0}`}
                  title={`${unit} ${hour}: ${cell?.value ?? 0}`}
                />
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
