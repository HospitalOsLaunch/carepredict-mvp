"""JSON-only interface for synthetic learned residual preparation distributions.

Target excludes downstream queues, transport and cleaning. No estimator or
pickle is accepted by the serving API; clinical authorization remains observed.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator

from hospitalos.operational.contract import Closed, Identifier, instant

from .innovations import uniform
from .models import State, discharge_blockers

EDGES = (30, 60, 120, 240, 480, 1440)
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class PreparationCurve(Closed):
    patient_id: Identifier
    mass: Annotated[tuple[Probability, ...], Field(min_length=6, max_length=6)]
    beyond_24h: Probability

    @model_validator(mode="after")
    def probability(self) -> Self:
        if not math.isclose(sum(self.mass) + self.beyond_24h, 1, abs_tol=1e-9):
            raise ValueError("Preparation mass and tail must sum to one")
        return self

    def quantile(self, probability: float) -> int | None:
        if not 0 < probability < 1:
            raise ValueError("Quantile probability must be in (0,1)")
        cumulative = 0.0
        for minute, mass in zip(EDGES, self.mass, strict=True):
            cumulative += mass
            if cumulative >= probability:
                return minute
        return None


class PreparationForecasts(Closed):
    schema_version: Literal["PREPARATION_FORECAST_1"] = "PREPARATION_FORECAST_1"
    target: Literal["residual_preparation_before_resource_queue"] = (
        "residual_preparation_before_resource_queue"
    )
    evidence: Literal["synthetic_fit_research_only"] = "synthetic_fit_research_only"
    model_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    hospital_id: Identifier
    state_fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    origin: datetime
    model_available_at: datetime
    curves: Annotated[tuple[PreparationCurve, ...], Field(max_length=400)]

    @field_validator("origin", "model_available_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def clocks(self) -> Self:
        if self.model_available_at > self.origin:
            raise ValueError("Model was not available at the decision origin")
        if len({c.patient_id for c in self.curves}) != len(self.curves):
            raise ValueError("Duplicate preparation curve")
        return self


def eligible_patients(state: State) -> tuple[str, ...]:
    return tuple(
        sorted(
            p.id
            for p in state.patients
            if not discharge_blockers(state, p, include_request=False, require_capacity=False)
        )
    )


def validate_preparation(state: State, forecasts: PreparationForecasts) -> None:
    if (
        state.issues
        or forecasts.origin != state.at
        or forecasts.hospital_id != state.hospital_id
        or forecasts.state_fingerprint != state.fingerprint
    ):
        raise ValueError("Preparation forecast does not match this usable as-of state")
    if set(eligible_patients(state)) != {c.patient_id for c in forecasts.curves}:
        raise ValueError("Preparation curves must cover exactly the eligible observed patients")


def preparation_draw(curve: PreparationCurve, seed: int, scenario: int) -> int | None:
    value = uniform(seed, scenario, "learned_preparation", curve.patient_id)
    cumulative = 0.0
    for minute, mass in zip(EDGES, curve.mass, strict=True):
        cumulative += mass
        if value < cumulative:
            return minute
    return None  # Preserve survival beyond the modeled horizon; never force a departure.


class PreparationFeatures(Closed):
    occupied_per_staffed_bed: Annotated[float, Field(ge=0, le=10, allow_inf_nan=False)]
    waiting_per_staffed_bed: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
    hour_utc: Annotated[StrictInt, Field(ge=0, le=23)]
    weekday_utc: Annotated[StrictInt, Field(ge=0, le=6)]

    def vector(self) -> tuple[float, ...]:
        angle = 2 * math.pi * self.hour_utc / 24
        return (
            self.occupied_per_staffed_bed,
            self.waiting_per_staffed_bed,
            math.sin(angle),
            math.cos(angle),
            float(self.weekday_utc >= 5),
        )


def features_at(state: State, patient_id: str) -> PreparationFeatures:
    patient = next(p for p in state.patients if p.id == patient_id)
    bed = next(b for b in state.beds if b.id == patient.bed_id)
    unit = next(u for u in state.units if u.id == bed.unit_id)
    if unit.staffed_beds is None or unit.staffed_beds <= 0:
        raise ValueError("Positive observed staffed capacity required for load features")
    denominator = unit.staffed_beds
    return PreparationFeatures(
        occupied_per_staffed_bed=sum(
            b.unit_id == unit.id and b.occupant is not None for b in state.beds
        )
        / denominator,
        waiting_per_staffed_bed=sum(
            p.status == "waiting" and unit.id in p.compatible_units for p in state.patients
        )
        / denominator,
        hour_utc=state.at.hour,
        weekday_utc=state.at.weekday(),
    )
