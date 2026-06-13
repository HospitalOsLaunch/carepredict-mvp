import { Sparkline } from "./Sparkline";
import { statusBorderClass, statusSoftBgClass, statusTextClass } from "./status";
import type { SparklinePoint, StatusVariant } from "./types";

interface StatCardProps {
  label: string;
  icon: string;
  metric: string;
  unit?: string;
  caption: string;
  variant?: StatusVariant;
  sparkline: SparklinePoint[];
}

export function StatCard({ label, icon, metric, unit, caption, variant = "neutral", sparkline }: StatCardProps) {
  return (
    <article className={`rounded-card border bg-bg-card p-5 shadow-card ${statusBorderClass[variant]}`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[13px] font-semibold uppercase tracking-wide text-text-muted">{label}</p>
          <div className="mt-3 flex items-end gap-2">
            <strong className={`text-[34px] font-bold leading-none ${variant === "neutral" ? "text-text-strong" : statusTextClass[variant]}`}>{metric}</strong>
            {unit ? <span className="pb-1 text-sm font-medium text-text-muted">{unit}</span> : null}
          </div>
        </div>
        <div className={`flex h-10 w-10 items-center justify-center rounded-2xl text-lg ${statusSoftBgClass[variant]} ${statusTextClass[variant]}`} aria-hidden="true">
          {icon}
        </div>
      </div>
      <p className="mt-3 text-sm text-text-muted">{caption}</p>
      <div className="mt-4 h-11">
        <Sparkline data={sparkline} variant={variant} label={`${label} trend`} />
      </div>
    </article>
  );
}
