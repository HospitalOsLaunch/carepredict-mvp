import type { ChargePredictionRequest, ChargePredictionResponse } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export async function fetchChargePrediction(
  request: ChargePredictionRequest
): Promise<ChargePredictionResponse> {
  const response = await fetch(`${API_BASE_URL}/predict/charge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request)
  });

  if (!response.ok) {
    throw new Error(`Prediction request failed with status ${response.status}`);
  }

  return (await response.json()) as ChargePredictionResponse;
}
