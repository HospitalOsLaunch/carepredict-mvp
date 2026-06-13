import type {
  ChargePredictionRequest,
  ChargePredictionResponse,
  HealthResponse,
  HospitalApiClient,
  SimulationRequest,
  SimulationResponse
} from "../contracts";

export class MockHospitalApiClient implements HospitalApiClient {
  async getHealth(): Promise<HealthResponse> {
    return { status: "ok" };
  }

  async getReady(): Promise<HealthResponse> {
    return { status: "ready" };
  }

  async simulateHospitalWorld(request: SimulationRequest): Promise<SimulationResponse> {
    // MOCK: replace with POST /simulate/hospital-world when VITE_USE_MOCK is disabled.
    const baseline = request.history_siips[request.history_siips.length - 1] ?? 740;
    const results = request.actions.map((action, index) => {
      const operationalPressure =
        action.scheduled_admissions * 3 - action.scheduled_discharges * 2 + action.scheduled_surgeries * 4;
      const predicted = baseline + Math.sin(index / 4) * 32 + operationalPressure;
      return {
        step_index: index,
        predicted_siips: predicted,
        lower_bound: predicted - 82,
        upper_bound: predicted + 96,
        reward: -Math.max(predicted - 850, 0) / 100,
        is_critical: predicted >= 850
      };
    });

    return {
      status: "ok",
      hospital_id: request.hospital_id,
      service_id: request.service_id,
      model_version: "mock-world-model",
      results
    };
  }

  async fetchChargePrediction(_request: ChargePredictionRequest): Promise<ChargePredictionResponse> {
    // MOCK: legacy /predict/charge support only; v2 screens must use simulateHospitalWorld.
    return {
      value: 72,
      lower_90: 64,
      upper_90: 83,
      coverage: 0.9,
      mape: 0.051,
      crps: 0.342,
      model_version: "mock-legacy-tft",
      attention_weights: { top_features: ["siips_score", "patient_count", "hour"] }
    };
  }
}
