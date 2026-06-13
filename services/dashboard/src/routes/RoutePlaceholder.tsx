interface RoutePlaceholderProps {
  title: string;
  subtitle: string;
  realData: string;
  mockData: string;
}

export function RoutePlaceholder({ title, subtitle, realData, mockData }: RoutePlaceholderProps) {
  return (
    <section className="rounded-card border border-border-subtle bg-bg-card p-8 shadow-card" aria-labelledby="screen-title">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-primary">UI-0 scaffold</p>
      <h1 id="screen-title" className="text-[28px] font-bold leading-tight text-text-strong">
        {title}
      </h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-text-muted">{subtitle}</p>
      <div className="mt-8 grid grid-cols-2 gap-4">
        <article className="rounded-2xl border border-border-subtle bg-bg-app p-4">
          <h2 className="text-sm font-semibold text-text-strong">Real API source</h2>
          <p className="mt-2 text-sm text-text-body">{realData}</p>
        </article>
        <article className="rounded-2xl border border-border-subtle bg-bg-app p-4">
          <h2 className="text-sm font-semibold text-text-strong">Typed mock coverage</h2>
          <p className="mt-2 text-sm text-text-body">{mockData}</p>
        </article>
      </div>
    </section>
  );
}
