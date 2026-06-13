import type {
  ChargePredictionRequest,
  ChargePredictionResponse,
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
