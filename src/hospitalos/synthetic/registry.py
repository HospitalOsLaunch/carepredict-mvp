"""Frozen cohort plans; split entire structures before generating any trajectories."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter
from typing import Annotated, Any, Literal, Self

import numpy as np
from pydantic import Field, StrictInt, model_validator

from .config import FrozenConfig, HospitalConfig, Identifier, Multiplier

Partition = Literal["train", "validation", "test"]
Template = Literal["MED_POLY", "CSG", "PNEUMO", "CARDIO"]
PoleShape = Annotated[tuple[Template, ...], Field(min_length=1, max_length=8)]


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def shape_key(poles: tuple[PoleShape, ...]) -> str:
    """Ignore names, ordering and numerical parameters, retain specialty multiplicities."""
    return digest(sorted(sorted(pole) for pole in poles))


def structure_key(config: HospitalConfig) -> str:
    return shape_key(tuple(tuple(unit.template for unit in pole.units) for pole in config.poles))


def physics_shape_key(poles: tuple[PoleShape, ...]) -> str:
    # v041 ignores pole boundaries: regrouping the same units is not a new physics topology.
    return digest(sorted(template for pole in poles for template in pole))


class ParameterRanges(FrozenConfig):
    """Engineering variation ranges, not estimates from real hospital data."""

    beds_min: Annotated[StrictInt, Field(ge=4, le=200)] = 20
    beds_max: Annotated[StrictInt, Field(ge=4, le=200)] = 32
    arrival_min: Multiplier = 0.8
    arrival_max: Multiplier = 1.2
    resource_min: Multiplier = 0.8
    resource_max: Multiplier = 1.2

    @model_validator(mode="after")
    def ordered(self) -> Self:
        for name in ("beds", "arrival", "resource"):
            if getattr(self, f"{name}_min") > getattr(self, f"{name}_max"):
                raise ValueError(f"Reversed {name} range")
        return self


class StructureSpec(FrozenConfig):
    structure_id: Identifier
    partition: Partition
    mechanism_family: Literal["v041"] = "v041"
    poles: Annotated[tuple[PoleShape, ...], Field(min_length=1, max_length=12)]
    hospitals: Annotated[StrictInt, Field(ge=1, le=100)] = 2
    replicates: Annotated[StrictInt, Field(ge=1, le=100)] = 2


class CohortPlan(FrozenConfig):
    schema_version: Literal["0.1"] = "0.1"
    cohort_id: Identifier
    seed: Annotated[StrictInt, Field(ge=0, le=2**32 - 1)]
    start: dt.date
    days: Annotated[StrictInt, Field(ge=1, le=366)] = 365
    warmup_days: Annotated[StrictInt, Field(ge=0, le=365)] = 61
    split_axis: Literal["structure", "mechanism"] = "structure"
    ranges: ParameterRanges = ParameterRanges()
    structures: Annotated[tuple[StructureSpec, ...], Field(min_length=3)]

    @model_validator(mode="after")
    def reserved_groups(self) -> Self:
        if {s.partition for s in self.structures} != {"train", "validation", "test"}:
            raise ValueError("Reserve train, validation and test before generation")
        ids = [s.structure_id for s in self.structures]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate structure_id")
        owners: dict[str, str] = {}
        physics_owners: dict[str, str] = {}
        mechanisms: dict[str, str] = {}
        for spec in self.structures:
            key = shape_key(spec.poles)
            if owners.setdefault(key, spec.partition) != spec.partition:
                raise ValueError("Structural clone crosses partitions, including renamed shapes")
            physical_key = physics_shape_key(spec.poles)
            if physics_owners.setdefault(physical_key, spec.partition) != spec.partition:
                raise ValueError(
                    "Effective v041 structure crosses partitions after pole regrouping"
                )
            if (
                self.split_axis == "mechanism"
                and mechanisms.setdefault(spec.mechanism_family, spec.partition) != spec.partition
            ):
                raise ValueError("Mechanism crosses partitions; v041 alone cannot test G4")
        try:
            self.start - dt.timedelta(days=self.warmup_days)
            self.start + dt.timedelta(days=self.days)
        except OverflowError as exc:
            raise ValueError("Simulation dates are out of range") from exc
        return self


class World(FrozenConfig):
    world_id: Identifier
    structure_id: Identifier
    structure_sha256: str
    hospital_index: Annotated[StrictInt, Field(ge=0)]
    replicate: Annotated[StrictInt, Field(ge=0)]
    config: HospitalConfig


def _entries(plan: CohortPlan) -> tuple[World, ...]:
    worlds = []
    ranges = plan.ranges
    for spec in sorted(plan.structures, key=lambda item: item.structure_id):
        for index in range(spec.hospitals):
            identity = [plan.cohort_id, plan.seed, spec.structure_id, index]
            hospital_id = "H_" + digest(identity)[:24]
            rng = np.random.Generator(np.random.PCG64(int(digest([identity, "parameters"]), 16)))
            poles = []
            for p, templates in enumerate(spec.poles):
                units = []
                for u, template in enumerate(templates):
                    beds = int(rng.integers(ranges.beds_min, ranges.beds_max + 1))
                    # Retain the four reference profiles' bed-type proportions.
                    fractions = {
                        "MED_POLY": (5 / 28, 16 / 28),
                        "CSG": (5 / 24, 14 / 24),
                        "PNEUMO": (7 / 26, 1.0),
                        "CARDIO": (4 / 24, 12 / 24),
                    }
                    iso, oxygen = fractions[template]
                    units.append(
                        {
                            "unit_id": f"U_{p:02d}_{u:02d}",
                            "template": template,
                            "beds": beds,
                            "isolation_beds": int(beds * iso),
                            "oxygen_beds": int(beds * oxygen),
                            "arrival_scale": round(
                                float(rng.uniform(ranges.arrival_min, ranges.arrival_max)), 6
                            ),
                        }
                    )
                poles.append({"pole_id": f"P_{p:02d}", "units": units})
            resources = {
                name: round(float(rng.uniform(ranges.resource_min, ranges.resource_max)), 6)
                for name in ("cleaning", "imaging", "transport", "specialist")
            }
            for replicate in range(spec.replicates):
                seed = int(digest([identity, "trajectory", replicate])[:8], 16)
                config = HospitalConfig.model_validate(
                    {
                        "hospital_id": hospital_id,
                        "seed": seed,
                        "start": plan.start,
                        "days": plan.days,
                        "warmup_days": plan.warmup_days,
                        "partition": spec.partition,
                        "mechanism_family": spec.mechanism_family,
                        "poles": poles,
                        "shared_resources": resources,
                    }
                )
                worlds.append(
                    World(
                        world_id="W_" + config.fingerprint[:24],
                        structure_id=spec.structure_id,
                        structure_sha256=structure_key(config),
                        hospital_index=index,
                        replicate=replicate,
                        config=config,
                    )
                )
    return tuple(worlds)


def validate_worlds(worlds: tuple[World, ...]) -> None:
    """Also callable across registries: do not split hospital identities or shapes."""
    groups: dict[tuple[str, str], str] = {}
    seeds: set[int] = set()
    ids: set[str] = set()
    hospital_parameters: dict[str, str] = {}
    for world in worlds:
        config = world.config
        key = structure_key(config)
        if world.structure_sha256 != key:
            raise ValueError("Incorrect structural fingerprint")
        physical_key = physics_shape_key(
            tuple(tuple(unit.template for unit in pole.units) for pole in config.poles)
        )
        for kind, identity in (
            ("hospital", config.hospital_id),
            ("structure", key),
            ("effective structure", physical_key),
        ):
            if groups.setdefault((kind, identity), config.partition) != config.partition:
                raise ValueError(f"{kind} crosses partitions")
        parameters = config.model_dump(
            mode="json", exclude={"seed", "start", "days", "warmup_days"}
        )
        fingerprint = digest(parameters)
        if hospital_parameters.setdefault(config.hospital_id, fingerprint) != fingerprint:
            raise ValueError("Hospital parameters change between replicates")
        if world.world_id in ids:
            raise ValueError("Duplicate world_id")
        if config.seed in seeds:
            raise ValueError("Trajectory seed collision; choose another cohort seed")
        ids.add(world.world_id)
        seeds.add(config.seed)


class Registry(FrozenConfig):
    schema_version: Literal["0.1"] = "0.1"
    plan: CohortPlan
    worlds: tuple[World, ...]

    @model_validator(mode="after")
    def verified(self) -> Self:
        validate_worlds(self.worlds)
        if self.worlds != _entries(self.plan):
            raise ValueError("Registry entries differ from their deterministic plan")
        return self

    @property
    def fingerprint(self) -> str:
        return digest(self.model_dump(mode="json"))

    def summary(self) -> dict[str, Any]:
        partitions = {}
        for partition in ("train", "validation", "test"):
            worlds = [w for w in self.worlds if w.config.partition == partition]
            hospitals = {w.config.hospital_id: w.config for w in worlds}
            partitions[partition] = {
                "worlds": len(worlds),
                "hospitals": len(hospitals),
                "structures": len({w.structure_sha256 for w in worlds}),
                "poles_per_hospital": sorted({len(c.poles) for c in hospitals.values()}),
                "units_per_hospital": sorted({len(c.units) for c in hospitals.values()}),
                "beds_per_hospital": sorted(
                    sum(u.beds for u in c.units) for c in hospitals.values()
                ),
            }
        return {
            "partitions": partitions,
            "mechanism_world_counts": dict(Counter(w.config.mechanism_family for w in self.worlds)),
            "mechanism_holdout": self.plan.split_axis == "mechanism",
        }


def compile_registry(plan: CohortPlan) -> Registry:
    return Registry(plan=plan, worlds=_entries(plan))
