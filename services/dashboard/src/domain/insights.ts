export type InsightRiskLevel = "low" | "moderate" | "high" | "critical";
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
}

export interface ScenarioPoint {
  hour: number;
  baseline: number;
  recommended: number;
  custom: number;
  threshold: number;
  lowerBound: number;
  upperBound: number;
}

export interface ScenarioSummary {
  peak: number;
  criticalHours: number;
}

export const PRESSURE_THRESHOLD_SIIPS = 1600;

export function classifyRiskLevel(peak: number, criticalHours: number): InsightRiskLevel {
  if (peak >= 1800 || criticalHours >= 5) return "critical";
  if (peak >= PRESSURE_THRESHOLD_SIIPS || criticalHours > 0) return "high";
  if (peak >= 1200) return "moderate";
  return "low";
}

export const RESEARCH_INSIGHT: ActionableInsight = {
  id: "insight-urgences-2026-09-14",
  context: {
    scenarioId: "scenario-demo-urgences-001",
    hospitalId: "demo-hospital",
    hospitalLabel: "Hôpital Démo",
    serviceId: "urgences",
    serviceLabel: "Urgences",
    origin: "2026-09-14T08:00:00+02:00",
    horizonHours: 48,
    dataMode: "research_synthetic"
  },
  title: "Tension prévue aux Urgences",
  riskLevel: "critical",
  riskWindowStart: "2026-09-14T16:00:00+02:00",
  riskWindowEnd: "2026-09-14T20:00:00+02:00",
  peakPressureSiips: 1810,
  criticalHours: 6,
  confidence: "high",
  drivers: [
    {
      id: "inflow",
      label: "Arrivées soutenues",
      explanation: "Le flux d'arrivées reste supérieur au rythme de sortie attendu."
    },
    {
      id: "discharge-window",
      label: "Fenêtre de sorties confirmées",
      explanation: "Cinq sorties confirmées peuvent réduire la tension avant le pic."
    },
    {
      id: "capacity",
      label: "Capacité d'aval contrainte",
      explanation: "La capacité disponible limite l'absorption du flux en fin de journée."
    }
  ],
  recommendation: {
    id: "recommendation-prioritize-discharge-001",
    title: "Prioriser 5 sorties confirmées avant 15h",
    rationale: "Cette action libère de la capacité avant la fenêtre de tension prévue.",
    expectedPeakDeltaSiips: -200,
    expectedCriticalHoursDelta: -5,
    feasibility: "high",
    confidence: "high",
    parameters: [
      {
        id: "confirmed_discharges",
        label: "Sorties confirmées avant 15h",
        value: 5,
        unit: "patients",
        min: 0,
        max: 8
      }
    ],
    status: "proposed"
  }
};

const BASELINE_PROFILE = [1550, 1620, 1680, 1750, 1810, 1770, 1690, 1590, 1510, 1450];

export function simulateDischargeScenario(confirmedDischarges: number): {
  points: ScenarioPoint[];
  summary: ScenarioSummary;
} {
  const clamped = Math.max(0, Math.min(8, Math.round(confirmedDischarges)));
  const recommended = RESEARCH_INSIGHT.recommendation.parameters[0].value;
  const points = BASELINE_PROFILE.map((baseline, index) => {
    const timingFactor = index < 5 ? (index + 1) / 5 : 1;
    const customReduction = clamped * 40 * timingFactor;
    const recommendedReduction = recommended * 40 * timingFactor;
    return {
      hour: index * 4,
      baseline,
      recommended: Math.round(baseline - recommendedReduction),
      custom: Math.round(baseline - customReduction),
      threshold: PRESSURE_THRESHOLD_SIIPS,
      lowerBound: baseline - 100,
      upperBound: baseline + 110
    };
  });
  const series = points.map((point) => point.custom);
  return {
    points,
    summary: {
      peak: Math.max(...series),
      criticalHours: series.filter((value) => value > PRESSURE_THRESHOLD_SIIPS).length
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
  const date = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", timeZone: "Europe/Paris" }).format(startDate);
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
