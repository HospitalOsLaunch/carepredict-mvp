"""Join available care documents onto independently reconciled patient rows."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Literal, Self

from pydantic import StrictBool, StrictInt, model_validator

from .config import FrozenConfig, HospitalConfig, Identifier
from .observations import Count, Hour
from .patient_asof import PatientRow, _check
from .patient_care import (
    SOURCES,
    CareDelivery,
    CarePayload,
    CareSource,
    DeparturePlan,
    Downstream,
    care_order,
)


class CareFact(FrozenConfig):
    event_id: str
    event_version: Count
    event_h: Hour
    available_h: Hour
    reporting_unit_id: Identifier
    source: CareSource
    age_h: Hour
    stale: StrictBool
    payload: CarePayload


class PatientCareRow(FrozenConfig):
    sample_id: str
    run_id: str
    hospital_id: Identifier
    stay_id: str
    partition: Literal["development", "train", "validation", "test"]
    decision_h: Count
    stale_after_h: Hour
    assessment: CareFact | None
    departure_plan: CareFact | None
    destination: CareFact | None
    downstream: CareFact | None
    downstream_request: CareFact | None
    home_help: CareFact | None
    assessment_missing: StrictBool
    departure_plan_missing: StrictBool
    planned_days_remaining: StrictInt | None
    plan_overdue: StrictBool | None
    plan_updates_known: Count
    destination_updates_known: Count
    corrected_events_known: Count
    voided_events_known: Count
    downstream_request_missing: StrictBool | None
    downstream_wait_h: Hour | None
    unmatched_downstream_events: Count

    @model_validator(mode="after")
    def contract(self) -> Self:
        if self.stale_after_h <= 0:
            raise ValueError("Invalid care staleness threshold")
        for field in (
            "assessment",
            "departure_plan",
            "destination",
            "downstream",
            "downstream_request",
            "home_help",
        ):
            fact: CareFact | None = getattr(self, field)
            if fact is None:
                continue
            kind = "downstream" if field == "downstream_request" else field
            if fact.payload.kind != kind or fact.source != SOURCES[kind]:
                raise ValueError("Care field provenance mismatch")
            if not fact.event_h <= fact.available_h <= self.decision_h or fact.event_version < 1:
                raise ValueError("Future care evidence")
            if fact.age_h != self.decision_h - fact.event_h or fact.stale != (
                fact.age_h > self.stale_after_h
            ):
                raise ValueError("Incorrect care information age")
        if self.assessment_missing != (self.assessment is None) or self.departure_plan_missing != (
            self.departure_plan is None
        ):
            raise ValueError("Incorrect missing care mask")
        plan = self.departure_plan.payload if self.departure_plan else None
        remaining = (
            plan.planned_day - self.decision_h // 24 if isinstance(plan, DeparturePlan) else None
        )
        if self.planned_days_remaining != remaining or self.plan_overdue != (
            remaining < 0 if remaining is not None else None
        ):
            raise ValueError("Planned date must remain a date, including overdue forecasts")
        value = self.downstream.payload if self.downstream else None
        missing = self.downstream_request is None if value is not None else None
        if missing != self.downstream_request_missing:
            raise ValueError("Incorrect downstream request mask")
        if self.downstream_request:
            request = self.downstream_request.payload
            if not isinstance(request, Downstream) or request.status != "requested":
                raise ValueError("Expected downstream request provenance")
            if not isinstance(value, Downstream) or value.request_id != request.request_id:
                raise ValueError("Cannot combine different downstream requests")
        wait = (
            self.decision_h - self.downstream_request.event_h
            if (
                self.downstream_request
                and isinstance(value, Downstream)
                and value.status == "requested"
            )
            else None
        )
        if self.downstream_wait_h != wait:
            raise ValueError("Unknown/cancelled/confirmed request cannot have a waiting duration")
        return self


def _selection(history: Iterable[CareDelivery]) -> tuple[dict[str, CareDelivery], dict[str, int]]:
    selected: dict[str, CareDelivery] = {}
    counts = dict.fromkeys(
        (
            "plan_updates_known",
            "destination_updates_known",
            "corrected_events_known",
            "voided_events_known",
            "unmatched_downstream_events",
        ),
        0,
    )
    plans = destinations = 0
    for row in sorted(history, key=lambda r: (r.event_h, r.event_order, r.event_id)):
        counts["corrected_events_known"] += row.event_version > 1
        counts["voided_events_known"] += row.voided
        if row.voided:
            continue
        p = row.payload
        plans += p.kind == "departure_plan"
        destinations += p.kind == "destination"
        if not isinstance(p, Downstream):
            selected[p.kind] = row
            continue
        if p.status == "requested":
            selected["downstream"] = selected["downstream_request"] = row
            continue
        request = selected.get("downstream_request")
        request_payload = request.payload if request else None
        matches = (
            isinstance(request_payload, Downstream) and p.request_id == request_payload.request_id
        )
        compatible = p.status == "cancelled" or (
            isinstance(request_payload, Downstream) and p.destination == request_payload.destination
        )
        if matches and compatible:
            selected["downstream"] = row
        else:
            counts["unmatched_downstream_events"] += 1
            # Preserve known request scope; an unrelated old confirmation cannot close it.
            if request is None:
                selected["downstream"] = row
    counts["plan_updates_known"] = max(0, plans - 1)
    counts["destination_updates_known"] = max(0, destinations - 1)
    return selected, counts


class CareAsOfCursor:
    def __init__(self, config: HospitalConfig, *, stale_after_h: float = 96.0):
        if not 0 < stale_after_h < float("inf"):
            raise ValueError("Invalid care staleness threshold")
        self.config, self.stale_after_h = config, stale_after_h
        self.hour = -1
        self.history: dict[str, dict[str, CareDelivery]] = {}
        self.selected: dict[str, tuple[dict[str, CareDelivery], dict[str, int]]] = {}
        self.receipts: dict[str, str] = {}
        self.versions: dict[tuple[str, int], str] = {}
        self.identities: dict[str, tuple[str | float | int, ...]] = {}

    def advance(self, hour: int, deliveries: Iterable[CareDelivery]) -> None:
        if type(hour) is not int or not max(0, self.hour) <= hour < self.config.days * 24:
            raise ValueError("Care cursor must move forward within recorded period")
        batch = sorted(
            (CareDelivery.model_validate_json(r.model_dump_json()) for r in deliveries),
            key=care_order,
        )
        receipts: dict[str, str] = {}
        versions: dict[tuple[str, int], str] = {}
        identities: dict[str, tuple[str | float | int, ...]] = {}
        for row in batch:
            if row.available_h > hour:
                raise ValueError("Cannot ingest future care delivery")
            if (
                row.hospital_id != self.config.hospital_id
                or self.config.unit_poles.get(row.unit_id) != row.pole_id
            ):
                raise ValueError("Care delivery topology mismatch")
            _check(self.receipts, receipts, row.delivery_id, row.model_dump_json())
            _check(self.versions, versions, (row.event_id, row.event_version), row.content_key())
            _check(self.identities, identities, row.event_id, row.identity)
        self.receipts.update(receipts)
        self.versions.update(versions)
        self.identities.update(identities)
        touched = set()
        for row in batch:
            history = self.history.setdefault(row.stay_id, {})
            previous = history.get(row.event_id)
            if previous is None or previous.event_version < row.event_version:
                history[row.event_id] = row
                touched.add(row.stay_id)
        for stay in touched:
            self.selected[stay] = _selection(self.history[stay].values())
        self.hour = hour

    def for_patient(self, row: PatientRow) -> PatientCareRow:
        if (
            row.decision_h != self.hour
            or row.hospital_id != self.config.hospital_id
            or row.partition != self.config.partition
        ):
            raise ValueError("Care join needs same hospital, partition and decision time")
        selected, counts = self.selected.get(row.stay_id, _selection(()))
        facts: dict[str, CareFact | None] = {}
        for key in (
            "assessment",
            "departure_plan",
            "destination",
            "downstream",
            "downstream_request",
            "home_help",
        ):
            value = selected.get(key)
            facts[key] = (
                CareFact(
                    event_id=value.event_id,
                    event_version=value.event_version,
                    event_h=value.event_h,
                    available_h=value.available_h,
                    reporting_unit_id=value.unit_id,
                    source=value.source,
                    age_h=self.hour - value.event_h,
                    stale=self.hour - value.event_h > self.stale_after_h,
                    payload=value.payload,
                )
                if value
                else None
            )
        plan = selected["departure_plan"].payload if "departure_plan" in selected else None
        remaining = plan.planned_day - self.hour // 24 if isinstance(plan, DeparturePlan) else None
        downstream = selected["downstream"].payload if "downstream" in selected else None
        request = selected.get("downstream_request")
        return PatientCareRow(
            sample_id=row.sample_id,
            run_id=row.run_id,
            hospital_id=row.hospital_id,
            stay_id=row.stay_id,
            partition=row.partition,
            decision_h=self.hour,
            stale_after_h=self.stale_after_h,
            assessment=facts["assessment"],
            departure_plan=facts["departure_plan"],
            destination=facts["destination"],
            downstream=facts["downstream"],
            downstream_request=facts["downstream_request"],
            home_help=facts["home_help"],
            plan_updates_known=counts["plan_updates_known"],
            destination_updates_known=counts["destination_updates_known"],
            corrected_events_known=counts["corrected_events_known"],
            voided_events_known=counts["voided_events_known"],
            unmatched_downstream_events=counts["unmatched_downstream_events"],
            assessment_missing=facts["assessment"] is None,
            departure_plan_missing=plan is None,
            planned_days_remaining=remaining,
            plan_overdue=remaining < 0 if remaining is not None else None,
            downstream_request_missing=request is None if downstream is not None else None,
            downstream_wait_h=self.hour - request.event_h
            if (request and isinstance(downstream, Downstream) and downstream.status == "requested")
            else None,
        )


def replay_care(
    patients: Iterable[PatientRow],
    deliveries: Iterable[CareDelivery],
    config: HospitalConfig,
    *,
    stale_after_h: float = 96.0,
) -> Iterator[PatientCareRow]:
    cursor = CareAsOfCursor(config, stale_after_h=stale_after_h)
    ordered = sorted(deliveries, key=care_order)
    index = 0
    for patient in patients:
        if patient.decision_h != cursor.hour:
            end = index
            while end < len(ordered) and ordered[end].available_h <= patient.decision_h:
                end += 1
            cursor.advance(patient.decision_h, ordered[index:end])
            index = end
        yield cursor.for_patient(patient)
