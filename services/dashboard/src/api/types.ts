export type {
  ActionLever,
  ActionRecommendRequest,
  ActionRecommendResponse,
  ActionSeverity,
  ActionSimulateRequest,
  ActionSimulationDelta,
  ActionSimulationMode,
  ActionSimulationPoint,
  ActionSimulationSummary,
  ActionStatus,
  ActionStep,
  ChargePredictionRequest,
  ChargePredictionResponse,
  FeatureWindowParams,
  FeatureWindowResponse,
  ForecastFeatureStep,
  ForecastRequest,
  ForecastResponse,
  ForecastStep,
  HealthResponse,
  HospitalApiClient,
  InterventionType,
  OpportunityKPIs,
  PlannedIntervention,
  Recommendation,
  RiskWindow,
  SimulationRequest,
  SimulationResponse,
  SimulationStepResult
} from "./contracts";

export interface ServiceOption {
  id: string;
  label: string;
  hospitalId: string;
  specialty: string;
  currentCharge: number;
}

export interface ChartPoint {
  timestamp: string;
  historical?: number;
  predicted?: number;
  lower_90?: number;
  upper_90?: number;
}
