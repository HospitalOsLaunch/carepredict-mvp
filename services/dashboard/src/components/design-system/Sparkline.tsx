import { statusFillTextClass, statusStrokeClass, statusTextClass } from "./status";
import type { SparklinePoint, StatusVariant } from "./types";

interface SparklineProps {
  data: SparklinePoint[];
  variant?: StatusVariant;
  height?: number;
  label?: string;
  showDots?: boolean;
}

export function Sparkline({ data, variant = "neutral", height = 36, label = "Trend", showDots = false }: SparklineProps) {
  const width = 160;
  const values = data.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = Math.max(max - min, 1);
  const points = data.map((point, index) => {
    const x = data.length === 1 ? width / 2 : (index / (data.length - 1)) * width;
    const y = height - ((point.value - min) / spread) * (height - 6) - 3;
    return { x, y, point };
  });
  const line = points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const area = `0,${height} ${line} ${width},${height}`;

  return (
    <svg className="h-full w-full overflow-visible" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      <title>{label}</title>
      <polygon className={statusFillTextClass[variant]} fill="currentColor" opacity="0.14" points={area} />
      <polyline className={statusStrokeClass[variant]} fill="none" points={line} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      {showDots
        ? points.map(({ x, y, point }) => (
            <circle key={`${point.label}-${x}`} className={statusTextClass[variant]} cx={x} cy={y} r="1.8" fill="currentColor">
              <title>{`${point.label}: ${point.value}`}</title>
            </circle>
          ))
        : null}
    </svg>
  );
}
