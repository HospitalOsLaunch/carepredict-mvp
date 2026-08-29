import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import {
  RESEARCH_INSIGHT,
  simulateDischargeScenario,
  type ActionableInsight
} from "./insights";

export type Decision = "accepted" | "dismissed";
export type DecisionSource = "recommendation" | "modified_scenario";

export interface DecisionRecord {
  insightId: string;
  recommendationId: string;
  researchSessionId: string;
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
  insight: ActionableInsight;
  selectedParameters: Record<string, number>;
  decision: DecisionRecord | null;
  auditEvents: DecisionRecord[];
}

interface ScenarioContextValue extends ScenarioState {
  simulation: ReturnType<typeof simulateDischargeScenario>;
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
    insight: RESEARCH_INSIGHT,
    selectedParameters: initialParameters(),
    decision: null,
    auditEvents: []
  };
}

export function ScenarioProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ScenarioState>(createInitialState);

  const simulation = useMemo(
    () => simulateDischargeScenario(state.selectedParameters.confirmed_discharges ?? 0),
    [state.selectedParameters]
  );

  const makeRecord = (current: ScenarioState, decision: Decision, decisionSource: DecisionSource, selectedParameters: Record<string, number>, reason?: string): DecisionRecord => {
    const timestamp = new Date().toISOString();
    return {
      insightId: current.insight.id,
      recommendationId: current.insight.recommendation.id,
      researchSessionId: current.researchSessionId,
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
    simulation,
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
