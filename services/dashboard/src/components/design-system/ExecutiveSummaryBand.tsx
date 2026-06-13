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
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-status-elevated/15 text-xl text-status-elevated" aria-hidden="true">
          ☼
        </div>
        <div className="min-w-0 flex-1">
          <h2 id="executive-summary-title" className="text-[17px] font-semibold text-text-strong">
            Executive Summary
          </h2>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-text-body">{summary}</p>
          <div className="mt-5 grid grid-cols-3 gap-4">
            {columns.map((column) => (
              <article key={column.label} className="rounded-2xl bg-bg-app p-4">
                <p className="text-[13px] font-semibold uppercase tracking-wide text-text-muted">{column.label}</p>
                <p className="mt-2 text-sm leading-5 text-text-strong">{column.value}</p>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
