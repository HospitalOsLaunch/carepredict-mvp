import type {
  ChargePredictionRequest,
  ChargePredictionResponse,
  HospitalApiClient
} from "./contracts";
import { MockHospitalApiClient } from "./mock/client";
import { RealHospitalApiClient } from "./real/client";

let apiClient: HospitalApiClient | undefined;

export function createApiClient(): HospitalApiClient {
  if (import.meta.env.VITE_USE_MOCK === "true") {
    return new MockHospitalApiClient();
  }
  return new RealHospitalApiClient();
}

export function getApiClient(): HospitalApiClient {
  apiClient ??= createApiClient();
  return apiClient;
}

export async function fetchChargePrediction(
  request: ChargePredictionRequest
): Promise<ChargePredictionResponse> {
  return getApiClient().fetchChargePrediction(request);
}
