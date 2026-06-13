import { statusBgClass, statusCopy, statusSoftBgClass, statusTextClass } from "./status";
import type { StatusVariant } from "./types";

interface PressureBadgeProps {
  status: StatusVariant;
  score?: number;
  label?: string;
}

export function PressureBadge({ status, score, label }: PressureBadgeProps) {
  return (
    <span className={`text-badge inline-flex items-center gap-2 rounded-full px-2.5 py-1 ${statusSoftBgClass[status]} ${statusTextClass[status]}`}>
      <span className={`h-2 w-2 rounded-full ${statusBgClass[status]}`} aria-hidden="true" />
      <span>{label ?? statusCopy[status]}</span>
      {score !== undefined ? <span className="numeric-tabular rounded-full bg-bg-card/80 px-1.5 py-0.5 text-text-strong">{score}</span> : null}
    </span>
  );
}
