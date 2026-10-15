"""Patient movements as known: revisions replace facts; retries do not create movements."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from typing import Any, Literal, Self, TypeVar

from pydantic import StrictBool, model_validator

from .config import FrozenConfig, HospitalConfig, Identifier
from .observations import Count, Hour
from .patient_observations import (
    Admission,
    AgeBand,
    Departure,
    NotAdmitted,
    PatientDelivery,
    Request,
    Transfer,
    delivery_order,
)


class PatientSource(FrozenConfig):
    event_id: str
    version: Count
    event_h: Hour
    available_h: Hour
    voided: StrictBool


class PatientRow(FrozenConfig):
    sample_id: str
    run_id: str
    hospital_id: Identifier
    stay_id: str
    partition: Literal["development", "train", "validation", "test"]
    decision_h: Count
    status: Literal["awaiting_admission", "admitted"]
    home_unit_id: Identifier | None
    current_unit_id: Identifier | None
    current_pole_id: Identifier | None
    bed_id: Count | None
    bed_conflict: StrictBool
    age_band: AgeBand | None
    admission_mode: Literal["urgences", "programme", "transfert_entrant"] | None
    isolation: StrictBool | None
    oxygen: StrictBool | None
    requested_h: Hour | None
    admission_h: Hour | None
    elapsed_stay_h: Hour | None
    admission_missing: StrictBool
    request_missing: StrictBool
    internal_movements: Count
    last_event_h: Hour
    last_information_age_h: Hour
    stale_after_h: Hour
    stale: StrictBool
    sources: tuple[PatientSource, ...]

    @model_validator(mode="after")
    def temporal_contract(self) -> Self:
        if not self.sources or len({s.event_id for s in self.sources}) != len(self.sources):
            raise ValueError("Patient row needs unique event provenance")
        if any(
            s.version < 1 or not s.event_h <= s.available_h <= self.decision_h for s in self.sources
        ):
            raise ValueError("Patient provenance is in the future")
        active = [s.event_h for s in self.sources if not s.voided]
        if not active or self.last_event_h != max(active):
            raise ValueError("Wrong patient event age")
        if self.last_information_age_h != self.decision_h - self.last_event_h:
            raise ValueError("Wrong patient information age")
        if self.stale_after_h <= 0 or self.stale != (
            self.last_information_age_h > self.stale_after_h
        ):
            raise ValueError("Wrong patient stale mask")
        if self.admission_missing != (self.admission_h is None) or self.request_missing != (
            self.requested_h is None
        ):
            raise ValueError("Wrong patient missingness mask")
        if any(h is not None and h > self.decision_h for h in (self.requested_h, self.admission_h)):
            raise ValueError("Future patient movement")
        elapsed = None if self.admission_h is None else self.decision_h - self.admission_h
        if elapsed != self.elapsed_stay_h:
            raise ValueError("Elapsed stay must come from observed admission")
        located = (
            self.current_unit_id is not None
            and self.current_pole_id is not None
            and self.bed_id is not None
        )
        if self.status == "admitted" and not located:
            raise ValueError("Admitted patient needs observed location")
        if self.status == "awaiting_admission" and any(
            v is not None
            for v in (self.current_unit_id, self.current_pole_id, self.bed_id, self.admission_h)
        ):
            raise ValueError("Waiting patient cannot have an occupied bed")
        if self.bed_conflict and not located:
            raise ValueError("Bed conflict needs a location")
        return self


def _state(events: Iterable[PatientDelivery], config: HospitalConfig) -> dict[str, Any] | None:
    ordered = sorted(events, key=lambda r: (r.event_h, r.event_order, r.event_id))
    state: dict[str, Any] = {
        "status": None,
        "home_unit_id": None,
        "current_unit_id": None,
        "current_pole_id": None,
        "bed_id": None,
        "age_band": None,
        "admission_mode": None,
        "isolation": None,
        "oxygen": None,
        "requested_h": None,
        "admission_h": None,
        "internal_movements": 0,
    }
    for row in ordered:
        if row.voided:
            continue
        p = row.payload
        if isinstance(p, Request):
            state.update(
                home_unit_id=row.unit_id,
                requested_h=row.event_h,
                age_band=p.age_band,
                admission_mode=p.admission_mode,
                isolation=p.isolation,
                oxygen=p.oxygen,
            )
            if state["status"] is None:
                state["status"] = "awaiting_admission"
        elif isinstance(p, (Admission, Transfer)):
            state.update(
                status="admitted",
                current_unit_id=row.unit_id,
                current_pole_id=config.unit_poles[row.unit_id],
                bed_id=p.bed_id,
            )
            if isinstance(p, Admission):
                state.update(admission_h=row.event_h, home_unit_id=p.home_unit_id)
            else:
                state["internal_movements"] += 1
        elif isinstance(p, (Departure, NotAdmitted)):
            state["status"] = "closed"
    if state["status"] in (None, "closed"):
        return None
    state["sources"] = tuple(
        PatientSource(
            event_id=r.event_id,
            version=r.event_version,
            event_h=r.event_h,
            available_h=r.available_h,
            voided=r.voided,
        )
        for r in ordered
    )
    state["last_event_h"] = max(r.event_h for r in ordered if not r.voided)
    return state


K = TypeVar("K")
V = TypeVar("V")


def _check(existing: dict[K, V], pending: dict[K, V], key: K, value: V) -> None:
    if existing.get(key, value) != value or pending.setdefault(key, value) != value:
        raise ValueError("Conflicting patient receipt, version or identity")


class PatientAsOfCursor:
    def __init__(self, config: HospitalConfig, *, run_id: str, stale_after_h: float = 96.0):
        if not 0 < stale_after_h < float("inf"):
            raise ValueError("Invalid patient staleness threshold")
        self.config, self.run_id, self.stale_after_h = config, run_id, stale_after_h
        self.hour = -1
        self.history: dict[str, dict[str, PatientDelivery]] = {}
        self.active: dict[str, dict[str, Any]] = {}
        self.receipts: dict[str, str] = {}
        self.versions: dict[tuple[str, int], str] = {}
        self.identities: dict[str, tuple[str | float | int, ...]] = {}

    def advance(self, hour: int, deliveries: Iterable[PatientDelivery]) -> tuple[PatientRow, ...]:
        if type(hour) is not int or not max(0, self.hour) <= hour < self.config.days * 24:
            raise ValueError("Patient cursor must move forward inside recorded period")
        # Validate the whole batch before changing any state, including constructed objects.
        batch = sorted(
            (PatientDelivery.model_validate_json(r.model_dump_json()) for r in deliveries),
            key=delivery_order,
        )
        receipts: dict[str, str] = {}
        versions: dict[tuple[str, int], str] = {}
        identities: dict[str, tuple[str | float | int, ...]] = {}
        for row in batch:
            if row.available_h > hour:
                raise ValueError("Cannot ingest a future patient delivery")
            if (
                row.hospital_id != self.config.hospital_id
                or self.config.unit_poles.get(row.unit_id) != row.pole_id
            ):
                raise ValueError("Patient delivery topology mismatch")
            if (
                isinstance(row.payload, Admission)
                and row.payload.home_unit_id not in self.config.unit_poles
            ):
                raise ValueError("Unknown patient home unit")
            if (
                isinstance(row.payload, Transfer)
                and row.payload.from_unit_id not in self.config.unit_poles
            ):
                raise ValueError("Unknown patient transfer origin")
            receipt, key, content = (
                row.model_dump_json(),
                (row.event_id, row.event_version),
                row.content_key(),
            )
            _check(self.receipts, receipts, row.delivery_id, receipt)
            _check(self.versions, versions, key, content)
            _check(self.identities, identities, row.event_id, row.identity)
        self.receipts.update(receipts)
        self.versions.update(versions)
        self.identities.update(identities)
        touched = set()
        for row in batch:
            history = self.history.setdefault(row.stay_id, {})
            previous = history.get(row.event_id)
            if previous is None or row.event_version > previous.event_version:
                history[row.event_id] = row
                touched.add(row.stay_id)
        for stay in touched:
            state = _state(self.history[stay].values(), self.config)
            if state is None:
                self.active.pop(stay, None)
            else:
                self.active[stay] = state
        self.hour = hour
        occupied = Counter(
            (s["current_unit_id"], s["bed_id"])
            for s in self.active.values()
            if s["status"] == "admitted"
        )
        result = []
        for stay, state in sorted(self.active.items()):
            age = hour - state["last_event_h"]
            admitted = state["admission_h"]
            result.append(
                PatientRow(
                    sample_id=f"{self.run_id}:{stay}@{hour}",
                    run_id=self.run_id,
                    hospital_id=self.config.hospital_id,
                    stay_id=stay,
                    partition=self.config.partition,
                    decision_h=hour,
                    **state,
                    bed_conflict=state["status"] == "admitted"
                    and occupied[state["current_unit_id"], state["bed_id"]] > 1,
                    elapsed_stay_h=None if admitted is None else hour - admitted,
                    admission_missing=admitted is None,
                    request_missing=state["requested_h"] is None,
                    last_information_age_h=age,
                    stale_after_h=self.stale_after_h,
                    stale=age > self.stale_after_h,
                )
            )
        return tuple(result)


def replay_patients(
    deliveries: Iterable[PatientDelivery],
    config: HospitalConfig,
    *,
    run_id: str,
    stale_after_h: float = 96.0,
) -> Iterator[PatientRow]:
    ordered = sorted(deliveries, key=delivery_order)
    cursor = PatientAsOfCursor(config, run_id=run_id, stale_after_h=stale_after_h)
    index = 0
    for hour in range(config.days * 24):
        end = index
        while end < len(ordered) and ordered[end].available_h <= hour:
            end += 1
        yield from cursor.advance(hour, ordered[index:end])
        index = end
