import { useQuery } from "@tanstack/react-query";

import { fetchChargePrediction } from "../api/client";
import type { ChargePredictionRequest, ChargePredictionResponse } from "../api/types";

export function usePrediction(request: ChargePredictionRequest) {
  return useQuery<ChargePredictionResponse>({
    queryKey: ["prediction", request],
    queryFn: () => fetchChargePrediction(request),
    refetchInterval: 5 * 60 * 1000
  });
}
