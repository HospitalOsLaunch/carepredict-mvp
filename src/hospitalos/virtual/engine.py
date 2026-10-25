"""Continuous fictional hospital. No policy import and no browser-driven clock."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Generator
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import simpy

from hospitalos.simulator.engine import START, Frame, PhysicalBed, PhysicalPatient, TruthEvent

from .config import HospitalConfig


class VirtualEngine:
    def __init__(
        self,
        config: HospitalConfig,
        seed: int,
        deliver: Callable[[Frame], None],
        *,
        epoch: datetime = START,
    ) -> None:
        self.config, self.seed, self.deliver = config, seed, deliver
        self.epoch = epoch
        self.prefix = f"{config.unit_id}-" if epoch != START else ""
        self.env = simpy.Environment()
        self.feed_enabled = True
        self.observed: Frame | None = None
        self.journal: list[TruthEvent] = []
        self.primitives: dict[str, int] = {}
        self.beds = {
            f"{self.prefix}G{n:02d}": self._make_bed(
                f"{self.prefix}G{n:02d}",
                oxygen=n in config.oxygen_beds,
                hygiene="dirty" if n <= 2 else "ready",
            )
            for n in range(1, config.beds + 1)
        }
        self.patients: dict[str, PhysicalPatient] = {}
        self.departed_at: dict[str, float] = {}
        self.cleaning: set[str] = set()
        self.cleaning_occurrences: dict[str, int] = {}
        self.priorities: list[str] = []
        self.coordinator_free = 0.0
        self.arrival_index = 0
        for n in range(config.initially_occupied):
            bed = self.beds[f"{self.prefix}G{n + 3:02d}"]
            patient = self._make_patient(
                f"{self.prefix}P-I{n:03d}", -86400, oxygen=bed.oxygen, status="admitted", bed=bed.id
            )
            self.patients[patient.id] = patient
            bed.occupant = patient.id
            self._record("initial_admitted", patient.id, bed.id)
            self._schedule_departure(patient, 600 + n * 900)
        for n in range(config.initial_waiting):
            patient = self._make_patient(f"{self.prefix}P-W{n:03d}", -n * 300, oxygen=n == 0)
            self.patients[patient.id] = patient
            self._record("initial_waiting", patient.id)
        self._later(0, self._observe)
        self._later(120, self._dispatch)
        self._later(600, self._arrive)

    def _make_bed(self, identifier: str, **kwargs: Any) -> PhysicalBed:
        return PhysicalBed(identifier, **kwargs)

    def _make_patient(self, identifier: str, since: float, **kwargs: Any) -> PhysicalPatient:
        return PhysicalPatient(identifier, since, **kwargs)

    @property
    def staffed_capacity(self) -> int:
        return self.config.staffed_beds

    def compatible(self, patient: PhysicalPatient, bed: PhysicalBed) -> bool:
        return not patient.oxygen or bed.oxygen

    def held_for_other(self, bed_id: str, patient_id: str) -> bool:
        return False

    @property
    def second(self) -> float:
        return float(self.env.now)

    @property
    def now(self) -> datetime:
        return self.epoch + timedelta(seconds=self.second)

    def draw(self, mechanism: str, entity: str, occurrence: int, support: tuple[int, ...]) -> int:
        key = (
            f"virtual-world-1|{self.config.hospital_id}|{self.seed}|"
            f"{mechanism}|{entity}|{occurrence}"
        )
        value = support[
            int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") % len(support)
        ]
        self.primitives[key] = value
        return value

    def _record(self, kind: str, patient: str | None = None, bed: str | None = None) -> None:
        self.journal.append(TruthEvent(self.second, kind, patient, bed))

    def _later(self, delay: float, callback: Callable[[], None]) -> None:
        def task() -> Generator[simpy.Event, object, None]:
            yield self.env.timeout(delay)
            callback()

        self.env.process(task())

    def advance(self, seconds: float) -> None:
        if seconds < 0 or seconds > 86400:
            raise ValueError("advance_between_zero_and_one_day_required")
        target = self.second + seconds
        while self.env.peek() <= target:
            self.env.step()
        if self.second < target:
            self.env.run(until=target)
        self.check()

    def _observe(self) -> None:
        if self.epoch != START:
            # The campus archive owns historical observations; retain only active patients
            # and the short departure delivery window in the operational engine.
            expired = [key for key, at in self.departed_at.items() if self.second - at > 120]
            for key in expired:
                self.patients.pop(key, None)
                self.departed_at.pop(key, None)
        if self.feed_enabled:
            # Departures remain visible for one observation cycle. Future readiness is not exported.
            frame = Frame(
                self.now,
                tuple(replace(b) for b in self.beds.values()),
                tuple(
                    replace(p)
                    for p in self.patients.values()
                    if p.status != "departed" or self.second - self.departed_at[p.id] <= 120
                ),
                self.config.cleaning_teams - len(self.cleaning),
            )

            def receive() -> None:
                if self.feed_enabled:
                    self.deliver(frame)
                    self.observed = frame
                    self._allocate()

            self._later(self.config.delivery_seconds, receive)
        self._later(self.config.observation_seconds, self._observe)

    def _arrive(self) -> None:
        if (
            sum(p.status != "departed" for p in self.patients.values())
            >= self.config.max_active_patients
        ):
            raise RuntimeError("virtual_active_patient_bound_exceeded")
        index = self.arrival_index
        patient_id = f"{self.prefix}P-A{index:06d}"
        self.arrival_index += 1
        oxygen = self.draw("oxygen", patient_id, 0, (0, 0, 1)) == 1
        self.patients[patient_id] = self._make_patient(patient_id, self.second, oxygen=oxygen)
        self._record("arrived", patient_id)
        peak = self.config.regime == "influx" and 0 <= self.second % 86400 < 7200
        support = (
            self.config.peak_interarrival_seconds if peak else self.config.interarrival_seconds
        )
        self._later(self.draw("interarrival", "arrivals", index, support), self._arrive)

    def _schedule_departure(self, patient: PhysicalPatient, delay: float) -> None:
        def ready() -> None:
            patient.cleared = True
            self._record("medically_cleared", patient.id, patient.bed)
            self._later(self.config.departure_delay_seconds, depart)

        def depart() -> None:
            if patient.status != "admitted" or not patient.cleared:
                raise RuntimeError("invalid_virtual_departure")
            bed = self.beds[patient.bed or ""]
            bed.occupant, bed.hygiene = None, "dirty"
            patient.status, patient.bed = "departed", None
            self.departed_at[patient.id] = self.second
            self._record("departed", patient.id, bed.id)
            self.check()

        self._later(delay, ready)

    def _dispatch(self) -> None:
        if self.observed is not None:
            candidates = sorted(
                (b for b in self.observed.beds if b.hygiene == "dirty" and not b.occupant),
                key=lambda b: (
                    self.priorities.index(b.id)
                    if b.id in self.priorities
                    else len(self.priorities),
                    b.id,
                ),
            )
            for observed in candidates:
                if len(self.cleaning) >= self.config.cleaning_teams:
                    break
                bed = self.beds[observed.id]
                if bed.hygiene != "dirty" or bed.occupant or not bed.opened:
                    continue
                bed.hygiene = "cleaning"
                self.cleaning.add(bed.id)
                if bed.id in self.priorities:
                    self.priorities.remove(bed.id)
                occurrence = self.cleaning_occurrences.get(bed.id, 0)
                self.cleaning_occurrences[bed.id] = occurrence + 1
                self._record("cleaning_started", bed=bed.id)

                def finish(bed: PhysicalBed = bed) -> None:
                    bed.hygiene = "ready"
                    self.cleaning.remove(bed.id)
                    self._record("cleaning_finished", bed=bed.id)
                    self.check()

                self._later(
                    self.draw("cleaning", bed.id, occurrence, self.config.cleaning_seconds), finish
                )
        self._later(60, self._dispatch)

    def _allocate(self) -> None:
        if self.observed is None or self.second < self.coordinator_free:
            return
        # Declared acuity first; a 60-minute age band prevents unbounded bypass by new demand.
        patients = sorted(
            (p for p in self.observed.patients if p.status == "waiting"),
            key=lambda p: (-(int(p.oxygen) + int((self.second - p.since) // 3600)), p.since, p.id),
        )
        beds = sorted(
            (
                b
                for b in self.observed.beds
                if b.hygiene == "ready" and b.opened and not b.occupant and not b.reserved_for
            ),
            key=lambda b: b.id,
        )
        for p in patients:
            for b in beds:
                if p.oxygen and not b.oxygen:
                    continue
                if self._reserve(p.id, b.id):
                    return

    def _reserve(self, patient_id: str, bed_id: str, *, coordinated: bool = False) -> bool:
        patient, bed = self.patients.get(patient_id), self.beds.get(bed_id)
        if patient is None or bed is None:
            return False
        if (
            patient.status != "waiting"
            or bed.occupant
            or bed.reserved_for
            or bed.hygiene != "ready"
            or not bed.opened
            or not self.compatible(patient, bed)
            or self.held_for_other(bed_id, patient_id)
            or any(b.reserved_for == patient.id for b in self.beds.values())
            or sum(b.occupant is not None or b.reserved_for is not None for b in self.beds.values())
            >= self.staffed_capacity
        ):
            return False
        bed.reserved_for = patient.id
        if not coordinated:
            self.coordinator_free = self.second + 30
        self._record("reserved", patient.id, bed.id)

        def install() -> None:
            if (
                bed.reserved_for == patient.id
                and not bed.occupant
                and bed.hygiene == "ready"
                and bed.opened
                and patient.status == "waiting"
                and self.compatible(patient, bed)
                and sum(b.occupant is not None for b in self.beds.values()) < self.staffed_capacity
            ):
                bed.reserved_for, bed.occupant = None, patient.id
                patient.status, patient.bed = "admitted", bed.id
                self._record("installed", patient.id, bed.id)
                self._schedule_departure(
                    patient,
                    self.draw("clinical_stay", patient.id, 0, self.config.clinical_stay_seconds),
                )
            else:
                if bed.reserved_for == patient.id:
                    bed.reserved_for = None
                self._record("installation_failed", patient.id, bed.id)
            self.check()

        self._later(60, install)
        return True

    def command(
        self,
        kind: str,
        bed_id: str,
        patient_id: str | None,
        accepted: bool,
        done: Callable[[str], None],
    ) -> None:
        start = max(self.second, self.coordinator_free)
        self.coordinator_free = start + 30
        self._record("coordination_requested")

        def perform() -> None:
            if not accepted:
                done("refused")
                return
            bed = self.beds.get(bed_id)
            if (
                kind == "prioritize_cleaning"
                and bed is not None
                and bed.hygiene == "dirty"
                and not bed.occupant
                and bed.opened
            ):
                if bed_id not in self.priorities:
                    self.priorities.append(bed_id)
                self._record("cleaning_prioritized", bed=bed_id)
                done("executed")
            elif kind == "reserve_bed" and bed and patient_id in self.patients:
                assert patient_id is not None
                done(
                    "executed" if self._reserve(patient_id, bed_id, coordinated=True) else "failed"
                )
            else:
                self._record("action_failed", patient_id, bed_id)
                done("failed")

        self._later(self.coordinator_free - self.second, perform)

    def check(self) -> None:
        occupied = [b.occupant for b in self.beds.values() if b.occupant]
        reserved = [b.reserved_for for b in self.beds.values() if b.reserved_for]
        if (
            len(occupied) != len(set(occupied))
            or len(reserved) != len(set(reserved))
            or len(occupied) + len(reserved) > self.config.staffed_beds
            or len(self.cleaning) > self.config.cleaning_teams
        ):
            raise RuntimeError("virtual_capacity_or_uniqueness_violation")
        for bed in self.beds.values():
            if bed.occupant:
                patient = self.patients[bed.occupant]
                if not (
                    patient.status == "admitted"
                    and patient.bed == bed.id
                    and bed.hygiene == "ready"
                    and (not patient.oxygen or bed.oxygen)
                ):
                    raise RuntimeError("virtual_occupancy_violation")
            if bed.reserved_for and (
                bed.occupant
                or bed.hygiene != "ready"
                or self.patients[bed.reserved_for].status != "waiting"
            ):
                raise RuntimeError("virtual_reservation_violation")
        for patient in self.patients.values():
            if patient.status == "admitted" and (
                patient.bed is None or self.beds[patient.bed].occupant != patient.id
            ):
                raise RuntimeError("virtual_patient_conservation_violation")
