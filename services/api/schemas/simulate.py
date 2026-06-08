"""Pydantic schemas for Hospital World Model simulation."""

from __future__ import annotations

import math
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActionStep(BaseModel):
    """Known intervention vector for one future hourly step."""

    model_config = ConfigDict(extra="forbid", strict=True)

    scheduled_admissions: Annotated[int, Field(ge=0, le=200)]
    scheduled_discharges: Annotated[int, Field(ge=0, le=200)]
    staff_redeployments: Annotated[int, Field(ge=0, le=200)]
    scheduled_surgeries: Annotated[int, Field(ge=0, le=200)]
    expected_transfers: Annotated[int, Field(ge=0, le=200)]

    def to_vector(self) -> list[float]:
        """Return the action step as a float vector in model action order."""
        return [
            float(self.scheduled_admissions),
            float(self.scheduled_discharges),
            float(self.staff_redeployments),
            float(self.scheduled_surgeries),
            float(self.expected_transfers),
        ]


class SimulationRequest(BaseModel):
    """Simulation request for counterfactual hospital workload planning."""

    model_config = ConfigDict(extra="forbid")

    hospital_id: Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]
    service_id: Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]
    history_siips: Annotated[list[float], Field(min_length=24, max_length=720)]
    actions: Annotated[list[ActionStep], Field(min_length=1, max_length=168)]

    @model_validator(mode="after")
    def validate_history_values(self) -> Self:
        """Ensure SIIPS history values are finite and non-negative."""
        for value in self.history_siips:
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError("history_siips values must be finite and non-negative")
        return self


class SimulationStepResult(BaseModel):
    """One simulated future hourly point."""

    model_config = ConfigDict(extra="forbid")

    step_index: int
    predicted_siips: float
    lower_bound: float
    upper_bound: float
    reward: float
    is_critical: bool


class SimulationResponse(BaseModel):
    """Simulation response containing point predictions and conformal intervals."""

    model_config = ConfigDict(extra="forbid")

    status: str
    hospital_id: str
    service_id: str
    model_version: str
    results: list[SimulationStepResult]
