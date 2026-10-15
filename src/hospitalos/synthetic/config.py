"""Validated, immutable topology for one synthetic hospital and one partition."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
Multiplier = Annotated[float, Field(ge=0, le=10, allow_inf_nan=False, strict=True)]
MechanismFamily = Literal["v041", "local_v1", "hybrid_v1"]


class FrozenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DynamicsConfig(FrozenConfig):
    """Versioned engineering hypotheses, independent of resource pooling."""

    arrivals: Literal["v041", "shared_bursts_v1", "appointments_v1"] = "v041"
    discharges: Literal["v041", "daily_rounds_v1", "rolling_v1"] = "v041"
    staffing: Literal["v041", "persistent_absence_v1", "shared_float_v1"] = "v041"


class ChangeWindow(FrozenConfig):
    change_id: Identifier
    starts_at: dt.datetime
    ends_at: dt.datetime | None = None

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        for value in (self.starts_at, self.ends_at):
            if value is not None and (
                value.utcoffset() != dt.timedelta(hours=1)
                or value.minute
                or value.second
                or value.microsecond
            ):
                raise ValueError("Changes require whole hours at explicit fixed UTC+01:00")
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("Change end must be strictly after start")
        return self


class BedClosure(ChangeWindow):
    kind: Literal["bed_closure"]
    unit_id: Identifier
    additional_closed_beds: Annotated[StrictInt, Field(ge=1, le=200)]


class ServiceCapacityChange(ChangeWindow):
    kind: Literal["service_capacity"]
    resource: Literal["cleaning", "imaging", "transport", "specialist"]
    multiplier: Multiplier


class StaffingShortage(ChangeWindow):
    kind: Literal["staffing_shortage"]
    unit_id: Identifier
    additional_absent: Annotated[StrictInt, Field(ge=1, le=200)]

    @model_validator(mode="after")
    def full_shifts(self) -> Self:
        # The inherited sid() uses midnight, 07:00 and 15:00 boundaries.
        if any(v is not None and v.hour not in (0, 7, 15) for v in (self.starts_at, self.ends_at)):
            raise ValueError("Staff shortages must start/end at 00:00, 07:00 or 15:00")
        return self


OrganisationalChange = Annotated[
    BedClosure | ServiceCapacityChange | StaffingShortage, Field(discriminator="kind")
]


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


class PoleResourceWeights(FrozenConfig):
    pole_id: Identifier
    weights: SharedResources = SharedResources()


class RoutingLink(FrozenConfig):
    origin: Identifier
    destination: Identifier


class HospitalConfig(FrozenConfig):
    schema_version: Literal["0.1"] = "0.1"
    hospital_id: Identifier
    seed: Annotated[StrictInt, Field(ge=0, le=2**32 - 1)]
    start: dt.date
    days: Annotated[StrictInt, Field(ge=1, le=366)] = 365
    warmup_days: Annotated[StrictInt, Field(ge=0, le=365)] = 61
    partition: Literal["development", "train", "validation", "test"] = "development"
    mechanism_family: MechanismFamily = "v041"
    dynamics: DynamicsConfig = DynamicsConfig()
    changes: tuple[OrganisationalChange, ...] = ()
    poles: Annotated[tuple[PoleConfig, ...], Field(min_length=1)]
    shared_resources: SharedResources = SharedResources()
    pole_resource_weights: tuple[PoleResourceWeights, ...] = ()
    routing_links: tuple[RoutingLink, ...] = ()
    cross_pole_delay_h: Annotated[StrictInt, Field(ge=1, le=168)] = 12

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        ids = [self.hospital_id]
        ids.extend(pole.pole_id for pole in self.poles)
        ids.extend(unit.unit_id for pole in self.poles for unit in pole.units)
        if len(ids) != len(set(ids)):
            raise ValueError("Hospital, pole and unit IDs must be unique within the hospital")
        pole_ids = {pole.pole_id for pole in self.poles}
        if self.mechanism_family != "v041" and len(pole_ids) < 2:
            raise ValueError("Local/hybrid mechanisms require at least two poles")
        weights = {item.pole_id: item.weights for item in self.pole_resource_weights}
        if len(weights) != len(self.pole_resource_weights) or not weights.keys() <= pole_ids:
            raise ValueError("Resource weights must name unique known poles")
        if self.mechanism_family == "v041" and (weights or self.routing_links):
            raise ValueError("v041 retains hospital pooling and unrestricted routing")
        if self.mechanism_family == "local_v1" and self.routing_links:
            raise ValueError("Local routing cannot have cross-pole links")
        if self.mechanism_family != "hybrid_v1" and self.cross_pole_delay_h != 12:
            raise ValueError("Cross-pole delay is configurable only for hybrid_v1")
        if self.mechanism_family == "hybrid_v1" and any(
            w.imaging != 1.0 or w.specialist != 1.0 for w in weights.values()
        ):
            raise ValueError("Hybrid imaging/specialist are shared, without local weights")
        for resource in ("cleaning", "imaging", "transport", "specialist"):
            if not any(getattr(weights.get(p, SharedResources()), resource) > 0 for p in pole_ids):
                raise ValueError(f"At least one pole must receive {resource} capacity")
        links = {(link.origin, link.destination) for link in self.routing_links}
        if len(links) != len(self.routing_links):
            raise ValueError("Duplicate routing link")
        if any(a not in pole_ids or b not in pole_ids or a == b for a, b in links):
            raise ValueError("Routing links must connect distinct known poles")
        # Fail before simulation if the warm-up or end would exceed datetime bounds.
        try:
            self.start - dt.timedelta(days=self.warmup_days)
            self.start + dt.timedelta(days=self.days)
        except OverflowError as exc:
            raise ValueError("Simulation dates are out of range") from exc
        recorded_start = dt.datetime.combine(
            self.start, dt.time(), dt.timezone(dt.timedelta(hours=1))
        )
        recorded_end = recorded_start + dt.timedelta(days=self.days)
        windows: dict[tuple[str, str], list[tuple[dt.datetime, dt.datetime]]] = {}
        change_ids = [c.change_id for c in self.changes]
        if len(set(change_ids)) != len(change_ids):
            raise ValueError("Duplicate change_id")
        units = {u.unit_id: u for u in self.units}
        for change in self.changes:
            end = change.ends_at or recorded_end
            if not recorded_start <= change.starts_at < recorded_end or end > recorded_end:
                raise ValueError("Changes must lie inside the recorded interval")
            if isinstance(change, ServiceCapacityChange):
                target: str = change.resource
            else:
                target = change.unit_id
                if target not in units:
                    raise ValueError("Change names an unknown unit")
                if (
                    isinstance(change, BedClosure)
                    and change.additional_closed_beds > units[target].beds
                ):
                    raise ValueError("Requested bed closure exceeds physical standard beds")
            windows.setdefault((change.kind, target), []).append((change.starts_at, end))
        for group in windows.values():
            ordered = sorted(group)
            if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:], strict=False)):
                raise ValueError("Overlapping changes for the same kind and target")
        return self

    @property
    def units(self) -> tuple[UnitConfig, ...]:
        return tuple(unit for pole in self.poles for unit in pole.units)

    @property
    def unit_poles(self) -> dict[str, str]:
        return {unit.unit_id: pole.pole_id for pole in self.poles for unit in pole.units}

    @property
    def fingerprint(self) -> str:
        # Preserve existing v041 dataset/world identities when adding inactive options.
        inactive = (
            {"pole_resource_weights", "routing_links", "cross_pole_delay_h"}
            if self.mechanism_family == "v041"
            else set()
        )
        if not self.changes:
            inactive.add("changes")
        if self.dynamics == DynamicsConfig():
            inactive.add("dynamics")
        return hashlib.sha256(self.model_dump_json(exclude=inactive).encode()).hexdigest()


def load_config(path: Path) -> HospitalConfig:
    return HospitalConfig.model_validate_json(path.read_text(encoding="utf-8"))


def validate_partition_isolation(configs: list[HospitalConfig]) -> None:
    """A hospital ID cannot occur in two partitions, even with different seeds."""
    partitions: dict[str, str] = {}
    for config in configs:
        previous = partitions.setdefault(config.hospital_id, config.partition)
        if previous != config.partition:
            raise ValueError(f"Hospital {config.hospital_id} crosses partitions")
