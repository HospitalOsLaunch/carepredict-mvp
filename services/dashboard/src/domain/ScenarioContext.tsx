import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import {
  RESEARCH_INSIGHT,
  simulateDischargeScenario,
  type ActionableInsight
} from "./insights";
import {
  getResearchUnit,
  type ResearchHorizonHours,
  type ResearchUnitDefinition,
  type ResearchUnitId
} from "../research/hclTargetScenario";

export type Decision = "accepted" | "dismissed";
export type DecisionSource = "recommendation" | "modified_scenario";

export interface DecisionRecord {
  insightId: string;
  recommendationId: string;
  researchSessionId: string;
  unitId: ResearchUnitId;
  horizonHours: ResearchHorizonHours;
  decision: Decision;
  decisionSource: DecisionSource;
  originalParameters: Record<string, number>;
  selectedParameters: Record<string, number>;
  createdAt: string;
  timestamp: string;
  reason?: string;
}

interface ScenarioState {
  researchSessionId: string;
  selectedUnitId: ResearchUnitId;
  horizonHours: ResearchHorizonHours;
  insight: ActionableInsight;
  selectedParameters: Record<string, number>;
  decision: DecisionRecord | null;
  auditEvents: DecisionRecord[];
}

interface ScenarioContextValue extends ScenarioState {
  selectedUnit: ResearchUnitDefinition;
  simulation: ReturnType<typeof simulateDischargeScenario>;
  setSelectedUnit: (unitId: ResearchUnitId) => void;
  setHorizonHours: (horizonHours: ResearchHorizonHours) => void;
  setParameter: (id: string, value: number) => void;
  acceptRecommendation: () => void;
  acceptModifiedScenario: () => void;
  refuseRecommendation: (reason: string, source?: DecisionSource) => void;
  resetResearchScenario: () => void;
}

const Context = createContext<ScenarioContextValue | undefined>(undefined);

function initialParameters(): Record<string, number> {
  return Object.fromEntries(
    RESEARCH_INSIGHT.recommendation.parameters.map((parameter) => [parameter.id, parameter.value])
  );
}

let sessionSequence = 0;

function nextResearchSessionId(): string {
  sessionSequence += 1;
  return `research-session-${String(sessionSequence).padStart(3, "0")}`;
}

function createInitialState(): ScenarioState {
  return {
    researchSessionId: nextResearchSessionId(),
    selectedUnitId: "emergency",
    horizonHours: 48,
    insight: RESEARCH_INSIGHT,
    selectedParameters: initialParameters(),
    decision: null,
    auditEvents: []
  };
}

export function ScenarioProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ScenarioState>(createInitialState);

  const selectedUnit = getResearchUnit(state.selectedUnitId);
  const contextualInsight = useMemo<ActionableInsight>(() => ({
    ...state.insight,
    context: {
      ...state.insight.context,
      serviceId: selectedUnit.id,
      serviceLabel: selectedUnit.label,
      horizonHours: state.horizonHours
    }
  }), [selectedUnit, state.horizonHours, state.insight]);

  const simulation = useMemo(
    () => simulateDischargeScenario(state.selectedParameters.confirmed_discharges ?? 0, state.horizonHours),
    [state.horizonHours, state.selectedParameters]
  );

  const makeRecord = (current: ScenarioState, decision: Decision, decisionSource: DecisionSource, selectedParameters: Record<string, number>, reason?: string): DecisionRecord => {
    const timestamp = new Date().toISOString();
    return {
      insightId: current.insight.id,
      recommendationId: current.insight.recommendation.id,
      researchSessionId: current.researchSessionId,
      unitId: current.selectedUnitId,
      horizonHours: current.horizonHours,
      decision,
      decisionSource,
      originalParameters: initialParameters(),
      selectedParameters: { ...selectedParameters },
      createdAt: timestamp,
      timestamp,
      reason
    };
  };

  const value: ScenarioContextValue = {
    ...state,
    insight: contextualInsight,
    selectedUnit,
    simulation,
    setSelectedUnit: (unitId) => setState((current) => ({ ...current, selectedUnitId: unitId })),
    setHorizonHours: (horizonHours) => setState((current) => ({ ...current, horizonHours })),
    setParameter: (id, value) => {
      setState((current) => current.decision
        ? current
        : { ...current, selectedParameters: { ...current.selectedParameters, [id]: value } });
    },
    acceptRecommendation: () => {
      setState((current) => {
        if (current.decision) return current;
        const originalParameters = initialParameters();
        const record = makeRecord(current, "accepted", "recommendation", originalParameters);
        return {
          ...current,
          insight: { ...current.insight, recommendation: { ...current.insight.recommendation, status: "accepted" } },
          selectedParameters: initialParameters(),
          decision: record,
          auditEvents: [...current.auditEvents, record]
        };
      });
    },
    acceptModifiedScenario: () => {
      setState((current) => {
        if (current.decision) return current;
        const record = makeRecord(current, "accepted", "modified_scenario", current.selectedParameters);
        return {
          ...current,
          insight: { ...current.insight, recommendation: { ...current.insight.recommendation, status: "accepted" } },
          decision: record,
          auditEvents: [...current.auditEvents, record]
        };
      });
    },
    refuseRecommendation: (reason, source = "recommendation") => {
      setState((current) => {
        if (current.decision) return current;
        const selectedParameters = source === "modified_scenario"
          ? current.selectedParameters
          : initialParameters();
        const record = makeRecord(current, "dismissed", source, selectedParameters, reason);
        return {
          ...current,
          insight: {
            ...current.insight,
            recommendation: { ...current.insight.recommendation, status: "refused" }
          },
          selectedParameters,
          decision: record,
          auditEvents: [...current.auditEvents, record]
        };
      });
    },
    resetResearchScenario: () => setState(createInitialState)
  };

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useScenarioContext(): ScenarioContextValue {
  const value = useContext(Context);
  if (!value) throw new Error("useScenarioContext must be used inside ScenarioProvider");
  return value;
}
