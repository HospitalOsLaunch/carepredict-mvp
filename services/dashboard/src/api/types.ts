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
