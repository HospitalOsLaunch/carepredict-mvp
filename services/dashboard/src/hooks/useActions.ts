import { useQuery } from "@tanstack/react-query";

import { getApiClient } from "../api/client";
import type { ActionRecommendResponse } from "../api/contracts";

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
