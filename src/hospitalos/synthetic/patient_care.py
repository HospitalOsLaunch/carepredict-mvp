"""Closed care-document observations, separate from physical presence and outcomes."""

from __future__ import annotations

import datetime as dt
import hashlib
import heapq
import json
import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Annotated, Any, Literal, Self

import numpy as np
from pydantic import Field, StrictBool, StrictInt, model_validator

from .config import FrozenConfig, HospitalConfig, Identifier
from .observation_profiles import SiteObservationStream
from .observations import Count, Hour
from .patient_observations import patient_profile

CARE_TYPES = frozenset(
    {
        "EVALUATION_CHARGE",
        "DATE_SORTIE_PREVISIONNELLE",
        "DESTINATION_DEMANDEE",
        "DEMANDE_AVAL",
        "DEMANDE_AVAL_ANNULEE",
        "PLACE_AVAL_CONFIRMEE",
        "AIDE_DOMICILE_DEMANDE",
        "AIDE_DOMICILE_ORGANISEE",
    }
)
Destination = Literal["domicile", "SMR", "EHPAD", "transfert"]
CareSource = Literal["DOSSIER_SOIN", "DPI_STAFF", "SERVICE_SOCIAL", "VIATRAJECTOIRE"]


class CareAssessment(FrozenConfig):
    kind: Literal["assessment"] = "assessment"
    minutes_per_24h: Annotated[float, Field(ge=0, strict=True, allow_inf_nan=False)]
    dependence: Annotated[StrictInt, Field(ge=1, le=4)]
    mobility: Literal["autonome", "aide", "brancard"]
    scale: Literal["synthetic_proxy_not_siips"] = "synthetic_proxy_not_siips"


class DeparturePlan(FrozenConfig):
    kind: Literal["departure_plan"] = "departure_plan"
    planned_day: StrictInt  # Relative to recording-year start; may exceed extraction.


class RequestedDestination(FrozenConfig):
    kind: Literal["destination"] = "destination"
    destination: Destination


class Downstream(FrozenConfig):
    kind: Literal["downstream"] = "downstream"
    status: Literal["requested", "cancelled", "confirmed"]
    destination: Literal["SMR", "EHPAD"] | None
    request_id: str | None

    @model_validator(mode="after")
    def contract(self) -> Self:
        if self.status != "cancelled" and self.destination is None:
            raise ValueError("Downstream request/confirmation needs destination")
        if self.status == "requested" and not self.request_id:
            raise ValueError("Downstream request needs its source identifier")
        return self


class HomeHelp(FrozenConfig):
    kind: Literal["home_help"] = "home_help"
    status: Literal["requested", "organized"]


CarePayload = Annotated[
    CareAssessment | DeparturePlan | RequestedDestination | Downstream | HomeHelp,
    Field(discriminator="kind"),
]
SOURCES: dict[str, CareSource] = {
    "assessment": "DOSSIER_SOIN",
    "departure_plan": "DPI_STAFF",
    "destination": "SERVICE_SOCIAL",
    "downstream": "VIATRAJECTOIRE",
    "home_help": "SERVICE_SOCIAL",
}


class CareDelivery(FrozenConfig):
    delivery_id: Annotated[str, Field(min_length=1)]
    event_id: Annotated[str, Field(min_length=1)]
    stay_id: Annotated[str, Field(min_length=1)]
    hospital_id: Identifier
    pole_id: Identifier
    unit_id: Identifier
    event_order: Count
    event_version: Annotated[StrictInt, Field(ge=1)] = 1
    replaces_version: Annotated[StrictInt, Field(ge=1)] | None = None
    source: CareSource
    event_h: Hour
    recorded_h: Hour
    ingested_h: Hour
    available_h: Hour
    voided: StrictBool = False
    payload: CarePayload
    synthetic: Literal[True] = True

    @model_validator(mode="after")
    def contract(self) -> Self:
        if not self.event_h <= self.recorded_h <= self.ingested_h <= self.available_h:
            raise ValueError("Require care event <= recorded <= ingested <= available")
        if self.replaces_version != (self.event_version - 1 if self.event_version > 1 else None):
            raise ValueError("Invalid care revision")
        if self.voided and self.event_version == 1:
            raise ValueError("Only a revision can void care evidence")
        if self.source != SOURCES[self.payload.kind]:
            raise ValueError("Care source disagrees with payload")
        if (
            isinstance(self.payload, Downstream)
            and self.payload.status == "requested"
            and self.payload.request_id != self.event_id
        ):
            raise ValueError("Request identity must match its source event")
        return self

    @property
    def identity(self) -> tuple[str | float | int, ...]:
        # A correction can change a value, not the workflow event or request linkage.
        link = self.payload.request_id or "" if isinstance(self.payload, Downstream) else ""
        status = self.payload.status if isinstance(self.payload, (Downstream, HomeHelp)) else ""
        return (
            self.hospital_id,
            self.pole_id,
            self.unit_id,
            self.stay_id,
            self.event_h,
            self.event_order,
            self.payload.kind,
            status,
            link,
        )

    def content_key(self) -> str:
        return self.model_dump_json(exclude={"delivery_id", "ingested_h", "available_h"})


def source_care(
    event: dict[str, Any],
    config: HospitalConfig,
    *,
    request_id: str | None = None,
) -> CareDelivery | None:
    if event["type"] not in CARE_TYPES:
        return None
    if (
        event["hospital_id"] != config.hospital_id
        or config.unit_poles.get(event["unit_id"]) != event["pole_id"]
    ):
        raise ValueError("Care source topology mismatch")
    hour = event["h"]
    match = re.fullmatch(re.escape(config.hospital_id) + r":E([0-9]+)", event["event_id"])
    if (
        type(hour) is not int
        or not -config.warmup_days * 24 <= hour < config.days * 24
        or match is None
        or not isinstance(event["stay_id"], str)
        or not event["stay_id"].startswith(config.hospital_id + ":S")
    ):
        raise ValueError("Invalid source care clock or identity")
    raw, kind = event["payload"], event["type"]
    payload: CareAssessment | DeparturePlan | RequestedDestination | Downstream | HomeHelp
    if kind == "EVALUATION_CHARGE":
        if raw.get("proxy_non_siips") is not True:
            raise ValueError("Care assessment must explicitly declare its proxy scale")
        payload = CareAssessment(
            minutes_per_24h=raw["minutes_soins_24h"],
            dependence=raw["dependance"],
            mobility=raw["mobilite"],
        )
    elif kind == "DATE_SORTIE_PREVISIONNELLE":
        payload = DeparturePlan(
            planned_day=(dt.date.fromisoformat(raw["date_prevue"]) - config.start).days
        )
    elif kind == "DESTINATION_DEMANDEE":
        payload = RequestedDestination(destination=raw["destination_demandee"])
    elif kind in ("DEMANDE_AVAL", "DEMANDE_AVAL_ANNULEE", "PLACE_AVAL_CONFIRMEE"):
        status: Literal["requested", "cancelled", "confirmed"] = (
            "requested"
            if kind == "DEMANDE_AVAL"
            else "cancelled"
            if kind == "DEMANDE_AVAL_ANNULEE"
            else "confirmed"
        )
        payload = Downstream(
            status=status,
            destination=raw.get("type_aval"),
            request_id=event["event_id"] if status == "requested" else request_id,
        )
    else:
        payload = HomeHelp(status="requested" if kind == "AIDE_DOMICILE_DEMANDE" else "organized")
    boundary = float(hour + 1)
    return CareDelivery(
        delivery_id=event["event_id"] + ":care_source",
        event_id=event["event_id"],
        stay_id=event["stay_id"],
        hospital_id=config.hospital_id,
        pole_id=event["pole_id"],
        unit_id=event["unit_id"],
        event_order=int(match[1]),
        source=SOURCES[payload.kind],
        event_h=boundary,
        recorded_h=boundary,
        ingested_h=boundary,
        available_h=boundary,
        payload=payload,
    )


def care_order(row: CareDelivery) -> tuple[float, str, int, str]:
    return row.available_h, row.event_id, row.event_version, row.delivery_id


class OnlineCare:
    """Synthetic source workflow IDs are assigned before any message can be lost."""

    def __init__(self, config: HospitalConfig):
        self.config, self.profile = config, patient_profile(config)
        self.outages = SiteObservationStream(config)
        self.offset = config.warmup_days * 24
        self.next_hour = -self.offset
        self.boundary = self.next_hour
        self.pending: list[tuple[tuple[float, str, int, str], CareDelivery]] = []
        self.seen: set[str] = set()
        self.requests: dict[str, tuple[str, str]] = {}

    def _observe(self, base: CareDelivery) -> list[CareDelivery]:
        key = json.dumps([self.config.seed, base.stay_id, base.event_order, "care_receipts_v1"])
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
        observed = base.payload
        if isinstance(observed, CareAssessment):
            observed = observed.model_copy(
                update={
                    "minutes_per_24h": round(
                        observed.minutes_per_24h * float(rng.lognormal(0, p.charge_noise_sigma)),
                        1,
                    )
                }
            )
        revised = (
            isinstance(observed, (CareAssessment, DeparturePlan))
            and rng.random() < p.revision_probability
        )
        initial = observed
        if revised:
            if isinstance(observed, CareAssessment):
                initial = observed.model_copy(
                    update={"minutes_per_24h": round(observed.minutes_per_24h * 1.2, 1)}
                )
            elif isinstance(observed, DeparturePlan):
                initial = observed.model_copy(update={"planned_day": observed.planned_day + 1})
        first = {
            **base.model_dump(),
            "payload": initial.model_dump(),
            "recorded_h": recorded,
            "ingested_h": ingested,
        }
        rows = [first]
        if revised:
            correction = recorded + float(
                rng.uniform(p.revision_delay_min_h, p.revision_delay_max_h)
            )
            rows.append(
                {
                    **first,
                    "payload": observed.model_dump(),
                    "event_version": 2,
                    "replaces_version": 1,
                    "recorded_h": correction,
                    "ingested_h": correction + 1 / 60,
                }
            )
        if rng.random() < p.duplicate_probability:
            rows.append({**first, "ingested_h": ingested + 2 / 60})
        result = []
        for index, row in enumerate(rows):
            row["delivery_id"] = f"{base.event_id}:care_receipt{index}"
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
            result.append(CareDelivery.model_validate(row))
        return result

    def push(self, hour: int, events: Iterable[dict[str, Any]]) -> None:
        batch = tuple(events)
        ids = [e["event_id"] for e in batch]
        if (
            type(hour) is not int
            or hour != self.next_hour
            or hour >= self.config.days * 24
            or any(e["h"] != hour for e in batch)
            or len(set(ids)) != len(ids)
            or self.seen.intersection(ids)
        ):
            raise ValueError("Invalid next hourly care source batch")
        # Validate all source messages before modifying the source workflow.
        projected = [r for e in batch if (r := source_care(e, self.config)) is not None]
        for base in sorted(projected, key=lambda r: r.event_order):
            p = base.payload
            if isinstance(p, Downstream):
                if p.status == "requested":
                    self.requests[base.stay_id] = base.event_id, str(p.destination)
                else:
                    previous = self.requests.get(base.stay_id)
                    link = (
                        previous[0]
                        if previous and (p.status == "cancelled" or previous[1] == p.destination)
                        else None
                    )
                    base = base.model_copy(
                        update={"payload": p.model_copy(update={"request_id": link})}
                    )
                    if link is not None and p.status == "cancelled":
                        self.requests.pop(base.stay_id, None)
            for row in self._observe(base):
                heapq.heappush(self.pending, (care_order(row), row))
        self.seen.update(ids)
        self.next_hour += 1

    def receive(self, hour: int) -> tuple[CareDelivery, ...]:
        if type(hour) is not int or not self.boundary <= hour <= self.next_hour:
            raise ValueError("Cannot receive beyond simulated care boundary")
        self.boundary = hour
        rows = []
        while self.pending and self.pending[0][0][0] <= hour:
            rows.append(heapq.heappop(self.pending)[1])
        return tuple(rows)


def observe_care(events: Iterable[dict[str, Any]], config: HospitalConfig) -> list[CareDelivery]:
    batches: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        hour = event["h"]
        if type(hour) is not int or not -config.warmup_days * 24 <= hour < config.days * 24:
            raise ValueError("Care source outside simulation period")
        batches[hour].append(event)
    online = OnlineCare(config)
    rows: list[CareDelivery] = []
    for hour in range(-config.warmup_days * 24, config.days * 24):
        online.push(hour, batches.pop(hour, []))
        rows.extend(online.receive(hour + 1))
    return sorted(rows, key=care_order)
