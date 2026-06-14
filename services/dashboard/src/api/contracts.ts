export type HealthResponse = {
  status: string;
};

export type InterventionType =
  | "discharge"
  | "surgery"
  | "transfer_in"
  | "transfer_out"
  | "admission"
  | "procedure"
  | "staff_redeployment";

export interface PlannedIntervention {
  type: InterventionType;
  scheduled_at: string;
  count: number;
}

export interface ChargePredictionRequest {
  service_id: string;
  hospital_id: string;
  timestamp: string;
  planned_interventions: PlannedIntervention[];
}

export interface ChargePredictionResponse {
  value: number;
  lower_90: number;
  upper_90: number;
  coverage: number;
  mape: number;
  crps: number;
  model_version: string;
  attention_weights: {
    top_features: string[];
  };
}

export interface ActionStep {
  scheduled_admissions: number;
  scheduled_discharges: number;
  staff_redeployments: number;
  scheduled_surgeries: number;
  expected_transfers: number;
}

export interface SimulationRequest {
  hospital_id: string;
  service_id: string;
  history_siips: number[];
  actions: ActionStep[];
}

export interface SimulationStepResult {
  step_index: number;
  predicted_siips: number;
  lower_bound: number;
  upper_bound: number;
  reward: number;
  is_critical: boolean;
}

export interface SimulationResponse {
  status: string;
  hospital_id: string;
  service_id: string;
  model_version: string;
  results: SimulationStepResult[];
}

export interface FeatureWindowParams {
  hospital_id: string;
  service_id: string;
  origin_timestamp: string;
  length?: number;
}

export interface FeatureWindowResponse {
  service_id: string;
  hospital_id: string;
  origin_timestamp: string;
  length: number;
  channels: string[];
  history: number[][];
}

export interface ForecastFeatureStep {
  admissions_h: number;
  discharges_h: number;
  nurse_count: number;
  aide_count: number;
  overtime_hours: number;
  patient_count: number;
  occupancy_rate: number;
}

export interface ForecastRequest {
  hospital_id: string;
  service_id: string;
  origin_timestamp: string;
  history: ForecastFeatureStep[];
  horizon: number;
}

export interface ForecastStep {
  step_index: number;
  predicted_siips: number;
  lower_90: number;
  upper_90: number;
}

export interface ForecastResponse {
  status: string;
  hospital_id: string;
  service_id: string;
  model_version: string;
  granularity: string;
  results: ForecastStep[];
}

export interface HospitalApiClient {
  getHealth(): Promise<HealthResponse>;
  getReady(): Promise<HealthResponse>;
  simulateHospitalWorld(request: SimulationRequest): Promise<SimulationResponse>;
  fetchChargePrediction(request: ChargePredictionRequest): Promise<ChargePredictionResponse>;
  getFeatureWindow(params: FeatureWindowParams): Promise<FeatureWindowResponse>;
  getForecast(request: ForecastRequest): Promise<ForecastResponse>;
}
