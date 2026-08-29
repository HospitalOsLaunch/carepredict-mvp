import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import {
  RESEARCH_INSIGHT,
  simulateDischargeScenario,
  type ActionableInsight
} from "./insights";

export type Decision = "accepted" | "dismissed";

export interface DecisionRecord {
  insightId: string;
  recommendationId: string;
  decision: Decision;
  originalParameters: Record<string, number>;
  selectedParameters: Record<string, number>;
  timestamp: string;
  reason?: string;
}

interface ScenarioState {
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
  refuseRecommendation: (reason: string) => void;
  resetDecision: () => void;
}

const Context = createContext<ScenarioContextValue | undefined>(undefined);

function initialParameters(): Record<string, number> {
  return Object.fromEntries(
    RESEARCH_INSIGHT.recommendation.parameters.map((parameter) => [parameter.id, parameter.value])
  );
}

export function ScenarioProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ScenarioState>(() => ({
    insight: RESEARCH_INSIGHT,
    selectedParameters: initialParameters(),
    decision: null,
    auditEvents: []
  }));

  const simulation = useMemo(
    () => simulateDischargeScenario(state.selectedParameters.confirmed_discharges ?? 0),
    [state.selectedParameters]
  );

  const makeRecord = (current: ScenarioState, decision: Decision, selectedParameters: Record<string, number>, reason?: string): DecisionRecord => ({
    insightId: current.insight.id,
    recommendationId: current.insight.recommendation.id,
    decision,
    originalParameters: initialParameters(),
    selectedParameters: { ...selectedParameters },
    timestamp: new Date().toISOString(),
    reason
  });

  const value: ScenarioContextValue = {
    ...state,
    simulation,
    setParameter: (id, value) => {
      setState((current) => ({
        ...current,
        selectedParameters: { ...current.selectedParameters, [id]: value },
        decision: null
      }));
    },
    acceptRecommendation: () => {
      setState((current) => {
        const originalParameters = initialParameters();
        const record = makeRecord(current, "accepted", originalParameters);
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
        const record = makeRecord(current, "accepted", current.selectedParameters);
        return {
          ...current,
          insight: { ...current.insight, recommendation: { ...current.insight.recommendation, status: "accepted" } },
          decision: record,
          auditEvents: [...current.auditEvents, record]
        };
      });
    },
    refuseRecommendation: (reason) => {
      setState((current) => {
        const record = makeRecord(current, "dismissed", current.selectedParameters, reason);
        return {
          ...current,
          insight: {
            ...current.insight,
            recommendation: { ...current.insight.recommendation, status: "refused" }
          },
          decision: record,
          auditEvents: [...current.auditEvents, record]
        };
      });
    },
    resetDecision: () => setState((current) => ({ ...current, decision: null }))
  };

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useScenarioContext(): ScenarioContextValue {
  const value = useContext(Context);
  if (!value) throw new Error("useScenarioContext must be used inside ScenarioProvider");
  return value;
}
