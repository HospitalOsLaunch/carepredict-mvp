export type TargetRiskLevel = "low" | "moderate" | "high" | "critical";
export type WorkloadLevel = "low" | "moderate" | "high" | "very_high";
export type ResearchHorizonHours = 6 | 12 | 18 | 24 | 48 | 72;
export type ResearchUnitId = "emergency" | "pediatrics" | "internal_medicine" | "surgery" | "icu";

export interface ResearchUnitDefinition {
  id: ResearchUnitId;
  label: string;
  hasDedicatedSituation: boolean;
}

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
  elapsedHours: number;
  timeLabel: string;
  baseline: number;
  recommended: number;
  custom: number;
  lowerBound: number;
  upperBound: number;
  threshold: number;
}

export const TARGET_PRESSURE_THRESHOLD_SIIPS = 1600;
export const RESEARCH_HORIZONS: ResearchHorizonHours[] = [6, 12, 18, 24, 48, 72];
export const RESEARCH_UNITS: ResearchUnitDefinition[] = [
  { id: "emergency", label: "Urgences", hasDedicatedSituation: true },
  { id: "pediatrics", label: "Pédiatrie", hasDedicatedSituation: false },
  { id: "internal_medicine", label: "Médecine interne", hasDedicatedSituation: false },
  { id: "surgery", label: "Chirurgie", hasDedicatedSituation: false },
  { id: "icu", label: "Réanimation", hasDedicatedSituation: false }
];

export function classifyTargetRisk(peak: number, criticalHours: number): TargetRiskLevel {
  if (criticalHours >= 5 || peak >= 1800) return "critical";
  if (criticalHours > 0 || peak >= TARGET_PRESSURE_THRESHOLD_SIIPS) return "high";
  if (peak >= 1200) return "moderate";
  return "low";
}

export function classifySiipsWorkload(value: number): WorkloadLevel {
  if (value >= 1750) return "very_high";
  if (value >= 1600) return "high";
  if (value >= 1400) return "moderate";
  return "low";
}

export function formatWorkloadLevel(level: WorkloadLevel): string {
  return { low: "Faible", moderate: "Modérée", high: "Élevée", very_high: "Très élevée" }[level];
}

export function getResearchUnit(unitId: ResearchUnitId): ResearchUnitDefinition {
  return RESEARCH_UNITS.find((unit) => unit.id === unitId) ?? RESEARCH_UNITS[0];
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

const FORECAST_TIMELINE = [
  { elapsedHours: 0, hour: 8, timeLabel: "08h" },
  { elapsedHours: 4, hour: 12, timeLabel: "12h" },
  { elapsedHours: 8, hour: 16, timeLabel: "16h" },
  { elapsedHours: 10, hour: 18, timeLabel: "18h" },
  { elapsedHours: 12, hour: 20, timeLabel: "20h" },
  { elapsedHours: 16, hour: 24, timeLabel: "15 sept. · 00h" },
  { elapsedHours: 24, hour: 32, timeLabel: "15 sept. · 08h" },
  { elapsedHours: 30, hour: 38, timeLabel: "15 sept. · 14h" },
  { elapsedHours: 36, hour: 44, timeLabel: "15 sept. · 20h" },
  { elapsedHours: 42, hour: 50, timeLabel: "16 sept. · 02h" },
  { elapsedHours: 48, hour: 56, timeLabel: "16 sept. · 08h" },
  { elapsedHours: 54, hour: 62, timeLabel: "16 sept. · 14h" },
  { elapsedHours: 60, hour: 68, timeLabel: "16 sept. · 20h" },
  { elapsedHours: 66, hour: 74, timeLabel: "17 sept. · 02h" },
  { elapsedHours: 72, hour: 80, timeLabel: "17 sept. · 08h" }
] as const;
const BASELINE_SERIES = [1560, 1640, 1750, 1810, 1760, 1510, 1490, 1580, 1660, 1515, 1460, 1540, 1625, 1490, 1440];
const RECOMMENDED_SERIES = [1510, 1580, 1590, 1610, 1580, 1460, 1450, 1540, 1610, 1480, 1430, 1510, 1580, 1460, 1420];
const CUSTOM_THREE_SERIES = [1530, 1620, 1680, 1690, 1650, 1470, 1470, 1560, 1635, 1495, 1445, 1525, 1600, 1475, 1430];
const CUSTOM_SEVEN_SERIES = [1500, 1570, 1580, 1530, 1510, 1430, 1435, 1525, 1585, 1465, 1420, 1495, 1560, 1445, 1405];
const DISCHARGE_REDUCTION_FACTORS = [12, 18, 26, 40, 34, 10, 8, 8, 10, 7, 6, 6, 9, 6, 5];

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
  return BASELINE_SERIES.map((value, index) => Math.round(value - count * DISCHARGE_REDUCTION_FACTORS[index]));
}

export function targetForecastFor(dischargeCount: number, horizonHours: ResearchHorizonHours = 48): TargetForecastPoint[] {
  const custom = seriesForDischarges(dischargeCount);
  return FORECAST_TIMELINE.filter((point) => point.elapsedHours <= horizonHours).map((point, index) => ({
    hour: point.hour,
    elapsedHours: point.elapsedHours,
    timeLabel: point.timeLabel,
    baseline: BASELINE_SERIES[index],
    recommended: RECOMMENDED_SERIES[index],
    custom: custom[index],
    lowerBound: BASELINE_SERIES[index] - 90,
    upperBound: BASELINE_SERIES[index] + 100,
    threshold: TARGET_PRESSURE_THRESHOLD_SIIPS
  }));
}
