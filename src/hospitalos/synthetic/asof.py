"""Reconstruct unit, pole and hospital features using available deliveries only."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Literal, Self

from pydantic import model_validator

from .config import FrozenConfig, HospitalConfig
from .observations import Count, Delivery, Hour, ObservedState


class Source(FrozenConfig):
    unit_id: str
    event_id: str
    version: Count
    event_h: Hour
    available_h: Hour


class AsOfRow(FrozenConfig):
    sample_id: str
    run_id: str
    hospital_id: str
    entity_id: str
    level: Literal["unit", "pole", "hospital"]
    partition: str
    decision_h: int
    total_units: int
    observed_units: int
    missing: bool
    stale: bool
    stale_after_h: float
    max_age_h: float | None
    max_available_h: float | None
    sources: tuple[Source, ...]
    values: ObservedState | None

    @model_validator(mode="after")
    def check_provenance(self) -> Self:
        if not 0 < self.stale_after_h < float("inf"):
            raise ValueError("Invalid staleness threshold")
        if (
            self.decision_h < 0
            or self.total_units < 1
            or self.observed_units != len(self.sources)
            or not 0 <= self.observed_units <= self.total_units
            or len({source.unit_id for source in self.sources}) != len(self.sources)
        ):
            raise ValueError("Invalid observation counts")
        if self.missing != (self.observed_units < self.total_units):
            raise ValueError("Inconsistent missingness")
        if (self.values is None) != self.missing:
            raise ValueError("Incomplete groups cannot have filled values")
        if any(
            not source.event_h <= source.available_h <= self.decision_h for source in self.sources
        ):
            raise ValueError("Source information is not available at the decision time")
        age = max((self.decision_h - source.event_h for source in self.sources), default=None)
        available = max((source.available_h for source in self.sources), default=None)
        if age != self.max_age_h or available != self.max_available_h:
            raise ValueError("Source ages or availability do not match provenance")
        if self.stale != (age is not None and age > self.stale_after_h):
            raise ValueError("Inconsistent staleness mask")
        return self


def replay(
    deliveries: Iterable[Delivery],
    config: HospitalConfig,
    *,
    run_id: str,
    start_h: int = 0,
    end_h: int | None = None,
    stale_after_h: float = 6.0,
) -> Iterator[AsOfRow]:
    """No truth argument. A revision becomes usable only at its own availability.

    Late corrections to an older snapshot never replace a newer event-time snapshot.
    Missing units are not zero-filled; group values require all member units.
    """
    end = config.days * 24 if end_h is None else end_h
    if not 0 <= start_h < end <= config.days * 24:
        raise ValueError("Invalid replay interval")
    if not 0 < stale_after_h < float("inf"):
        raise ValueError("stale_after_h must be positive and finite")
    ordered = sorted(
        deliveries,
        key=lambda row: (row.available_h, row.event_id, row.event_version, row.delivery_id),
    )
    topology = config.unit_poles
    groups: list[tuple[str, Literal["unit", "pole", "hospital"], tuple[str, ...]]] = [
        (unit.unit_id, "unit", (unit.unit_id,)) for unit in config.units
    ]
    groups.extend(
        (pole.pole_id, "pole", tuple(unit.unit_id for unit in pole.units)) for pole in config.poles
    )
    groups.append((config.hospital_id, "hospital", tuple(unit.unit_id for unit in config.units)))
    latest: dict[str, Delivery] = {}
    versions: dict[tuple[str, int], str] = {}
    identities: dict[str, tuple[str, str, str, float]] = {}
    receipts: dict[str, str] = {}
    cursor = 0
    for hour in range(start_h, end):
        while cursor < len(ordered) and ordered[cursor].available_h <= hour:
            row = ordered[cursor]
            cursor += 1
            if row.hospital_id != config.hospital_id or topology.get(row.unit_id) != row.pole_id:
                raise ValueError("Delivery topology does not match hospital config")
            receipt = row.model_dump_json()
            if receipts.setdefault(row.delivery_id, receipt) != receipt:
                raise ValueError("Conflicting delivery ID")
            identity = (row.hospital_id, row.pole_id, row.unit_id, row.event_h)
            if identities.setdefault(row.event_id, identity) != identity:
                raise ValueError("Event identity changed across versions")
            key, content = (row.event_id, row.event_version), row.content_key()
            if versions.setdefault(key, content) != content:
                raise ValueError("Conflicting duplicate event version")
            previous = latest.get(row.unit_id)
            if previous is None or (row.event_h, row.event_id, row.event_version) > (
                previous.event_h,
                previous.event_id,
                previous.event_version,
            ):
                latest[row.unit_id] = row
        for entity, level, units in groups:
            known = [latest[unit] for unit in units if unit in latest]
            missing = len(known) != len(units)
            age = max((hour - row.event_h for row in known), default=None)
            values = None
            if not missing:
                values = ObservedState.model_validate(
                    {
                        field: sum(getattr(row.values, field) for row in known)
                        for field in ObservedState.model_fields
                    }
                )
            yield AsOfRow(
                sample_id=f"{run_id}:{entity}@{hour}",
                run_id=run_id,
                hospital_id=config.hospital_id,
                entity_id=entity,
                level=level,
                partition=config.partition,
                decision_h=hour,
                total_units=len(units),
                observed_units=len(known),
                missing=missing,
                stale_after_h=stale_after_h,
                stale=age is not None and age > stale_after_h,
                max_age_h=age,
                max_available_h=max((row.available_h for row in known), default=None),
                sources=tuple(
                    Source(
                        unit_id=row.unit_id,
                        event_id=row.event_id,
                        version=row.event_version,
                        event_h=row.event_h,
                        available_h=row.available_h,
                    )
                    for row in known
                ),
                values=values,
            )
