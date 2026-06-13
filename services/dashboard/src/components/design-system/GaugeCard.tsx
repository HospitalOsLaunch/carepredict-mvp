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
  polarity?: "pressure" | "positive";
}

export function GaugeCard({ title, value, label, variant, trend, yesterday, sevenDayAverage, polarity = "pressure" }: GaugeCardProps) {
  const clamped = Math.max(0, Math.min(100, value));
  const radius = 64;
  const circumference = Math.PI * radius;
  const dash = (clamped / 100) * circumference;
  const needleAngle = -90 + clamped * 1.8;
  const trendUpIsGood = polarity === "positive";
  const arrowClass = trendUpIsGood ? "text-status-good" : "text-status-critical";

  return (
    <article className="rounded-card border border-border-subtle bg-bg-card p-5 shadow-card">
      <div className="flex items-start justify-between gap-4">
        <p className="text-card-label">{title}</p>
        <span className={`text-badge ${statusTextClass[variant]}`}>{statusCopy[variant]}</span>
      </div>
      <div className="relative mx-auto mt-2 h-[118px] w-[220px]">
        <svg className="absolute inset-0" viewBox="0 0 220 126" role="img" aria-label={`${title}: ${value} ${label}`}>
          <path d="M 38 100 A 72 72 0 0 1 182 100" className="stroke-gauge-track" fill="none" strokeWidth="14" strokeLinecap="round" />
          <path
            d="M 38 100 A 72 72 0 0 1 182 100"
            className={statusStrokeClass[variant]}
            fill="none"
            strokeWidth="14"
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circumference}`}
          />
          <line
            x1="110"
            y1="100"
            x2="110"
            y2="62"
            className="stroke-text-strong"
            strokeWidth="2"
            strokeLinecap="round"
            transform={`rotate(${needleAngle} 110 100)`}
          />
          <circle cx="110" cy="100" r="5" className="fill-text-strong" />
        </svg>
        <div className="numeric-tabular absolute inset-x-0 top-[70px] z-10 mx-auto flex max-w-[170px] items-baseline justify-center gap-1 rounded-full bg-bg-card/90 px-3 py-1 text-center backdrop-blur-sm">
          <strong className="text-gauge-number text-text-strong">{Math.round(value)}</strong>
          <span className="text-unit whitespace-nowrap">/ {label}</span>
        </div>
      </div>
      <div className="mt-1 h-8">
        <Sparkline data={trend} variant={variant} height={32} label={`${title} trend`} />
      </div>
      <p className="text-caption mt-2 numeric-tabular">
        Yesterday: <span className="text-text-body">{yesterday}</span> <span className={arrowClass}>↑</span> / 7d avg:{" "}
        <span className="text-text-body">{sevenDayAverage}</span>
      </p>
    </article>
  );
}
