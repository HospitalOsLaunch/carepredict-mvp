interface CurrentVsPredictedProps {
  current: number;
  predicted: number;
}

export function CurrentVsPredicted({ current, predicted }: CurrentVsPredictedProps) {
  const delta = predicted - current;
  const trend = delta >= 0 ? "hausse" : "baisse";
  const gaugeWidth = Math.min(Math.max(predicted, 0), 100);

  return (
    <section className="metric-grid" aria-label="Charges">
      <article className="metric-card">
        <span className="metric-label">Charge actuelle</span>
        <strong>{Math.round(current)}</strong>
        <div className="gauge" aria-hidden="true">
          <span style={{ width: `${Math.min(Math.max(current, 0), 100)}%` }} />
        </div>
      </article>
      <article className="metric-card accent">
        <span className="metric-label">Prédiction J+12h</span>
        <strong>{Math.round(predicted)}</strong>
        <span className="delta">
          {delta >= 0 ? "+" : ""}
          {delta.toFixed(1)} pts · {trend}
        </span>
        <div className="gauge" aria-hidden="true">
          <span style={{ width: `${gaugeWidth}%` }} />
        </div>
      </article>
    </section>
  );
}
