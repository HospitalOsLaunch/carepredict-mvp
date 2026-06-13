import { Sun } from "lucide-react";

interface SummaryColumn {
  label: string;
  value: string;
}

interface ExecutiveSummaryBandProps {
  summary: string;
  columns: SummaryColumn[];
}

export function ExecutiveSummaryBand({ summary, columns }: ExecutiveSummaryBandProps) {
  return (
    <section className="rounded-card border border-border-subtle bg-bg-card p-6 shadow-card" aria-labelledby="executive-summary-title">
      <div className="flex gap-5">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-status-elevated/15 text-status-elevated" aria-hidden="true">
          <Sun className="h-5 w-5" strokeWidth={2.2} />
        </div>
        <div className="min-w-0 flex-1">
          <h2 id="executive-summary-title" className="text-section text-text-strong">
            Executive Summary
          </h2>
          <p className="text-body-copy mt-2 max-w-4xl">{summary}</p>
          <div className="mt-5 grid grid-cols-3 gap-4">
            {columns.map((column) => (
              <article key={column.label} className="rounded-card bg-bg-app p-4">
                <p className="text-card-label">{column.label}</p>
                <p className="text-body-strong mt-2">{column.value}</p>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
