export type {
  ActionStep,
  ChargePredictionRequest,
  ChargePredictionResponse,
  HealthResponse,
  HospitalApiClient,
  InterventionType,
  PlannedIntervention,
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
