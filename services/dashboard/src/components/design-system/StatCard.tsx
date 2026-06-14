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
  badge?: string;
  compact?: boolean;
}

export function StatCard({ label, icon: Icon, metric, unit, caption, variant = "neutral", sparkline, badge, compact = false }: StatCardProps) {
  return (
    <article className={`flex flex-col rounded-card border bg-bg-card shadow-card ${compact ? "h-[164px] p-4 opacity-90" : "h-[196px] p-5"} ${statusBorderClass[variant]}`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-card-label">{label}</p>
          {badge ? <span className="text-badge mt-1.5 inline-flex rounded-full border border-status-elevated/30 bg-status-elevated/10 px-2 py-0.5 text-status-high">{badge}</span> : null}
        </div>
        <div className={`flex items-center justify-center rounded-full ${compact ? "h-8 w-8" : "h-9 w-9"} ${statusSoftBgClass[variant]} ${statusTextClass[variant]}`} aria-hidden="true">
          <Icon className={compact ? "h-4 w-4" : "h-[18px] w-[18px]"} strokeWidth={2.2} />
        </div>
      </div>
      <div className={`${compact ? "mt-2" : "mt-2.5"} flex items-baseline gap-1`}>
        <strong className={`text-hero numeric-tabular ${variant === "neutral" ? "text-text-strong" : statusTextClass[variant]}`}>{metric}</strong>
        {unit ? <span className="text-unit">{unit}</span> : null}
      </div>
      <p className={`text-caption mt-1.5 line-clamp-2 ${compact ? "min-h-[30px]" : "min-h-[34px]"}`}>{caption}</p>
      <div className={`mt-auto ${compact ? "h-7 pt-2" : "h-9 pt-3"}`}>
        <Sparkline data={sparkline} variant={variant} height={compact ? 24 : 36} label={`${label} trend`} />
      </div>
    </article>
  );
}
