import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getApiClient } from "../api/client";
import type {
  ActionEventsResponse,
  ActionRecommendResponse,
  ActionSimulationDelta,
  ActionStatus,
  ActionTransitionResponse,
  Recommendation
} from "../api/contracts";

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

export function useActionEvents(recommendationId: string | undefined) {
  return useQuery<ActionEventsResponse>({
    queryKey: ["actions-events", recommendationId],
    enabled: Boolean(recommendationId),
    queryFn: async () => {
      if (!recommendationId) {
        throw new Error("No recommendation selected");
      }
      return getApiClient().getActionEvents(recommendationId);
    }
  });
}

export function useActionTransition() {
  const queryClient = useQueryClient();
  return useMutation<
    ActionTransitionResponse,
    Error,
    { recommendationId: string; toStatus: ActionStatus; actor: string; reason?: string | null },
    { previous: Array<[readonly unknown[], ActionRecommendResponse | undefined]> }
  >({
    mutationFn: async ({ recommendationId, toStatus, actor, reason }) =>
      getApiClient().transitionAction(recommendationId, {
        to_status: toStatus,
        actor,
        reason
      }),
    onMutate: async ({ recommendationId, toStatus }) => {
      await queryClient.cancelQueries({ queryKey: ["actions-recommend"] });
      const previous = queryClient.getQueriesData<ActionRecommendResponse>({ queryKey: ["actions-recommend"] });
      queryClient.setQueriesData<ActionRecommendResponse>({ queryKey: ["actions-recommend"] }, (current) => {
        if (!current) return current;
        return {
          ...current,
          recommendations: current.recommendations.map((recommendation) =>
            recommendation.id === recommendationId ? { ...recommendation, status: toStatus } : recommendation
          )
        };
      });
      return { previous };
    },
    onError: (_error, _variables, context) => {
      for (const [queryKey, value] of context?.previous ?? []) {
        queryClient.setQueryData(queryKey, value);
      }
    },
    onSuccess: (response, variables) => {
      queryClient.setQueriesData<ActionRecommendResponse>({ queryKey: ["actions-recommend"] }, (current) => {
        if (!current) return current;
        return {
          ...current,
          recommendations: current.recommendations.map((recommendation) =>
            recommendation.id === variables.recommendationId
              ? { ...recommendation, status: response.recommendation.status }
              : recommendation
          )
        };
      });
      void queryClient.invalidateQueries({ queryKey: ["actions-events", variables.recommendationId] });
    }
  });
}
