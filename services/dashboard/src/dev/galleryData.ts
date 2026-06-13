import { Activity, Bed, Clock, Unlock, Users, Euro } from "lucide-react";

import type { DataTableColumn, DataTableRow, HeatmapCell, SparklinePoint, StatusVariant } from "../components/design-system";

export const sparkline: SparklinePoint[] = [
  { label: "08:00", value: 52 },
  { label: "10:00", value: 58 },
  { label: "12:00", value: 68 },
  { label: "14:00", value: 74 },
  { label: "16:00", value: 71 },
  { label: "18:00", value: 83 },
  { label: "20:00", value: 79 }
];

export const calmSparkline: SparklinePoint[] = [
  { label: "08:00", value: 42 },
  { label: "10:00", value: 44 },
  { label: "12:00", value: 43 },
  { label: "14:00", value: 46 },
  { label: "16:00", value: 45 },
  { label: "18:00", value: 47 },
  { label: "20:00", value: 46 }
];

export const statVariants = [
  { variant: "neutral" as const, label: "Care load", metric: "72", unit: "score", caption: "vs. 7d average, peak at 2 PM", icon: Activity },
  { variant: "critical" as const, label: "Beds at risk", metric: "43", unit: "beds", caption: "critical pressure in 4 units", icon: Bed },
  { variant: "high" as const, label: "Staffing gap", metric: "18", unit: "FTE", caption: "night shift variance increasing", icon: Users },
  { variant: "elevated" as const, label: "Delayed discharges", metric: "31", unit: "pts", caption: "expected to peak by 16:00", icon: Clock },
  { variant: "good" as const, label: "Capacity unlock", metric: "26", unit: "beds", caption: "if playbook is executed by noon", icon: Unlock },
  { variant: "good" as const, label: "Overtime exposure", metric: "€42k", unit: "risk", caption: "avoidable with early redeployment", icon: Euro }
];

export const tableColumns: DataTableColumn[] = [
  { key: "unit", header: "Unit" },
  { key: "pressure", header: "Pressure" },
  { key: "saturation", header: "Beds" },
  { key: "trend", header: "Trend" },
  { key: "delta", header: "Delta", align: "right" },
  { key: "action", header: "Action", align: "right" }
];

export const tableRows: DataTableRow[] = [
  {
    id: "ed",
    cells: {
      unit: { type: "text", value: "Emergency Department", muted: "42 active patients" },
      pressure: { type: "status", status: "critical", score: 91 },
      saturation: { type: "miniBar", value: 94, label: "Saturation" },
      trend: { type: "sparkline", data: sparkline, variant: "critical" },
      delta: { type: "delta", value: 18, unit: "pts", inverted: true },
      action: { type: "action", label: "Simulate" }
    }
  },
  {
    id: "cardiology",
    cells: {
      unit: { type: "text", value: "Cardiology", muted: "28 active patients" },
      pressure: { type: "status", status: "high", score: 76 },
      saturation: { type: "miniBar", value: 81, label: "Saturation" },
      trend: { type: "sparkline", data: sparkline.slice().reverse(), variant: "high" },
      delta: { type: "delta", value: -7, unit: "pts", inverted: true },
      action: { type: "action", label: "View" }
    }
  },
  {
    id: "surgery",
    cells: {
      unit: { type: "text", value: "Surgery", muted: "33 active patients" },
      pressure: { type: "status", status: "elevated", score: 63 },
      saturation: { type: "miniBar", value: 68, label: "Saturation" },
      trend: { type: "sparkline", data: calmSparkline, variant: "elevated" },
      delta: { type: "delta", value: 4, unit: "pts", inverted: true },
      action: { type: "action", label: "Simulate" }
    }
  }
];

export const heatmapUnits = ["ED", "Cardiology", "Surgery", "ICU", "Pediatrics"];
export const heatmapHours = ["08", "10", "12", "14", "16", "18", "20", "22"];

export const heatmapCells: HeatmapCell[] = heatmapUnits.flatMap((unit, unitIndex) =>
  heatmapHours.map((hour, hourIndex) => {
    const value = 42 + unitIndex * 8 + hourIndex * 5;
    const status: StatusVariant = value > 86 ? "critical" : value > 72 ? "high" : value > 58 ? "elevated" : "optimal";
    return { unit, hour, value, status };
  })
);
