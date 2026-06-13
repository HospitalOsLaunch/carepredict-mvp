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
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-primary text-sm font-bold text-white">{rank}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold text-text-strong">{title}</span>
        <span className="mt-1 block text-sm text-text-muted">{subtitle}</span>
      </span>
      <span className="grid gap-1 text-right text-xs">
        <span className="font-semibold text-status-good">Pressure {pressureDelta}</span>
        <span className="font-semibold text-text-body">Financial {financialImpact}</span>
      </span>
    </button>
  );
}
