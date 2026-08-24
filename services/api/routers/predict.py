"""Prediction endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from services.api.dependencies.feature_fetcher import FeastFeatureFetcher, get_feature_fetcher
from services.api.dependencies.model_loader import PredictionModelBundle, get_model_bundle
from services.api.middleware.evidently import EvidentlyPredictionLogger, get_evidently_logger
from services.api.schemas.prediction import (
    AttentionWeights,
    ChargePredictionRequest,
    ChargePredictionResponse,
)
from services.ml.models.tft_model import FutureIntervention

router = APIRouter(prefix="/predict", tags=["prediction"])


@router.post("/charge", response_model=ChargePredictionResponse)
def predict_charge(
    request: ChargePredictionRequest,
    feature_fetcher: FeastFeatureFetcher = Depends(get_feature_fetcher),  # noqa: B008
    model_bundle: PredictionModelBundle = Depends(get_model_bundle),  # noqa: B008
    evidently_logger: EvidentlyPredictionLogger = Depends(get_evidently_logger),  # noqa: B008
) -> ChargePredictionResponse:
    """Predict J+12h nursing care load with a calibrated 90% interval."""
    features = feature_fetcher.fetch(request)
    interventions = [
        FutureIntervention(
            intervention_type=intervention.type,
            scheduled_at=intervention.scheduled_at,
            count=intervention.count,
        )
        for intervention in request.planned_interventions
    ]
    forecast = model_bundle.model.predict(features.history, interventions=interventions)
    interval = model_bundle.conformal.predict_interval(forecast.value)
    response = ChargePredictionResponse(
        value=round(interval.value),
        lower_90=round(interval.lower),
        upper_90=round(interval.upper),
        coverage=interval.coverage,
        mape=model_bundle.mape,
        crps=model_bundle.crps,
        model_version=forecast.model_version,
        attention_weights=AttentionWeights(top_features=forecast.top_features),
    )
    evidently_logger.log_prediction(request, response)
    return response
