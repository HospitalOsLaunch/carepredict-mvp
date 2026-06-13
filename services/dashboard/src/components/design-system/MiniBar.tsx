import { statusBgClass, statusFromScore } from "./status";
import type { StatusVariant } from "./types";

interface MiniBarProps {
  value: number;
  max?: number;
  label?: string;
  variant?: StatusVariant;
}

export function MiniBar({ value, max = 100, label = "Saturation", variant }: MiniBarProps) {
  const percent = Math.max(0, Math.min(100, (value / max) * 100));
  const resolvedVariant = variant ?? statusFromScore(percent);

  return (
    <div className="min-w-[120px]" aria-label={`${label}: ${Math.round(percent)} percent`}>
      <div className="text-caption flex items-center justify-between">
        <span>{label}</span>
        <span className="numeric-tabular text-body-strong">{Math.round(percent)}%</span>
      </div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-bg-app">
        <div className={`h-full rounded-full ${statusBgClass[resolvedVariant]}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
