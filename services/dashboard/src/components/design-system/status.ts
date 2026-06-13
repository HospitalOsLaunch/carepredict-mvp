import type { StatusVariant } from "./types";

export const statusCopy: Record<StatusVariant, string> = {
  neutral: "Neutral",
  critical: "Very High",
  high: "High",
  elevated: "Elevated",
  good: "Good",
  optimal: "Optimal"
};

export const statusTextClass: Record<StatusVariant, string> = {
  neutral: "text-text-muted",
  critical: "text-status-critical",
  high: "text-status-high",
  elevated: "text-status-elevated",
  good: "text-status-good",
  optimal: "text-status-optimal"
};

export const statusBgClass: Record<StatusVariant, string> = {
  neutral: "bg-text-muted",
  critical: "bg-status-critical",
  high: "bg-status-high",
  elevated: "bg-status-elevated",
  good: "bg-status-good",
  optimal: "bg-status-optimal"
};

export const statusBorderClass: Record<StatusVariant, string> = {
  neutral: "border-border-subtle",
  critical: "border-status-critical/25",
  high: "border-status-high/25",
  elevated: "border-status-elevated/30",
  good: "border-status-good/25",
  optimal: "border-status-optimal/25"
};

export const statusSoftBgClass: Record<StatusVariant, string> = {
  neutral: "bg-bg-app",
  critical: "bg-status-critical/10",
  high: "bg-status-high/10",
  elevated: "bg-status-elevated/15",
  good: "bg-status-good/10",
  optimal: "bg-status-optimal/10"
};

export const statusStrokeClass: Record<StatusVariant, string> = {
  neutral: "stroke-text-muted",
  critical: "stroke-status-critical",
  high: "stroke-status-high",
  elevated: "stroke-status-elevated",
  good: "stroke-status-good",
  optimal: "stroke-status-optimal"
};

export const statusFillTextClass: Record<StatusVariant, string> = {
  neutral: "text-text-muted",
  critical: "text-status-critical",
  high: "text-status-high",
  elevated: "text-status-elevated",
  good: "text-status-good",
  optimal: "text-status-optimal"
};

export function statusFromScore(score: number): StatusVariant {
  if (score >= 85) return "critical";
  if (score >= 70) return "high";
  if (score >= 55) return "elevated";
  return "optimal";
}
