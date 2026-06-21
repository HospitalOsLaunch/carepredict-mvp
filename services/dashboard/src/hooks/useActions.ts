import { useQuery } from "@tanstack/react-query";

import { getApiClient } from "../api/client";
import type { ActionRecommendResponse, ActionSimulationDelta, Recommendation } from "../api/contracts";

export function useRecommendations(
  facilityId: string,
  horizon: number,
  services: string[],
  origin: string
) {
  return useQuery<ActionRecommendResponse>({
    queryKey: ["actions-recommend", facilityId, horizon, services, origin],
    queryFn: async () => {
      const api = getApiClient();
      return api.getRecommendations({
        facility_id: facilityId,
        horizon_h: horizon,
        services,
        origin
      });
    }
  });
}

export function useActionSimulation(
  recommendation: Recommendation | undefined,
  facilityId: string,
  origin: string
) {
  return useQuery<ActionSimulationDelta>({
    queryKey: ["actions-simulate", recommendation?.id, recommendation?.service_id, recommendation?.lever, origin],
    enabled: Boolean(recommendation),
    queryFn: async () => {
      if (!recommendation) {
        throw new Error("No recommendation selected");
      }
      const api = getApiClient();
      return api.simulateAction(recommendation.id, {
        facility_id: facilityId,
        service_id: recommendation.service_id,
        lever: recommendation.lever,
        origin,
        horizon_h: recommendation.horizon_h,
        projected_impact_siips: recommendation.projected_impact_siips
      });
    }
  });
}
