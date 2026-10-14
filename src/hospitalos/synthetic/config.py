"""Validated, immutable topology for one synthetic hospital and one partition."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
Multiplier = Annotated[float, Field(ge=0, le=10, allow_inf_nan=False, strict=True)]


class FrozenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UnitConfig(FrozenConfig):
    unit_id: Identifier
    template: Literal["MED_POLY", "CSG", "PNEUMO", "CARDIO"]
    beds: Annotated[StrictInt, Field(ge=4, le=200)]
    isolation_beds: Annotated[StrictInt, Field(ge=0)]
    oxygen_beds: Annotated[StrictInt, Field(ge=0)]
    arrival_scale: Multiplier = 1.0

    @model_validator(mode="after")
    def compatible_beds(self) -> Self:
        # In the inherited engine, isolation beds are a subset of oxygen beds.
        if not self.isolation_beds <= self.oxygen_beds <= self.beds:
            raise ValueError("Require isolation_beds <= oxygen_beds <= beds")
        return self


class PoleConfig(FrozenConfig):
    pole_id: Identifier
    units: Annotated[tuple[UnitConfig, ...], Field(min_length=1)]


class SharedResources(FrozenConfig):
    """Hospital-wide multipliers; capacities rounded down to integer slots/agents."""

    cleaning: Multiplier = 1.0
    imaging: Multiplier = 1.0
    transport: Multiplier = 1.0
    specialist: Multiplier = 1.0


class HospitalConfig(FrozenConfig):
    schema_version: Literal["0.1"] = "0.1"
    hospital_id: Identifier
    seed: Annotated[StrictInt, Field(ge=0, le=2**32 - 1)]
    start: dt.date
    days: Annotated[StrictInt, Field(ge=1, le=366)] = 365
    warmup_days: Annotated[StrictInt, Field(ge=0, le=365)] = 61
    partition: Literal["development", "train", "validation", "test"] = "development"
    mechanism_family: Literal["v041"] = "v041"
    poles: Annotated[tuple[PoleConfig, ...], Field(min_length=1)]
    shared_resources: SharedResources = SharedResources()

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        ids = [self.hospital_id]
        ids.extend(pole.pole_id for pole in self.poles)
        ids.extend(unit.unit_id for pole in self.poles for unit in pole.units)
        if len(ids) != len(set(ids)):
            raise ValueError("Hospital, pole and unit IDs must be unique within the hospital")
        # Fail before simulation if the warm-up or end would exceed datetime bounds.
        try:
            self.start - dt.timedelta(days=self.warmup_days)
            self.start + dt.timedelta(days=self.days)
        except OverflowError as exc:
            raise ValueError("Simulation dates are out of range") from exc
        return self

    @property
    def units(self) -> tuple[UnitConfig, ...]:
        return tuple(unit for pole in self.poles for unit in pole.units)

    @property
    def unit_poles(self) -> dict[str, str]:
        return {unit.unit_id: pole.pole_id for pole in self.poles for unit in pole.units}

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def load_config(path: Path) -> HospitalConfig:
    return HospitalConfig.model_validate_json(path.read_text(encoding="utf-8"))


def validate_partition_isolation(configs: list[HospitalConfig]) -> None:
    """A hospital ID cannot occur in two partitions, even with different seeds."""
    partitions: dict[str, str] = {}
    for config in configs:
        previous = partitions.setdefault(config.hospital_id, config.partition)
        if previous != config.partition:
            raise ValueError(f"Hospital {config.hospital_id} crosses partitions")
