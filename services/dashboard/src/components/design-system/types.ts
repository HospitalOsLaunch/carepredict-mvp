export type StatusVariant = "neutral" | "critical" | "high" | "elevated" | "good" | "optimal";

export interface SparklinePoint {
  label: string;
  value: number;
}
