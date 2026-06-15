import type {
  ActionRecommendRequest,
  ActionRecommendResponse,
  ChargePredictionRequest,
  ChargePredictionResponse,
  FeatureWindowParams,
  FeatureWindowResponse,
  ForecastRequest,
  ForecastResponse,
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

  async getFeatureWindow(params: FeatureWindowParams): Promise<FeatureWindowResponse> {
    // MOCK: needs GET /history/feature-window from canonical.care_load and staffing when VITE_USE_MOCK is true.
    return {
      service_id: params.service_id,
      hospital_id: params.hospital_id,
      origin_timestamp: params.origin_timestamp,
      length: params.length ?? 120,
      channels: ["admissions_h", "discharges_h", "nurse_count", "aide_count", "overtime_hours", "patient_count", "occupancy_rate"],
      history: Array.from({ length: params.length ?? 120 }, (_, index) => {
        const hour = index % 24;
        const load = 41 + Math.sin((hour / 24) * Math.PI * 2) * 5;
        return [hour >= 8 && hour <= 18 ? 1 : 0, hour >= 11 && hour <= 17 ? 1 : 0, 5, 4, 0.8, load, load / 42];
      })
    };
  }

  async getForecast(request: ForecastRequest): Promise<ForecastResponse> {
    // MOCK: needs POST /forecast/charge when VITE_USE_MOCK is true.
    const baseline = 920 + (request.service_id.length % 5) * 12;
    const results = Array.from({ length: request.horizon }, (_, index) => {
      const predicted = baseline + Math.sin(index / 5) * 85 + index * 3;
      return {
        step_index: index + 1,
        predicted_siips: predicted,
        lower_90: predicted - 120,
        upper_90: predicted + 145
      };
    });
    return {
      status: "ok",
      hospital_id: request.hospital_id,
      service_id: request.service_id,
      model_version: "mock-v2-forecast",
      granularity: "daily_patch_24",
      results
    };
  }

  async getRecommendations(request: ActionRecommendRequest): Promise<ActionRecommendResponse> {
    // MOCK: needs POST /actions/recommend when VITE_USE_MOCK is true; real mode uses the backend.
    return {
      opportunity: {
        total_projected_impact_siips: 42.7,
        critical_actions_count: 3,
        services_at_risk: 2,
        risk_window: {
          start: request.origin,
          end: new Date(new Date(request.origin).getTime() + 14 * 60 * 60 * 1000).toISOString()
        }
      },
      recommendations: [
        {
          id: "rec_mock_staff",
          service_id: "rea-001",
          lever: "move_staff",
          title: "Réallouer 2 IDE vers Réanimation",
          severity: "critical",
          score: 0.87,
          projected_impact_siips: -18.3,
          feasibility: 0.8,
          rationale: "Mock recommendation pending real mode.",
          horizon_h: request.horizon_h,
          status: "proposed"
        },
        {
          id: "rec_mock_discharge",
          service_id: "urg-001",
          lever: "prioritize_discharge",
          title: "Prioriser les sorties confirmées en Urgences",
          severity: "high",
          score: 0.71,
          projected_impact_siips: -12.4,
          feasibility: 0.86,
          rationale: "Mock recommendation pending real mode.",
          horizon_h: request.horizon_h,
          status: "proposed"
        }
      ]
    };
  }
}
