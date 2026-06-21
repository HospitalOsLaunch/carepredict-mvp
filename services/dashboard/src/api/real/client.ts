import type {
  ActionRecommendRequest,
  ActionRecommendResponse,
  ActionSimulateRequest,
  ActionSimulationDelta,
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

const DEFAULT_API_BASE = "";

export class RealHospitalApiClient implements HospitalApiClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string = import.meta.env.VITE_API_BASE ?? import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  getHealth(): Promise<HealthResponse> {
    return this.getJson<HealthResponse>("/health");
  }

  getReady(): Promise<HealthResponse> {
    return this.getJson<HealthResponse>("/ready");
  }

  simulateHospitalWorld(request: SimulationRequest): Promise<SimulationResponse> {
    return this.postJson<SimulationRequest, SimulationResponse>("/simulate/hospital-world", request);
  }

  fetchChargePrediction(request: ChargePredictionRequest): Promise<ChargePredictionResponse> {
    return this.postJson<ChargePredictionRequest, ChargePredictionResponse>("/predict/charge", request);
  }

  getFeatureWindow(params: FeatureWindowParams): Promise<FeatureWindowResponse> {
    const query = new URLSearchParams({
      hospital_id: params.hospital_id,
      service_id: params.service_id,
      origin_timestamp: params.origin_timestamp,
      length: String(params.length ?? 120)
    });
    return this.getJson<FeatureWindowResponse>(`/history/feature-window?${query.toString()}`);
  }

  getForecast(request: ForecastRequest): Promise<ForecastResponse> {
    return this.postJson<ForecastRequest, ForecastResponse>("/forecast/charge", request);
  }

  getRecommendations(request: ActionRecommendRequest): Promise<ActionRecommendResponse> {
    return this.postJson<ActionRecommendRequest, ActionRecommendResponse>("/actions/recommend", request);
  }

  simulateAction(recommendationId: string, request: ActionSimulateRequest): Promise<ActionSimulationDelta> {
    return this.postJson<ActionSimulateRequest, ActionSimulationDelta>(
      `/actions/${encodeURIComponent(recommendationId)}/simulate`,
      request
    );
  }

  private async getJson<TResponse>(path: string): Promise<TResponse> {
    const response = await fetch(`${this.baseUrl}${path}`);
    return parseResponse<TResponse>(response, path);
  }

  private async postJson<TRequest, TResponse>(path: string, request: TRequest): Promise<TResponse> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request)
    });
    return parseResponse<TResponse>(response, path);
  }
}

async function parseResponse<TResponse>(response: Response, path: string): Promise<TResponse> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`API request ${path} failed with status ${response.status}: ${detail}`);
  }
  return (await response.json()) as TResponse;
}
