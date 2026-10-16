"""Operational v2 research contract: observations, never simulator internals.

This version coexists with the frozen Nantes v1 contract. It does not replace
its production validator or claim that an actual hospital connector is built.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

Level = Literal["unit", "pole", "hospital", "ght"]
Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_:.-]{0,159}$")]
Nonnegative = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
SCHEMA: Literal["OPERATIONAL_V2_RESEARCH_1"] = "OPERATIONAL_V2_RESEARCH_1"
# SIIPS and the synthetic workload proxy have distinct units and never map to one another.
METRICS = {
    "occupancy": "patients",
    "open_beds": "beds",
    "ed_waiting": "patients",
    "medically_ready": "patients",
    "nurse_count": "persons",
    "aide_count": "persons",
    "care_workload_proxy": "synthetic_minutes_per_hour",
    "siips_score": "siips_points",
}
COUNTS = {"occupancy", "open_beds", "ed_waiting", "medically_ready"}
ADDITIVE = set(METRICS) - {"siips_score"}


def instant(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An explicit timezone is required")
    return value.astimezone(dt.UTC)


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Node(Closed):
    entity_id: Identifier
    level: Level
    parent_id: Identifier | None = None
    capacity_beds: Nonnegative | None = None
    isolation_beds: Nonnegative | None = None
    oxygen_beds: Nonnegative | None = None
    activity: Literal["medicine", "geriatrics", "cardiology", "respiratory", "unknown"] = "unknown"


class Topology(Closed):
    schema_version: Literal["OPERATIONAL_V2_RESEARCH_1"] = SCHEMA
    topology_id: Identifier
    version: Annotated[StrictInt, Field(ge=1)] = 1
    valid_from: dt.datetime
    valid_to: dt.datetime | None = None
    available_at: dt.datetime
    nodes: Annotated[tuple[Node, ...], Field(min_length=1)]

    @field_validator("valid_from", "valid_to", "available_at")
    @classmethod
    def utc(cls, value: dt.datetime | None) -> dt.datetime | None:
        return instant(value) if value is not None else None

    @model_validator(mode="after")
    def tree(self) -> Self:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("Empty topology validity interval")
        nodes = {n.entity_id: n for n in self.nodes}
        if len(nodes) != len(self.nodes) or sum(n.parent_id is None for n in self.nodes) != 1:
            raise ValueError("Topology requires unique nodes and one root")
        allowed = {
            "unit": {"pole", "hospital"},
            "pole": {"hospital"},
            "hospital": {"ght"},
            "ght": set(),
        }
        for n in self.nodes:
            if n.parent_id is not None and (
                n.parent_id not in nodes or nodes[n.parent_id].level not in allowed[n.level]
            ):
                raise ValueError("Unknown parent or invalid hierarchy")
        return self

    def usable(self, at: dt.datetime) -> bool:
        at = instant(at)
        return (
            self.available_at <= at
            and self.valid_from <= at
            and (self.valid_to is None or at < self.valid_to)
        )

    def descendants(self, entity: str) -> set[str]:
        if entity not in {n.entity_id for n in self.nodes}:
            raise ValueError("Unknown entity")
        result = {entity}
        for _ in range(4):
            result |= {n.entity_id for n in self.nodes if n.parent_id in result}
        return result

    def frontier(self, entities: Iterable[str]) -> tuple[Node, ...]:
        ids = tuple(entities)
        nodes = {n.entity_id: n for n in self.nodes}
        if not ids or len(ids) != len(set(ids)) or not set(ids) <= nodes.keys():
            raise ValueError("Invalid observation frontier")
        coverage = [self.descendants(i) for i in ids]
        if any(a & b for j, a in enumerate(coverage) for b in coverage[j + 1 :]):
            raise ValueError("Observation frontier double-counts descendants")
        leaves = {n.entity_id for n in self.nodes} - {n.parent_id for n in self.nodes}
        if not leaves <= set.union(*coverage):
            raise ValueError("Observation frontier does not cover its declared perimeter")
        return tuple(nodes[i] for i in ids)


def select_topology(versions: Iterable[Topology], at: dt.datetime) -> Topology:
    candidates = [t for t in versions if t.usable(at)]
    if not candidates or len({t.topology_id for t in candidates}) != 1:
        raise ValueError("No unambiguous topology known at this origin")
    keys = [(t.version, t.available_at) for t in candidates]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate topology version")
    return max(candidates, key=lambda t: (t.version, t.available_at))


class Observation(Closed):
    schema_version: Literal["OPERATIONAL_V2_RESEARCH_1"] = SCHEMA
    event_id: Identifier
    version: Annotated[StrictInt, Field(ge=1)] = 1
    entity_id: Identifier
    level: Level
    source_system: Identifier
    event_time: dt.datetime
    recorded_at: dt.datetime | None = None
    ingested_at: dt.datetime | None = None
    available_at: dt.datetime
    values: dict[str, int | float | None]

    @field_validator("event_time", "recorded_at", "ingested_at", "available_at")
    @classmethod
    def utc(cls, value: dt.datetime | None) -> dt.datetime | None:
        return instant(value) if value is not None else None

    @field_validator("values", mode="before")
    @classmethod
    def measures(cls, values: Any) -> Any:
        if not isinstance(values, dict) or not values or not values.keys() <= METRICS.keys():
            raise ValueError("Unknown or empty operational measures")
        for key, value in values.items():
            if value is None:
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("Operational measures must be finite nonnegative numbers")
            if key in COUNTS and type(value) is not int:
                raise ValueError("Counts must be integers")
        return values

    @model_validator(mode="after")
    def clocks(self) -> Self:
        clocks = [self.event_time, self.recorded_at, self.ingested_at, self.available_at]
        known = [c for c in clocks if c is not None]
        if known != sorted(known):
            raise ValueError("Require event <= recorded <= ingested <= available")
        return self

    def content(self) -> str:
        return self.model_dump_json(exclude={"ingested_at", "available_at"})


class Cursor:
    """Shared real/synthetic as-of consumer; no imputation of absent children."""

    def __init__(self, timezone: dt.tzinfo = dt.UTC) -> None:
        self.timezone = timezone
        self.now: dt.datetime | None = None
        self.events: dict[tuple[str, int], str] = {}
        self.identities: dict[str, tuple[str, str, dt.datetime]] = {}
        self.slots: dict[tuple[str, dt.datetime], Observation] = {}
        self.latest: dict[str, Observation] = {}
        self.hourly_latest: dict[tuple[str, int], Observation] = {}

    def advance(
        self, at: dt.datetime, deliveries: Iterable[Observation], topology: Topology
    ) -> None:
        at = instant(at)
        if (self.now is not None and at < self.now) or not topology.usable(at):
            raise ValueError("Invalid as-of origin or unavailable topology")
        nodes = {n.entity_id: n for n in topology.nodes}
        for obs in deliveries:
            if obs.available_at > at:
                raise ValueError("Future observation")
            if obs.entity_id not in nodes or obs.level != nodes[obs.entity_id].level:
                raise ValueError("Observation does not belong to this topology")
            identity = (obs.entity_id, obs.source_system, obs.event_time)
            if self.identities.setdefault(obs.event_id, identity) != identity:
                raise ValueError("Event identity changed across versions")
            key = (obs.event_id, obs.version)
            if key in self.events:
                if self.events[key] != obs.content():
                    raise ValueError("Conflicting event version")
                continue  # identical transport retry; earliest receipt already retained
            self.events[key] = obs.content()
            slot = (obs.entity_id, obs.event_time)
            old = self.slots.get(slot)
            if old is not None and old.event_id != obs.event_id:
                raise ValueError(
                    "Multiple sources for same snapshot require explicit reconciliation"
                )
            if old is None or obs.version > old.version:
                self.slots[slot] = obs
                previous = self.latest.get(obs.entity_id)
                if previous is None or (obs.event_time, obs.version) > (
                    previous.event_time,
                    previous.version,
                ):
                    self.latest[obs.entity_id] = obs
                hour_key = (obs.entity_id, obs.event_time.astimezone(self.timezone).hour)
                previous_hour = self.hourly_latest.get(hour_key)
                if previous_hour is None or (obs.event_time, obs.version) > (
                    previous_hour.event_time,
                    previous_hour.version,
                ):
                    self.hourly_latest[hour_key] = obs
        self.now = at

    def same_clock_hour(self, entity: str, target: dt.datetime) -> Observation | None:
        hour = instant(target).astimezone(self.timezone).hour
        return self.hourly_latest.get((entity, hour))
