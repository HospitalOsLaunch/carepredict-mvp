"""Prediction request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from services.api.schemas.intervention import PlannedIntervention


class ChargePredictionRequest(BaseModel):
    """Request schema for ``POST /predict/charge``."""

    model_config = ConfigDict(extra="forbid")

    service_id: str
    hospital_id: str
    timestamp: datetime
    planned_interventions: list[PlannedIntervention] = Field(default_factory=list)


class AttentionWeights(BaseModel):
    """Top attention features returned by the model."""

    model_config = ConfigDict(extra="forbid")

    top_features: list[str]


class ChargePredictionResponse(BaseModel):
    """Exact response schema required by pass 2."""

    model_config = ConfigDict(extra="forbid")

    value: int
    lower_90: int
    upper_90: int
    coverage: float
    mape: float
    crps: float
    model_version: str
    attention_weights: AttentionWeights
