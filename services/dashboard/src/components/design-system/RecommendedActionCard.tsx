interface RecommendedActionCardProps {
  rank: number;
  title: string;
  subtitle: string;
  pressureDelta: string;
  financialImpact: string;
}

export function RecommendedActionCard({ rank, title, subtitle, pressureDelta, financialImpact }: RecommendedActionCardProps) {
  return (
    <button
      type="button"
      className="group flex w-full items-center gap-4 rounded-card border border-border-subtle bg-bg-card p-4 text-left shadow-card outline-none transition hover:-translate-y-0.5 hover:shadow-lg focus-visible:ring-2 focus-visible:ring-brand-primary"
    >
      <span className="numeric-tabular flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-primary text-rank text-white">{rank}</span>
      <span className="min-w-0 flex-1">
        <span className="text-body-strong block">{title}</span>
        <span className="text-caption mt-1 block">{subtitle}</span>
      </span>
      <span className="text-badge grid gap-1 text-right">
        <span className="numeric-tabular text-status-good">Pressure {pressureDelta}</span>
        <span className="numeric-tabular text-text-body">Financial {financialImpact}</span>
      </span>
    </button>
  );
}
