"""Patient movements as known: revisions replace facts; retries do not create movements."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from typing import Any, Literal, Self, TypeVar

from pydantic import StrictBool, model_validator

from .config import FrozenConfig, HospitalConfig, Identifier
from .observations import Count, Hour
from .patient_census import CensusDelivery, CensusMember, census_order
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
    source: Literal["DPI_MOUVEMENTS", "RECENSEMENT_UNITE"] = "DPI_MOUVEMENTS"
    complete: StrictBool | None = None

    @model_validator(mode="after")
    def coverage(self) -> Self:
        if (self.source == "RECENSEMENT_UNITE") != (self.complete is not None):
            raise ValueError("Only census provenance carries explicit coverage")
        return self


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
    presence_basis: Literal["movement", "census"] = "movement"
    observation_conflict: StrictBool = False

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


class PatientReconciliation(FrozenConfig):
    """Change journal, including unresolved unit absences; never a discharge target."""

    run_id: str
    hospital_id: Identifier
    stay_id: str
    decision_h: Count
    status: Literal["admitted", "awaiting_admission", "unit_absence", "closed", "unobserved"]
    current_unit_id: Identifier | None
    absence_unit_id: Identifier | None
    absence_h: Hour | None
    closure_kind: Literal["departure", "not_admitted"] | None
    observation_conflict: StrictBool
    sources: tuple[PatientSource, ...]

    trigger_delivery_ids: tuple[str, ...]

    @model_validator(mode="after")
    def contract(self) -> Self:
        if any(s.available_h > self.decision_h for s in self.sources):
            raise ValueError("Future reconciliation evidence")
        absent = self.status == "unit_absence"
        if absent != (self.absence_unit_id is not None and self.absence_h is not None):
            raise ValueError("Unit absence needs its scope and date")
        if (self.status == "closed") != (self.closure_kind is not None):
            raise ValueError("Only a recorded movement can close a stay")
        if self.status != "admitted" and self.current_unit_id is not None:
            raise ValueError("Unlocated patient cannot occupy a unit")
        return self


def _state(
    events: Iterable[PatientDelivery],
    config: HospitalConfig,
    censuses: Iterable[tuple[CensusDelivery, CensusMember | None]] = (),
    *,
    retain_closed: bool = False,
) -> dict[str, Any] | None:
    # Censuses describe the end of a boundary, after its ordered movements.
    facts: list[
        tuple[float, int, int, str, PatientDelivery | tuple[CensusDelivery, CensusMember | None]]
    ] = [(r.event_h, 0, r.event_order, r.event_id, r) for r in events]
    facts.extend((r.event_h, 1, 0, r.event_id, (r, member)) for r, member in censuses)
    sources: list[PatientSource] = []
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
        "presence_basis": "movement",
        "observation_conflict": False,
        "absence_unit_id": None,
        "absence_h": None,
        "closure_kind": None,
        "presence_h": None,
    }
    for _, _, _, _, fact in sorted(facts, key=lambda f: f[:4]):
        if isinstance(fact, tuple):
            census, member = fact
            applies = member is not None or (
                census.complete
                and state["status"] == "admitted"
                and state["current_unit_id"] == census.unit_id
            )
            if not applies and not census.voided:
                continue
            sources.append(
                PatientSource(
                    event_id=census.event_id,
                    version=census.event_version,
                    event_h=census.event_h,
                    available_h=census.available_h,
                    voided=census.voided,
                    source=census.source,
                    complete=census.complete,
                )
            )
            if census.voided:
                continue
            if member is not None:
                if state["status"] == "closed" or (
                    state["presence_basis"] == "census"
                    and state["presence_h"] == census.event_h
                    and state["current_unit_id"] != census.unit_id
                ):
                    state["observation_conflict"] = True
                state.update(
                    status="admitted",
                    current_unit_id=census.unit_id,
                    current_pole_id=config.unit_poles[census.unit_id],
                    bed_id=member.bed_id,
                    presence_basis="census",
                    absence_unit_id=None,
                    absence_h=None,
                    closure_kind=None,
                    presence_h=census.event_h,
                )
            else:
                state.update(
                    status="unit_absence",
                    current_unit_id=None,
                    current_pole_id=None,
                    bed_id=None,
                    absence_unit_id=census.unit_id,
                    absence_h=census.event_h,
                )
            continue
        row = fact
        sources.append(
            PatientSource(
                event_id=row.event_id,
                version=row.event_version,
                event_h=row.event_h,
                available_h=row.available_h,
                voided=row.voided,
            )
        )
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
                presence_basis="movement",
                absence_unit_id=None,
                absence_h=None,
                closure_kind=None,
                presence_h=row.event_h,
            )
            if isinstance(p, Admission):
                state.update(admission_h=row.event_h, home_unit_id=p.home_unit_id)
            else:
                state["internal_movements"] += 1
        elif isinstance(p, (Departure, NotAdmitted)):
            state.update(
                status="closed",
                current_unit_id=None,
                current_pole_id=None,
                bed_id=None,
                absence_unit_id=None,
                absence_h=None,
                closure_kind=p.kind,
            )
    if state["status"] is None:
        state["status"] = "unobserved"
    if not retain_closed and state["status"] in ("closed", "unit_absence", "unobserved"):
        return None
    state["sources"] = tuple(sources)
    state["last_event_h"] = max((r.event_h for r in sources if not r.voided), default=0.0)
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
        self.censuses: dict[str, dict[str, CensusDelivery]] = {}
        self.members: dict[str, dict[str, CensusMember]] = {}
        self.stay_units: dict[str, set[str]] = {}
        self.stay_start: dict[str, float] = {}
        self.dependencies: dict[str, set[str]] = {}
        self.states: dict[str, dict[str, Any]] = {}
        self.reconciliations: tuple[PatientReconciliation, ...] = ()

    def advance(
        self,
        hour: int,
        deliveries: Iterable[PatientDelivery],
        censuses: Iterable[CensusDelivery] = (),
    ) -> tuple[PatientRow, ...]:
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
        census_batch = sorted(
            (CensusDelivery.model_validate_json(r.model_dump_json()) for r in censuses),
            key=census_order,
        )
        for census in census_batch:
            if census.available_h > hour:
                raise ValueError("Cannot ingest a future census")
            if (
                census.hospital_id != self.config.hospital_id
                or self.config.unit_poles.get(census.unit_id) != census.pole_id
            ):
                raise ValueError("Census topology mismatch")
            _check(self.receipts, receipts, census.delivery_id, census.model_dump_json())
            _check(
                self.versions,
                versions,
                (census.event_id, census.event_version),
                census.content_key(),
            )
            _check(self.identities, identities, census.event_id, census.identity)
        self.receipts.update(receipts)
        self.versions.update(versions)
        self.identities.update(identities)
        touched = set()
        for row in batch:
            history = self.history.setdefault(row.stay_id, {})
            previous = history.get(row.event_id)
            if previous is None or row.event_version > previous.event_version:
                history[row.event_id] = row
                self.stay_units.setdefault(row.stay_id, set()).add(row.unit_id)
                self.stay_start[row.stay_id] = min(
                    self.stay_start.get(row.stay_id, row.event_h),
                    row.event_h,
                )
                touched.add(row.stay_id)
        for census in census_batch:
            history_c = self.censuses.setdefault(census.unit_id, {})
            previous_c = history_c.get(census.event_id)
            if previous_c is not None and census.event_version <= previous_c.event_version:
                continue
            touched.update(self.active)
            touched.update(self.dependencies.get(census.event_id, ()))
            if previous_c:
                touched.update(m.stay_id for m in previous_c.members)
            history_c[census.event_id] = census
            self.members[census.event_id] = {m.stay_id: m for m in census.members}
            for member in census.members:
                touched.add(member.stay_id)
                self.stay_units.setdefault(member.stay_id, set()).add(census.unit_id)
                self.stay_start[member.stay_id] = min(
                    self.stay_start.get(member.stay_id, census.event_h),
                    census.event_h,
                )
        changes = []
        for stay in touched:
            state = _state(
                self.history.get(stay, {}).values(),
                self.config,
                (
                    (c, self.members[c.event_id].get(stay))
                    for u in self.stay_units.get(stay, ())
                    for c in self.censuses.get(u, {}).values()
                    if c.event_h >= self.stay_start[stay]
                ),
                retain_closed=True,
            )
            if state is None:
                self.active.pop(stay, None)
                self.states.pop(stay, None)
            else:
                if state != self.states.get(stay):
                    changes.append(
                        PatientReconciliation(
                            run_id=self.run_id,
                            hospital_id=self.config.hospital_id,
                            stay_id=stay,
                            decision_h=hour,
                            trigger_delivery_ids=tuple(
                                sorted(
                                    [r.delivery_id for r in batch]
                                    + [r.delivery_id for r in census_batch]
                                )
                            ),
                            **{
                                k: state[k]
                                for k in (
                                    "status",
                                    "current_unit_id",
                                    "absence_unit_id",
                                    "absence_h",
                                    "closure_kind",
                                    "observation_conflict",
                                    "sources",
                                )
                            },
                        )
                    )
                self.states[stay] = state
                for source in state["sources"]:
                    if source.source == "RECENSEMENT_UNITE":
                        self.dependencies.setdefault(source.event_id, set()).add(stay)
                if state["status"] in ("admitted", "awaiting_admission"):
                    self.active[stay] = state
                else:
                    self.active.pop(stay, None)
        self.reconciliations = tuple(sorted(changes, key=lambda r: r.stay_id))
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
                    **{
                        k: v
                        for k, v in state.items()
                        if k not in ("absence_unit_id", "absence_h", "closure_kind", "presence_h")
                    },
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


def replay_patient_batches(
    deliveries: Iterable[PatientDelivery],
    config: HospitalConfig,
    *,
    run_id: str,
    stale_after_h: float = 96.0,
    censuses: Iterable[CensusDelivery] = (),
) -> Iterator[tuple[tuple[PatientRow, ...], tuple[PatientReconciliation, ...]]]:
    ordered = sorted(deliveries, key=delivery_order)
    ordered_c = sorted(censuses, key=census_order)
    cursor = PatientAsOfCursor(config, run_id=run_id, stale_after_h=stale_after_h)
    index = 0
    index_c = 0
    for hour in range(config.days * 24):
        end = index
        while end < len(ordered) and ordered[end].available_h <= hour:
            end += 1
        end_c = index_c
        while end_c < len(ordered_c) and ordered_c[end_c].available_h <= hour:
            end_c += 1
        rows = cursor.advance(hour, ordered[index:end], ordered_c[index_c:end_c])
        yield rows, cursor.reconciliations
        index = end
        index_c = end_c


def replay_patients(
    deliveries: Iterable[PatientDelivery],
    config: HospitalConfig,
    *,
    run_id: str,
    stale_after_h: float = 96.0,
    censuses: Iterable[CensusDelivery] = (),
) -> Iterator[PatientRow]:
    for rows, _ in replay_patient_batches(
        deliveries,
        config,
        run_id=run_id,
        stale_after_h=stale_after_h,
        censuses=censuses,
    ):
        yield from rows
