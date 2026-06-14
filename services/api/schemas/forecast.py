"""Pydantic schemas for action-free v2 charge forecasts."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

FORECAST_HISTORY_LENGTH = 120
FORECAST_HORIZON_MAX = 48


class ForecastFeatureStep(BaseModel):
    """One hourly 7-channel feature vector for the v2 forecast head."""

    model_config = ConfigDict(extra="forbid")

    admissions_h: Annotated[float, Field(ge=0.0)]
    discharges_h: Annotated[float, Field(ge=0.0)]
    nurse_count: Annotated[float, Field(ge=0.0)]
    aide_count: Annotated[float, Field(ge=0.0)]
    overtime_hours: Annotated[float, Field(ge=0.0)]
    patient_count: Annotated[float, Field(ge=0.0)]
    occupancy_rate: Annotated[float, Field(ge=0.0)]

    @model_validator(mode="after")
    def validate_finite_values(self) -> Self:
        """Ensure all feature values are finite."""
        for value in self.to_vector():
            if not math.isfinite(value):
                raise ValueError("forecast feature values must be finite")
        return self

    def to_vector(self) -> list[float]:
        """Return the feature row in the trained channel order."""
        return [
            float(self.admissions_h),
            float(self.discharges_h),
            float(self.nurse_count),
            float(self.aide_count),
            float(self.overtime_hours),
            float(self.patient_count),
            float(self.occupancy_rate),
        ]


class ForecastRequest(BaseModel):
    """Action-free charge forecast request for a service and origin timestamp."""

    model_config = ConfigDict(extra="forbid")

    hospital_id: Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]
    service_id: Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]
    origin_timestamp: datetime
    history: Annotated[
        list[ForecastFeatureStep],
        Field(min_length=FORECAST_HISTORY_LENGTH, max_length=FORECAST_HISTORY_LENGTH),
    ]
    horizon: Annotated[int, Field(ge=1, le=FORECAST_HORIZON_MAX)] = FORECAST_HORIZON_MAX


class ForecastStep(BaseModel):
    """One future hourly forecast point."""

    model_config = ConfigDict(extra="forbid")

    step_index: int
    predicted_siips: float
    lower_90: float
    upper_90: float


class ForecastResponse(BaseModel):
    """Forecast response containing raw SIIPS predictions and conformal intervals."""

    model_config = ConfigDict(extra="forbid")

    status: str
    hospital_id: str
    service_id: str
    model_version: str
    granularity: str
    results: list[ForecastStep]
