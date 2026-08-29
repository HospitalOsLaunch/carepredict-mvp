export type TargetRiskLevel = "low" | "moderate" | "high" | "critical";

export type OperationalMetricSemantic =
  | "capacity"
  | "flow"
  | "staffing"
  | "workload"
  | "risk"
  | "downstream";

export interface OperationalMetricDefinition {
  id: string;
  label: string;
  unit?: string;
  semantic: OperationalMetricSemantic;
  provenance: "synthetic_research";
  researchCandidate: true;
}

export interface TargetScenarioState {
  additionalEarlyDischarges: number;
  peakOccupiedBeds: number;
  peakAvailableBeds: number;
  peakOccupancyPercent: number;
  peakSiips: number;
  criticalHours: number;
  risk: TargetRiskLevel;
  staffingGapPeak: number;
  staffingGapUnit: string;
  downstreamCapacity: "contrainte" | "disponible";
}

export interface TargetForecastPoint {
  hour: number;
  timeLabel: string;
  baseline: number;
  recommended: number;
  custom: number;
  lowerBound: number;
  upperBound: number;
  threshold: number;
}

export const TARGET_PRESSURE_THRESHOLD_SIIPS = 1600;

export function classifyTargetRisk(peak: number, criticalHours: number): TargetRiskLevel {
  if (criticalHours >= 5 || peak >= 1800) return "critical";
  if (criticalHours > 0 || peak >= TARGET_PRESSURE_THRESHOLD_SIIPS) return "high";
  if (peak >= 1200) return "moderate";
  return "low";
}

export const TARGET_METRICS: OperationalMetricDefinition[] = [
  { id: "occupancy", label: "Occupation prévue", unit: "%", semantic: "capacity", provenance: "synthetic_research", researchCandidate: true },
  { id: "available-beds", label: "Lits disponibles", unit: "lits", semantic: "capacity", provenance: "synthetic_research", researchCandidate: true },
  { id: "inflow", label: "Entrées attendues avant le pic", unit: "patients", semantic: "flow", provenance: "synthetic_research", researchCandidate: true },
  { id: "outflow", label: "Sorties prévues avant le pic", unit: "patients", semantic: "flow", provenance: "synthetic_research", researchCandidate: true },
  { id: "staffing", label: "Couverture prévue", unit: "IDE", semantic: "staffing", provenance: "synthetic_research", researchCandidate: true },
  { id: "siips", label: "Charge en soins au pic", unit: "SIIPS", semantic: "workload", provenance: "synthetic_research", researchCandidate: true },
  { id: "downstream", label: "Capacité d'aval", semantic: "downstream", provenance: "synthetic_research", researchCandidate: true }
];

const BASELINE_SERIES = [1560, 1640, 1750, 1810, 1760, 1510];
const RECOMMENDED_SERIES = [1510, 1580, 1590, 1610, 1580, 1460];
const CUSTOM_THREE_SERIES = [1530, 1620, 1680, 1690, 1650, 1470];
const CUSTOM_SEVEN_SERIES = [1500, 1570, 1580, 1530, 1510, 1430];
const TIME_LABELS = ["08h", "12h", "16h", "18h", "20h", "00h"];
const TIME_HOURS = [8, 12, 16, 18, 20, 24];

function stateForDischarges(dischargeCount: number): TargetScenarioState {
  const count = Math.max(0, Math.min(8, Math.round(dischargeCount)));
  const exact: Record<number, Pick<TargetScenarioState, "peakOccupiedBeds" | "peakAvailableBeds" | "peakOccupancyPercent" | "peakSiips" | "criticalHours">> = {
    0: { peakOccupiedBeds: 70, peakAvailableBeds: 2, peakOccupancyPercent: 97.2, peakSiips: 1810, criticalHours: 6 },
    3: { peakOccupiedBeds: 67, peakAvailableBeds: 5, peakOccupancyPercent: 93.1, peakSiips: 1690, criticalHours: 4 },
    5: { peakOccupiedBeds: 65, peakAvailableBeds: 7, peakOccupancyPercent: 90.3, peakSiips: 1610, criticalHours: 1 },
    7: { peakOccupiedBeds: 63, peakAvailableBeds: 9, peakOccupancyPercent: 87.5, peakSiips: 1530, criticalHours: 0 }
  };
  const known = exact[count];
  const peakOccupiedBeds = known?.peakOccupiedBeds ?? 70 - count;
  const peakAvailableBeds = known?.peakAvailableBeds ?? 72 - peakOccupiedBeds;
  const peakOccupancyPercent = known?.peakOccupancyPercent ?? Number(((peakOccupiedBeds / 72) * 100).toFixed(1));
  const peakSiips = known?.peakSiips ?? 1810 - count * 40;
  const criticalHours = known?.criticalHours ?? Math.max(0, Math.round(6 - count * 0.9));
  return {
    additionalEarlyDischarges: count,
    peakOccupiedBeds,
    peakAvailableBeds,
    peakOccupancyPercent,
    peakSiips,
    criticalHours,
    risk: classifyTargetRisk(peakSiips, criticalHours),
    staffingGapPeak: -2,
    staffingGapUnit: "IDE",
    downstreamCapacity: "contrainte"
  };
}

export const HCL_TARGET_PRODUCT_RESEARCH_SCENARIO = {
  scenarioId: "target-scenario-urgences-2026-09-14",
  hospitalId: "demo-hospital",
  hospitalLabel: "Hôpital Démo",
  serviceId: "urgences",
  serviceLabel: "Urgences",
  scenarioDateLabel: "14 septembre",
  referenceTime: "08:00",
  origin: "2026-09-14T08:00:00+02:00",
  riskWindow: { start: "16:00", end: "20:00" },
  riskWindowStart: "2026-09-14T16:00:00+02:00",
  riskWindowEnd: "2026-09-14T20:00:00+02:00",
  expectedPeakTime: "18:00",
  horizonHours: 48,
  dataMode: "research_synthetic" as const,
  bedCapacity: 72,
  occupiedBedsAtReference: 63,
  expectedArrivalsBeforePeak: 18,
  expectedBaselineExitsBeforePeak: 11,
  staffingGapUnit: "IDE",
  recommendation: {
    id: "recommendation-prioritize-discharge-001",
    title: "Avancer 5 sorties confirmées avant 15h",
    rationale: "Créer de la capacité avant la fenêtre de tension prévue.",
    parameterId: "confirmed_discharges",
    parameterLabel: "Sorties à avancer avant 15h",
    recommendedValue: 5,
    min: 0,
    max: 8,
    unit: "patients"
  },
  states: {
    baseline: stateForDischarges(0),
    recommended: stateForDischarges(5),
    custom3: stateForDischarges(3),
    custom7: stateForDischarges(7)
  },
  metricDefinitions: TARGET_METRICS
} as const;

export function targetScenarioStateFor(dischargeCount: number): TargetScenarioState {
  return stateForDischarges(dischargeCount);
}

function seriesForDischarges(dischargeCount: number): number[] {
  const count = Math.max(0, Math.min(8, Math.round(dischargeCount)));
  if (count === 0) return BASELINE_SERIES;
  if (count === 3) return CUSTOM_THREE_SERIES;
  if (count === 5) return RECOMMENDED_SERIES;
  if (count === 7) return CUSTOM_SEVEN_SERIES;
  return BASELINE_SERIES.map((value, index) => Math.round(value - count * [12, 18, 26, 40, 34, 10][index]));
}

export function targetForecastFor(dischargeCount: number): TargetForecastPoint[] {
  const custom = seriesForDischarges(dischargeCount);
  return TIME_HOURS.map((hour, index) => ({
    hour,
    timeLabel: TIME_LABELS[index],
    baseline: BASELINE_SERIES[index],
    recommended: RECOMMENDED_SERIES[index],
    custom: custom[index],
    lowerBound: BASELINE_SERIES[index] - 90,
    upperBound: BASELINE_SERIES[index] + 100,
    threshold: TARGET_PRESSURE_THRESHOLD_SIIPS
  }));
}
