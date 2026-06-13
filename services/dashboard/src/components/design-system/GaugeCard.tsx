import { Sparkline } from "./Sparkline";
import { statusCopy, statusStrokeClass, statusTextClass } from "./status";
import type { SparklinePoint, StatusVariant } from "./types";

interface GaugeCardProps {
  title: string;
  value: number;
  label: string;
  variant: StatusVariant;
  trend: SparklinePoint[];
  yesterday: number;
  sevenDayAverage: number;
}

export function GaugeCard({ title, value, label, variant, trend, yesterday, sevenDayAverage }: GaugeCardProps) {
  const clamped = Math.max(0, Math.min(100, value));
  const radius = 58;
  const circumference = Math.PI * radius;
  const dash = (clamped / 100) * circumference;
  const needleAngle = -90 + clamped * 1.8;

  return (
    <article className="rounded-card border border-border-subtle bg-bg-card p-6 shadow-card">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[13px] font-semibold uppercase tracking-wide text-text-muted">{title}</p>
          <h2 className="mt-1 text-lg font-semibold text-text-strong">{label}</h2>
        </div>
        <span className={`text-sm font-semibold ${statusTextClass[variant]}`}>{statusCopy[variant]}</span>
      </div>
      <div className="relative mx-auto mt-5 h-[140px] w-[220px]">
        <svg viewBox="0 0 220 140" role="img" aria-label={`${title}: ${value} ${label}`}>
          <path d="M 36 112 A 74 74 0 0 1 184 112" className="stroke-bg-app" fill="none" strokeWidth="18" strokeLinecap="round" />
          <path
            d="M 36 112 A 74 74 0 0 1 184 112"
            className={statusStrokeClass[variant]}
            fill="none"
            strokeWidth="18"
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circumference}`}
          />
          <line
            x1="110"
            y1="112"
            x2="110"
            y2="48"
            className="stroke-text-strong"
            strokeWidth="3"
            strokeLinecap="round"
            transform={`rotate(${needleAngle} 110 112)`}
          />
          <circle cx="110" cy="112" r="6" className="fill-text-strong" />
        </svg>
        <div className="absolute inset-x-0 bottom-2 text-center">
          <strong className="text-[32px] font-bold leading-none text-text-strong">{Math.round(value)}</strong>
          <span className="ml-2 text-sm font-semibold text-text-muted">/ {label}</span>
        </div>
      </div>
      <div className="mt-3 h-10">
        <Sparkline data={trend} variant={variant} label={`${title} trend`} />
      </div>
      <p className="mt-3 text-sm text-text-muted">
        Yesterday: <span className="font-semibold text-text-body">{yesterday}</span> ↑ / 7d avg: <span className="font-semibold text-text-body">{sevenDayAverage}</span>
      </p>
    </article>
  );
}
