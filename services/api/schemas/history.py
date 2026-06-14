"""Pydantic schemas for canonical feature-history windows."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

FEATURE_WINDOW_CHANNELS: tuple[str, ...] = (
    "admissions_h",
    "discharges_h",
    "nurse_count",
    "aide_count",
    "overtime_hours",
    "patient_count",
    "occupancy_rate",
)


class FeatureWindowResponse(BaseModel):
    """Canonical 7-channel feature window aligned for v2 forecasting."""

    model_config = ConfigDict(extra="forbid")

    service_id: str
    hospital_id: str
    origin_timestamp: datetime
    length: int
    channels: list[str]
    history: list[Annotated[list[float], Field(min_length=7, max_length=7)]]
