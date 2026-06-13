import type { LucideIcon } from "lucide-react";

import { Sparkline } from "./Sparkline";
import { statusBorderClass, statusSoftBgClass, statusTextClass } from "./status";
import type { SparklinePoint, StatusVariant } from "./types";

interface StatCardProps {
  label: string;
  icon: LucideIcon;
  metric: string;
  unit?: string;
  caption: string;
  variant?: StatusVariant;
  sparkline: SparklinePoint[];
}

export function StatCard({ label, icon: Icon, metric, unit, caption, variant = "neutral", sparkline }: StatCardProps) {
  return (
    <article className={`flex h-[196px] flex-col rounded-card border bg-bg-card p-5 shadow-card ${statusBorderClass[variant]}`}>
      <div className="flex items-start justify-between gap-4">
        <p className="text-card-label">{label}</p>
        <div className={`flex h-9 w-9 items-center justify-center rounded-full ${statusSoftBgClass[variant]} ${statusTextClass[variant]}`} aria-hidden="true">
          <Icon className="h-[18px] w-[18px]" strokeWidth={2.2} />
        </div>
      </div>
      <div className="mt-2.5 flex items-baseline gap-1">
        <strong className={`text-hero numeric-tabular ${variant === "neutral" ? "text-text-strong" : statusTextClass[variant]}`}>{metric}</strong>
        {unit ? <span className="text-unit">{unit}</span> : null}
      </div>
      <p className="text-caption mt-1.5 line-clamp-2 min-h-[34px]">{caption}</p>
      <div className="mt-auto h-9 pt-3">
        <Sparkline data={sparkline} variant={variant} label={`${label} trend`} />
      </div>
    </article>
  );
}
