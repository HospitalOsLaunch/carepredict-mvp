import { useQuery } from "@tanstack/react-query";

import { getApiClient } from "../api/client";
import type {
  FeatureWindowResponse,
  ForecastFeatureStep,
  ForecastResponse
} from "../api/contracts";

export const FORECAST_HISTORY_LENGTH = 120;

const FEATURE_CHANNELS: (keyof ForecastFeatureStep)[] = [
  "admissions_h",
  "discharges_h",
  "nurse_count",
  "aide_count",
  "overtime_hours",
  "patient_count",
  "occupancy_rate"
];

export interface ForecastBundle {
  featureWindow: FeatureWindowResponse;
  forecast: ForecastResponse;
}

export function useForecast(serviceId: string, originTimestamp: string, horizon: number, hospitalId = "hosp-001") {
  return useQuery<ForecastBundle>({
    queryKey: ["v2-forecast", hospitalId, serviceId, originTimestamp, horizon],
    queryFn: async () => {
      const api = getApiClient();
      const featureWindow = await api.getFeatureWindow({
        hospital_id: hospitalId,
        service_id: serviceId,
        origin_timestamp: originTimestamp,
        length: FORECAST_HISTORY_LENGTH
      });
      const forecast = await api.getForecast({
        hospital_id: hospitalId,
        service_id: serviceId,
        origin_timestamp: originTimestamp,
        history: toForecastHistory(featureWindow),
        horizon
      });
      return { featureWindow, forecast };
    }
  });
}

function toForecastHistory(featureWindow: FeatureWindowResponse): ForecastFeatureStep[] {
  return featureWindow.history.map((row) => {
    const step = {} as ForecastFeatureStep;
    for (const channel of FEATURE_CHANNELS) {
      const index = featureWindow.channels.indexOf(channel);
      if (index < 0) {
        throw new Error(`Feature window is missing required channel: ${channel}`);
      }
      step[channel] = Number(row[index]);
    }
    return step;
  });
}
