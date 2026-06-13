import { useState } from "react";

import { statusBgClass, statusCopy } from "./status";
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
  const [activeCell, setActiveCell] = useState<HeatmapCell | null>(null);
  const byKey = new Map(cells.map((cell) => [`${cell.unit}-${cell.hour}`, cell]));

  return (
    <div className="relative rounded-card border border-border-subtle bg-bg-card p-5 shadow-card">
      <div className="grid gap-2" style={{ gridTemplateColumns: `120px repeat(${hours.length}, minmax(28px, 1fr))` }}>
        <div />
        {hours.map((hour) => (
          <div key={hour} className="text-badge numeric-tabular text-center text-text-muted">
            {hour}
          </div>
        ))}
        {units.map((unit) => (
          <div key={unit} className="contents">
            <div className="text-body-strong py-1">{unit}</div>
            {hours.map((hour) => {
              const cell = byKey.get(`${unit}-${hour}`);
              return (
                <button
                  key={`${unit}-${hour}`}
                  type="button"
                  className={`h-8 rounded-lg outline-none ring-brand-primary/0 transition hover:ring-2 focus-visible:ring-2 ${cell ? statusBgClass[cell.status] : "bg-bg-app"}`}
                  aria-label={`${unit} ${hour}: ${cell ? `${statusCopy[cell.status]}, ${cell.value}` : "no value"}`}
                  onBlur={() => setActiveCell(null)}
                  onFocus={() => setActiveCell(cell ?? null)}
                  onMouseEnter={() => setActiveCell(cell ?? null)}
                  onMouseLeave={() => setActiveCell(null)}
                />
              );
            })}
          </div>
        ))}
      </div>
      {activeCell ? (
        <div className="chart-tooltip pointer-events-none absolute right-5 top-5 z-20">
          <div className="text-badge text-text-muted">{activeCell.unit} · {activeCell.hour}:00</div>
          <div className="mt-1 text-body-strong numeric-tabular">{activeCell.value} pressure</div>
          <div className="text-caption">{statusCopy[activeCell.status]}</div>
        </div>
      ) : null}
    </div>
  );
}
