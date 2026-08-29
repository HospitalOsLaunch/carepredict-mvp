import {
  classifyTargetRisk,
  HCL_TARGET_PRODUCT_RESEARCH_SCENARIO,
  targetForecastFor,
  targetScenarioStateFor,
  TARGET_PRESSURE_THRESHOLD_SIIPS,
  type OperationalMetricDefinition,
  type ResearchHorizonHours,
  type TargetRiskLevel,
  type TargetScenarioState
} from "../research/hclTargetScenario";

export type InsightRiskLevel = TargetRiskLevel;
export type InsightConfidence = "low" | "medium" | "high";

export interface ScenarioContext {
  scenarioId: string;
  hospitalId: string;
  hospitalLabel: string;
  serviceId: string;
  serviceLabel: string;
  origin: string;
  horizonHours: number;
  dataMode: "research_synthetic" | "real";
}

export interface InsightDriver {
  id: string;
  label: string;
  explanation: string;
}

export interface RecommendationParameter {
  id: string;
  label: string;
  value: number;
  unit: string;
  min?: number;
  max?: number;
}

export interface InsightRecommendation {
  id: string;
  title: string;
  rationale: string;
  expectedPeakDeltaSiips: number | null;
  expectedCriticalHoursDelta: number | null;
  feasibility: "low" | "medium" | "high";
  confidence: InsightConfidence;
  parameters: RecommendationParameter[];
  status: "proposed" | "accepted" | "refused";
}

export interface ActionableInsight {
  id: string;
  context: ScenarioContext;
  title: string;
  riskLevel: InsightRiskLevel;
  riskWindowStart: string;
  riskWindowEnd: string;
  peakPressureSiips: number;
  criticalHours: number;
  confidence: InsightConfidence;
  drivers: InsightDriver[];
  recommendation: InsightRecommendation;
  metricDefinitions: OperationalMetricDefinition[];
}

export interface ScenarioPoint {
  hour: number;
  elapsedHours: number;
  timeLabel: string;
  baseline: number;
  recommended: number;
  custom: number;
  threshold: number;
  lowerBound: number;
  upperBound: number;
}

export interface ScenarioSummary extends TargetScenarioState {
  peak: number;
}

export const PRESSURE_THRESHOLD_SIIPS = TARGET_PRESSURE_THRESHOLD_SIIPS;
export const classifyRiskLevel = classifyTargetRisk;

const scenario = HCL_TARGET_PRODUCT_RESEARCH_SCENARIO;
const baseline = scenario.states.baseline;

export const RESEARCH_INSIGHT: ActionableInsight = {
  id: "situation-urgences-2026-09-14",
  context: {
    scenarioId: scenario.scenarioId,
    hospitalId: scenario.hospitalId,
    hospitalLabel: scenario.hospitalLabel,
    serviceId: scenario.serviceId,
    serviceLabel: scenario.serviceLabel,
    origin: scenario.origin,
    horizonHours: scenario.horizonHours,
    dataMode: scenario.dataMode
  },
  title: "Tension critique prévue de 16h à 20h",
  riskLevel: baseline.risk,
  riskWindowStart: scenario.riskWindowStart,
  riskWindowEnd: scenario.riskWindowEnd,
  peakPressureSiips: baseline.peakSiips,
  criticalHours: baseline.criticalHours,
  confidence: "high",
  drivers: [
    {
      id: "inflow",
      label: "Flux entrant supérieur aux sorties avant le pic",
      explanation: "18 entrées attendues contre 11 sorties prévues avant la fenêtre de tension."
    },
    {
      id: "discharge-window",
      label: "5 sorties confirmées peuvent être avancées",
      explanation: "Ces sorties sont déjà confirmées dans le scénario ; l'action ne décide pas de l'éligibilité médicale."
    },
    {
      id: "staffing",
      label: "Couverture IDE inférieure au besoin estimé",
      explanation: "Un déficit de 2 IDE reste prévu sur la fenêtre 16h–20h, quelle que soit l'action capacitaire."
    },
    {
      id: "downstream",
      label: "Capacité d'aval contrainte",
      explanation: "La capacité d'aval limite l'absorption du flux en fin de journée."
    }
  ],
  recommendation: {
    id: scenario.recommendation.id,
    title: scenario.recommendation.title,
    rationale: scenario.recommendation.rationale,
    expectedPeakDeltaSiips: -200,
    expectedCriticalHoursDelta: -5,
    feasibility: "high",
    confidence: "high",
    parameters: [{
      id: scenario.recommendation.parameterId,
      label: scenario.recommendation.parameterLabel,
      value: scenario.recommendation.recommendedValue,
      unit: scenario.recommendation.unit,
      min: scenario.recommendation.min,
      max: scenario.recommendation.max
    }],
    status: "proposed"
  },
  metricDefinitions: scenario.metricDefinitions
};

export function simulateDischargeScenario(confirmedDischarges: number, horizonHours: ResearchHorizonHours = 48): {
  points: ScenarioPoint[];
  summary: ScenarioSummary;
} {
  const state = targetScenarioStateFor(confirmedDischarges);
  const points = targetForecastFor(confirmedDischarges, horizonHours);
  return {
    points,
    summary: {
      ...state,
      peak: state.peakSiips
    }
  };
}

export function formatRiskLevel(level: InsightRiskLevel): string {
  return { low: "Faible", moderate: "Modérée", high: "Élevée", critical: "Critique" }[level];
}

export function formatConfidence(confidence: InsightConfidence): string {
  return { low: "Faible", medium: "Moyenne", high: "Élevée" }[confidence];
}

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export function formatRiskWindow(start: string, end: string): string {
  const startDate = new Date(start);
  const endDate = new Date(end);
  const date = new Intl.DateTimeFormat("fr-FR", {
    day: "numeric",
    month: "long",
    timeZone: "Europe/Paris"
  }).format(startDate);
  const formatHour = (value: Date) => {
    const hourPart = new Intl.DateTimeFormat("fr-FR", {
      hour: "numeric",
      hour12: false,
      timeZone: "Europe/Paris"
    }).formatToParts(value).find((part) => part.type === "hour");
    return `${hourPart?.value ?? value.getHours()}h`;
  };
  return `${date} · ${formatHour(startDate)}–${formatHour(endDate)}`;
}
