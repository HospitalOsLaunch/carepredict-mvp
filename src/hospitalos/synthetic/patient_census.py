"""Observed unit censuses: explicit coverage, delayed versions, no discharge inference."""

from __future__ import annotations

import hashlib
import heapq
import json
from collections import defaultdict
from collections.abc import Iterable
from typing import Annotated, Any, Literal, Self

import numpy as np
from pydantic import Field, StrictBool, StrictInt, model_validator

from .config import FrozenConfig, HospitalConfig, Identifier, Probability
from .observation_profiles import SiteObservationStream
from .observations import Count, Hour
from .patient_observations import (
    Admission,
    Departure,
    NotAdmitted,
    Transfer,
    patient_profile,
    source_movement,
)


class CensusProfile(FrozenConfig):
    interval_h: Annotated[StrictInt, Field(ge=1, le=168)] = 24
    partial_probability: Probability = 0.15
    partial_retention_probability: Probability = 0.8


class CensusMember(FrozenConfig):
    stay_id: str
    bed_id: Count


class CensusDelivery(FrozenConfig):
    delivery_id: str
    event_id: str
    event_version: Annotated[StrictInt, Field(ge=1)] = 1
    replaces_version: Annotated[StrictInt, Field(ge=1)] | None = None
    hospital_id: Identifier
    pole_id: Identifier
    unit_id: Identifier
    source: Literal["RECENSEMENT_UNITE"] = "RECENSEMENT_UNITE"
    event_h: Hour
    recorded_h: Hour
    ingested_h: Hour
    available_h: Hour
    complete: StrictBool
    members: tuple[CensusMember, ...]
    voided: StrictBool = False
    synthetic: Literal[True] = True

    @model_validator(mode="after")
    def contract(self) -> Self:
        if not self.event_h <= self.recorded_h <= self.ingested_h <= self.available_h:
            raise ValueError("Require census event <= recorded <= ingested <= available")
        expected = self.event_version - 1 if self.event_version > 1 else None
        if self.replaces_version != expected or (self.voided and self.event_version == 1):
            raise ValueError("Invalid census revision")
        if len({m.stay_id for m in self.members}) != len(self.members):
            raise ValueError("Duplicate census stay")
        if len({m.bed_id for m in self.members}) != len(self.members):
            raise ValueError("Duplicate census bed")
        return self

    def content_key(self) -> str:
        return self.model_dump_json(exclude={"delivery_id", "ingested_h", "available_h"})

    @property
    def identity(self) -> tuple[str | float, ...]:
        return self.hospital_id, self.pole_id, self.unit_id, self.event_h


def census_order(row: CensusDelivery) -> tuple[float, str, int, str]:
    return row.available_h, row.event_id, row.event_version, row.delivery_id


class OnlineCensus:
    """Synthetic observer fed only the current hourly physical movement batch.

    This generator may see present occupancy; the consumer sees only its deliveries.
    It never reads final stay records, medical readiness or future movement batches.
    """

    def __init__(self, config: HospitalConfig, profile: CensusProfile | None = None):
        self.config, self.profile = config, profile or CensusProfile()
        self.observation = patient_profile(config)
        self.outages = SiteObservationStream(config)
        self.offset = config.warmup_days * 24
        self.next_hour = -self.offset
        self.boundary = self.next_hour
        self.present: dict[str, tuple[str, int]] = {}
        self.seen: set[str] = set()
        self.pending: list[tuple[tuple[float, str, int, str], CensusDelivery]] = []

    def _snapshot(self, hour: int, unit: str) -> list[CensusDelivery]:
        key = json.dumps([self.config.seed, self.config.hospital_id, unit, hour, "census_v1"])
        rng = np.random.Generator(
            np.random.PCG64(int.from_bytes(hashlib.sha256(key.encode()).digest()[:16], "big"))
        )
        p = self.observation
        if rng.random() < p.missing_probability:
            return []
        members = tuple(
            CensusMember(stay_id=s, bed_id=b)
            for s, (u, b) in sorted(self.present.items())
            if u == unit
        )
        revised = rng.random() < p.revision_probability
        partial = revised or rng.random() < self.profile.partial_probability
        initial = (
            tuple(m for m in members if rng.random() < self.profile.partial_retention_probability)
            if partial
            else members
        )
        median = p.recording_delay_median_minutes
        lag = float(rng.lognormal(np.log(median), p.recording_delay_sigma)) / 60 if median else 0.0
        recorded = hour + lag
        ingested = (
            recorded
            + float(rng.uniform(p.ingestion_delay_min_minutes, p.ingestion_delay_max_minutes)) / 60
        )
        base: dict[str, Any] = {
            "event_id": f"{self.config.hospital_id}:C:{unit}:{hour}",
            "hospital_id": self.config.hospital_id,
            "pole_id": self.config.unit_poles[unit],
            "unit_id": unit,
            "event_h": float(hour),
            "recorded_h": recorded,
            "ingested_h": ingested,
            "complete": not partial,
            "members": initial,
        }
        rows: list[dict[str, Any]] = [base]
        if revised:
            correction = recorded + float(
                rng.uniform(p.revision_delay_min_h, p.revision_delay_max_h)
            )
            rows.append(
                dict(
                    base,
                    event_version=2,
                    replaces_version=1,
                    complete=True,
                    members=members,
                    recorded_h=correction,
                    ingested_h=correction + 1 / 60,
                )
            )
        if rng.random() < p.duplicate_probability:
            rows.append(dict(base, ingested_h=ingested + 2 / 60))
        result = []
        for index, row in enumerate(rows):
            row = dict(row)
            row["delivery_id"] = f"{base['event_id']}:receipt{index}"
            row["ingested_h"] = (
                self.outages.release(row["ingested_h"] + self.offset, unit) - self.offset
            )
            row["available_h"] = (
                self.outages.release(
                    row["ingested_h"] + self.offset + p.availability_delay_minutes / 60, unit
                )
                - self.offset
            )
            result.append(CensusDelivery.model_validate(row))
        return result

    def push(self, hour: int, events: Iterable[dict[str, Any]]) -> None:
        batch = tuple(events)
        if type(hour) is not int or hour != self.next_hour or hour >= self.config.days * 24:
            raise ValueError("Expected next source census hour")
        ids = [e["event_id"] for e in batch]
        if (
            any(e["h"] != hour for e in batch)
            or len(set(ids)) != len(ids)
            or self.seen.intersection(ids)
        ):
            raise ValueError("Invalid hourly census source batch")
        movements = [r for e in batch if (r := source_movement(e, self.config)) is not None]
        for row in sorted(movements, key=lambda r: r.event_order):
            if isinstance(row.payload, (Admission, Transfer)):
                self.present[row.stay_id] = row.unit_id, row.payload.bed_id
            elif isinstance(row.payload, (Departure, NotAdmitted)):
                self.present.pop(row.stay_id, None)
        self.seen.update(ids)
        self.next_hour += 1
        if self.next_hour % self.profile.interval_h == 0:
            for unit in self.config.unit_poles:
                for receipt in self._snapshot(self.next_hour, unit):
                    heapq.heappush(self.pending, (census_order(receipt), receipt))

    def receive(self, hour: int) -> tuple[CensusDelivery, ...]:
        if type(hour) is not int or not self.boundary <= hour <= self.next_hour:
            raise ValueError("Cannot receive beyond simulated census boundary")
        self.boundary = hour
        rows = []
        while self.pending and self.pending[0][0][0] <= hour:
            rows.append(heapq.heappop(self.pending)[1])
        return tuple(rows)


def observe_censuses(
    events: Iterable[dict[str, Any]],
    config: HospitalConfig,
    profile: CensusProfile | None = None,
) -> list[CensusDelivery]:
    batches: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        hour = event["h"]
        if type(hour) is not int or not -config.warmup_days * 24 <= hour < config.days * 24:
            raise ValueError("Census source outside simulation interval")
        batches[hour].append(event)
    online = OnlineCensus(config, profile)
    rows: list[CensusDelivery] = []
    for hour in range(-config.warmup_days * 24, config.days * 24):
        online.push(hour, batches.pop(hour, []))
        rows.extend(online.receive(hour + 1))
    return sorted(rows, key=census_order)
