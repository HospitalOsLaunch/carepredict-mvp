"""Closed movement contract; patient receipts use a separate, event-local noise stream."""

from __future__ import annotations

import hashlib
import heapq
import json
import re
from collections.abc import Iterable
from typing import Annotated, Any, Literal, Self

import numpy as np
from pydantic import Field, StrictBool, StrictInt, model_validator

from .config import FrozenConfig, HospitalConfig, Identifier, ObservationProfile
from .observation_profiles import SiteObservationStream
from .observations import Count, Hour

PATIENT_TYPES = frozenset(
    {
        "DEMANDE_ADMISSION",
        "ADMISSION",
        "TRANSFERT_INTERNE",
        "SORTIE",
        "ORIENTATION_HORS_PERIMETRE",
        "DEPROGRAMMATION",
        "TRANSFERT_REFUSE",
    }
)
AgeBand = Literal["under_65", "65_74", "75_84", "85_plus"]


class Request(FrozenConfig):
    kind: Literal["request"] = "request"
    admission_mode: Literal["urgences", "programme", "transfert_entrant"]
    age_band: AgeBand
    isolation: StrictBool
    oxygen: StrictBool


class Admission(FrozenConfig):
    kind: Literal["admission"] = "admission"
    home_unit_id: Identifier
    bed_id: Count


class Transfer(FrozenConfig):
    kind: Literal["transfer"] = "transfer"
    from_unit_id: Identifier
    from_bed_id: Count
    bed_id: Count


class Departure(FrozenConfig):
    kind: Literal["departure"] = "departure"
    destination: Literal["domicile", "SMR", "EHPAD", "deces", "transfert"]


class NotAdmitted(FrozenConfig):
    kind: Literal["not_admitted"] = "not_admitted"
    reason: Literal["ORIENTATION_HORS_PERIMETRE", "DEPROGRAMMATION", "TRANSFERT_REFUSE"]


PatientPayload = Annotated[
    Request | Admission | Transfer | Departure | NotAdmitted, Field(discriminator="kind")
]


class PatientDelivery(FrozenConfig):
    delivery_id: Annotated[str, Field(min_length=1)]
    event_id: Annotated[str, Field(min_length=1)]
    stay_id: Annotated[str, Field(min_length=1)]
    hospital_id: Identifier
    pole_id: Identifier
    unit_id: Identifier  # Reporting unit; immutable across revisions.
    event_order: Count
    event_version: Annotated[StrictInt, Field(ge=1)]
    source: Literal["DPI_MOUVEMENTS"] = "DPI_MOUVEMENTS"
    event_h: Hour
    recorded_h: Hour
    ingested_h: Hour
    available_h: Hour
    replaces_version: Annotated[StrictInt, Field(ge=1)] | None = None
    voided: StrictBool = False
    payload: PatientPayload
    synthetic: Literal[True] = True

    @model_validator(mode="after")
    def ordered_clocks(self) -> Self:
        if not self.event_h <= self.recorded_h <= self.ingested_h <= self.available_h:
            raise ValueError("Require event <= recorded <= ingested <= available")
        if self.replaces_version != (self.event_version - 1 if self.event_version > 1 else None):
            raise ValueError("Incorrect replaced version")
        if self.voided and self.event_version == 1:
            raise ValueError("Only a revision can void a source event")
        return self

    def content_key(self) -> str:
        return self.model_dump_json(exclude={"delivery_id", "ingested_h", "available_h"})

    @property
    def identity(self) -> tuple[str | float | int, ...]:
        return (
            self.hospital_id,
            self.pole_id,
            self.unit_id,
            self.stay_id,
            self.event_h,
            self.event_order,
            self.payload.kind,
        )


def patient_profile(config: HospitalConfig) -> ObservationProfile:
    """v041 snapshots stay untouched; the NEW movement adapter has an explicit default."""
    if config.observation.mode == "v041":
        return ObservationProfile(mode="site_v1", recording_delay_median_minutes=25.0)
    return config.observation


def source_movement(event: dict[str, Any], config: HospitalConfig) -> PatientDelivery | None:
    """Project only recorded movement fields, never latent patient arrays or stay outcomes."""
    if event["type"] not in PATIENT_TYPES:
        return None
    unit = event["unit_id"]
    if (
        event["hospital_id"] != config.hospital_id
        or config.unit_poles.get(unit) != event["pole_id"]
    ):
        raise ValueError("Patient event topology mismatch")
    hour = event["h"]
    if type(hour) is not int or not -config.warmup_days * 24 <= hour < config.days * 24:
        raise ValueError("Patient event outside the simulation interval")
    match = re.fullmatch(re.escape(config.hospital_id) + r":E([0-9]+)", event["event_id"])
    if (
        match is None
        or not isinstance(event["stay_id"], str)
        or not event["stay_id"].startswith(config.hospital_id + ":S")
    ):
        raise ValueError("Expected hospital-scoped truth event and stay IDs")
    raw = event["payload"]
    kind = event["type"]
    payload: Request | Admission | Transfer | Departure | NotAdmitted
    if kind == "DEMANDE_ADMISSION":
        age = raw["age"]
        if type(age) is not int or not 0 <= age <= 120:
            raise ValueError("Invalid source age")
        band: AgeBand = (
            "under_65" if age < 65 else "65_74" if age < 75 else "75_84" if age < 85 else "85_plus"
        )
        payload = Request(
            admission_mode=raw["mode_entree"],
            age_band=band,
            isolation=raw["isolement"],
            oxygen=raw["oxygene"],
        )
    elif kind == "ADMISSION":
        target = raw["unite_cible"]
        if type(target) is not int or not 0 <= target < len(config.units):
            raise ValueError("Unknown home unit index")
        payload = Admission(home_unit_id=config.units[target].unit_id, bed_id=raw["lit"])
    elif kind == "TRANSFERT_INTERNE":
        payload = Transfer(
            from_unit_id=raw["depuis"], from_bed_id=raw["lit_origine"], bed_id=raw["lit"]
        )
        if payload.from_unit_id not in config.unit_poles:
            raise ValueError("Unknown transfer origin")
    elif kind == "SORTIE":
        payload = Departure(destination=raw["destination"])
    else:
        payload = NotAdmitted(reason=kind)
    # All events emitted during [h,h+1) become facts at its end, like unit snapshots.
    boundary = float(hour + 1)
    return PatientDelivery(
        delivery_id=event["event_id"] + ":truth",
        event_id=event["event_id"],
        stay_id=event["stay_id"],
        hospital_id=config.hospital_id,
        pole_id=event["pole_id"],
        unit_id=unit,
        event_order=int(match[1]),
        event_version=1,
        event_h=boundary,
        recorded_h=boundary,
        ingested_h=boundary,
        available_h=boundary,
        payload=payload,
    )


class PatientObservationStream:
    def __init__(self, config: HospitalConfig):
        self.config, self.profile = config, patient_profile(config)
        self.offset = config.warmup_days * 24
        self.outages = SiteObservationStream(config)

    def observe(self, event: dict[str, Any]) -> list[PatientDelivery]:
        base = source_movement(event, self.config)
        if base is None:
            return []
        key = json.dumps([self.config.seed, base.stay_id, base.event_order, "patient_receipts_v1"])
        rng = np.random.Generator(
            np.random.PCG64(int.from_bytes(hashlib.sha256(key.encode()).digest()[:16], "big"))
        )
        p = self.profile
        if rng.random() < p.missing_probability:
            return []
        median = p.recording_delay_median_minutes
        lag = float(rng.lognormal(np.log(median), p.recording_delay_sigma)) / 60 if median else 0.0
        recorded = base.event_h + lag
        ingested = (
            recorded
            + float(rng.uniform(p.ingestion_delay_min_minutes, p.ingestion_delay_max_minutes)) / 60
        )
        payload = base.payload
        revised = (
            isinstance(payload, (Admission, Transfer)) and rng.random() < p.revision_probability
        )
        initial = (
            payload.model_copy(update={"bed_id": payload.bed_id + 1})
            if revised and isinstance(payload, (Admission, Transfer))
            else payload
        )
        rows = [
            {
                **base.model_dump(),
                "payload": initial.model_dump(),
                "recorded_h": recorded,
                "ingested_h": ingested,
            }
        ]
        if revised:
            revision_h = recorded + float(
                rng.uniform(p.revision_delay_min_h, p.revision_delay_max_h)
            )
            rows.append(
                {
                    **rows[0],
                    "payload": payload.model_dump(),
                    "event_version": 2,
                    "replaces_version": 1,
                    "recorded_h": revision_h,
                    "ingested_h": revision_h + 1 / 60,
                }
            )
        if rng.random() < p.duplicate_probability:
            rows.append({**rows[0], "ingested_h": ingested + 2 / 60})
        result = []
        for index, row in enumerate(rows):
            row["delivery_id"] = f"{base.event_id}:patient_receipt{index}"
            row["ingested_h"] = (
                self.outages.release(row["ingested_h"] + self.offset, base.unit_id) - self.offset
            )
            row["available_h"] = (
                self.outages.release(
                    row["ingested_h"] + self.offset + p.availability_delay_minutes / 60,
                    base.unit_id,
                )
                - self.offset
            )
            result.append(PatientDelivery.model_validate(row))
        return result


def delivery_order(row: PatientDelivery) -> tuple[float, str, int, str]:
    return row.available_h, row.event_id, row.event_version, row.delivery_id


def observe_patients(
    events: Iterable[dict[str, Any]], config: HospitalConfig
) -> list[PatientDelivery]:
    stream = PatientObservationStream(config)
    rows: list[PatientDelivery] = []
    seen = set()
    for event in events:
        if event["event_id"] in seen:
            raise ValueError("Duplicate truth event ID")
        seen.add(event["event_id"])
        rows.extend(r for r in stream.observe(event) if r.available_h <= config.days * 24)
    return sorted(rows, key=delivery_order)


class OnlinePatients:
    """Feed a complete chronological source batch per hour, including empty batches."""

    def __init__(self, config: HospitalConfig):
        self.adapter = PatientObservationStream(config)
        self.next_hour = -config.warmup_days * 24
        self.boundary = self.next_hour
        self.pending: list[tuple[tuple[float, str, int, str], PatientDelivery]] = []
        self.seen: set[str] = set()

    def push(self, hour: int, events: Iterable[dict[str, Any]]) -> None:
        batch = tuple(events)
        if type(hour) is not int or hour != self.next_hour or hour >= self.adapter.config.days * 24:
            raise ValueError("Expected next source hour within simulation")
        ids = [e["event_id"] for e in batch]
        if (
            any(e["h"] != hour for e in batch)
            or len(set(ids)) != len(ids)
            or self.seen.intersection(ids)
        ):
            raise ValueError("Invalid hourly patient batch")
        receipts = [r for e in batch for r in self.adapter.observe(e)]
        self.seen.update(ids)
        self.next_hour += 1
        for row in receipts:
            heapq.heappush(self.pending, (delivery_order(row), row))

    def receive(self, hour: int) -> tuple[PatientDelivery, ...]:
        if type(hour) is not int or not self.boundary <= hour <= self.next_hour:
            raise ValueError("Cannot receive before or beyond simulated patient boundary")
        self.boundary = hour
        result = []
        while self.pending and self.pending[0][0][0] <= hour:
            result.append(heapq.heappop(self.pending)[1])
        return tuple(result)
