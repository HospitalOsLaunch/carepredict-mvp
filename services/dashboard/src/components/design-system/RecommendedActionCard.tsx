interface RecommendedActionCardProps {
  rank: number;
  title: string;
  subtitle: string;
  pressureDelta: string;
  financialImpact: string;
  sourceLabel?: string;
  source?: "live" | "illustrative";
  ctaLabel?: string;
  onClick?: () => void;
}

export function RecommendedActionCard({ rank, title, subtitle, pressureDelta, financialImpact, sourceLabel, source = "illustrative", ctaLabel, onClick }: RecommendedActionCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex w-full items-center gap-4 rounded-card border border-border-subtle bg-bg-card p-4 text-left shadow-card outline-none transition hover:-translate-y-0.5 hover:shadow-lg focus-visible:ring-2 focus-visible:ring-brand-primary"
    >
      <span className="numeric-tabular flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-primary text-rank text-white">{rank}</span>
      <span className="min-w-0 flex-1">
        {sourceLabel ? <span className={`text-badge mb-2 inline-flex rounded-full border px-2 py-0.5 ${source === "live" ? "border-status-good/30 bg-status-good/10 text-status-good" : "border-status-elevated/30 bg-status-elevated/10 text-status-high"}`}>{sourceLabel}</span> : null}
        <span className="text-body-strong block">{title}</span>
        <span className="text-caption mt-1 block">{subtitle}</span>
        {ctaLabel ? <span className="text-control mt-2 block text-brand-primary">{ctaLabel} →</span> : null}
      </span>
      <span className="text-badge grid gap-1 text-right">
        <span className="numeric-tabular text-status-good">Pressure {pressureDelta}</span>
        <span className="numeric-tabular text-text-body">Financial {financialImpact}</span>
      </span>
    </button>
  );
}
