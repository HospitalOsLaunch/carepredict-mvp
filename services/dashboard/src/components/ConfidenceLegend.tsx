interface ConfidenceLegendProps {
  coverage: number;
}

export function ConfidenceLegend({ coverage }: ConfidenceLegendProps) {
  return (
    <aside className="confidence">
      <strong>Intervalle {Math.round(coverage * 100)}%</strong>
      <p>La bande indique l'intervalle dans lequel la charge réelle se situera 9 fois sur 10</p>
    </aside>
  );
}
