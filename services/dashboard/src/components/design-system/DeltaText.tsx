interface DeltaTextProps {
  value: number;
  unit?: string;
  inverted?: boolean;
}

export function DeltaText({ value, unit = "pts", inverted = false }: DeltaTextProps) {
  const isPositive = value >= 0;
  const isGood = inverted ? !isPositive : isPositive;
  const arrow = isPositive ? "↑" : "↓";
  const className = isGood ? "text-status-good" : "text-status-critical";

  return (
    <span className={`inline-flex items-center gap-1 text-sm font-semibold ${className}`}>
      <span aria-hidden="true">{arrow}</span>
      <span>
        {Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 0 })} {unit}
      </span>
    </span>
  );
}
