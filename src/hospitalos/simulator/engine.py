"""Independent SimPy truth engine for one geriatric demonstration unit.

No planner import. Staff act on delivered observations, then check physical
preconditions. The journal and future event queue never enter the cockpit API.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Generator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal

import simpy

START = datetime(2026, 10, 25, 7, 30, tzinfo=UTC)
UNIT = "court-sejour-geriatrique"
HOSPITAL = "hopital-simule"
SOURCE = "si-simule"
LIMIT = 3 * 3600


@dataclass
class PhysicalBed:
    id: str
    oxygen: bool = False
    occupant: str | None = None
    hygiene: Literal["dirty", "cleaning", "ready"] = "dirty"
    opened: bool = True
    reserved_for: str | None = None


@dataclass
class PhysicalPatient:
    id: str
    since: float
    oxygen: bool = False
    status: Literal["waiting", "admitted", "departed"] = "waiting"
    bed: str | None = None
    cleared: bool = False


@dataclass(frozen=True)
class TruthEvent:
    second: float
    kind: str
    patient: str | None = None
    bed: str | None = None


@dataclass(frozen=True)
class Frame:
    """A direct observation at a known time, with no future primitive or journal."""

    observed_at: datetime
    beds: tuple[PhysicalBed, ...]
    patients: tuple[PhysicalPatient, ...]
    cleaning_available: int


class HospitalSimulation:
    def __init__(self, seed: int, deliver: Callable[[Frame], None]) -> None:
        self.env = simpy.Environment()
        self.seed = seed
        self.deliver = deliver
        self.feed_enabled = True
        self.beds = {
            "G01": PhysicalBed("G01"),
            "G02": PhysicalBed("G02", oxygen=True),
            "G03": PhysicalBed("G03", occupant="P-G00", hygiene="ready"),
        }
        self.patients = {
            "P-G00": PhysicalPatient("P-G00", -86400, status="admitted", bed="G03", cleared=True),
            "P-G01": PhysicalPatient("P-G01", 0, oxygen=True),
        }
        self.journal: list[TruthEvent] = []
        self.observed: Frame | None = None
        self.cleaning_bed: str | None = None
        self.priority: str | None = None
        self.coordinator_free = 0.0
        self._record("initial_admitted", "P-G00", "G03")
        self._record("initial_waiting", "P-G01")
        self._later(0, self._observe)
        self._later(120, self._dispatch)
        self._later(600, self._arrive)
        self._later(2400, self._depart)

    @property
    def second(self) -> float:
        return float(self.env.now)

    @property
    def now(self) -> datetime:
        return START + timedelta(seconds=self.second)

    def _later(self, delay: float, callback: Callable[[], None]) -> None:
        def task() -> Generator[simpy.Event, object, None]:
            yield self.env.timeout(delay)
            callback()

        self.env.process(task())

    def advance(self, seconds: float) -> None:
        target = self.second + seconds
        if seconds < 0 or target > LIMIT:
            raise ValueError("simulation_horizon_exceeded")
        # SimPy run(until=t) excludes events at t: explicitly process the boundary.
        while self.env.peek() <= target:
            self.env.step()
        if self.second < target:
            self.env.run(until=target)
        self.check()

    def _record(self, kind: str, patient: str | None = None, bed: str | None = None) -> None:
        self.journal.append(TruthEvent(self.second, kind, patient, bed))

    def _duration(self, mechanism: str, entity: str, support: tuple[int, ...]) -> int:
        # One occurrence per mechanism/entity in this bounded scenario. No redraw on refusal.
        key = f"demo-world-1|{self.seed}|{mechanism}|{entity}|0".encode()
        return support[int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % len(support)]

    def _observe(self) -> None:
        if self.feed_enabled:
            frame = Frame(
                observed_at=self.now,
                beds=tuple(replace(b) for b in self.beds.values()),
                patients=tuple(replace(p) for p in self.patients.values()),
                cleaning_available=int(self.cleaning_bed is None),
            )

            def receive() -> None:
                if self.feed_enabled:
                    self.deliver(frame)
                    self.observed = frame
                    self._allocate()

            self._later(30, receive)
        self._later(60, self._observe)

    def _arrive(self) -> None:
        self.patients["P-G02"] = PhysicalPatient("P-G02", self.second)
        self._record("arrived", "P-G02")

    def _depart(self) -> None:
        p = self.patients["P-G00"]
        if p.status != "admitted" or not p.cleared:
            return
        bed = self.beds[p.bed or ""]
        bed.occupant, bed.hygiene = None, "dirty"
        p.status, p.bed = "departed", None
        self._record("departed", p.id, bed.id)
        self.check()

    def _dispatch(self) -> None:
        if self.cleaning_bed is None and self.observed is not None:
            candidates = sorted(
                (b for b in self.observed.beds if b.hygiene == "dirty" and not b.occupant),
                key=lambda b: (b.id != self.priority, b.id),
            )
            if candidates:
                bed = self.beds[candidates[0].id]
                if bed.hygiene == "dirty" and bed.opened and bed.occupant is None:
                    bed.hygiene = "cleaning"
                    self.cleaning_bed = bed.id
                    self.priority = None
                    self._record("cleaning_started", bed=bed.id)

                    def finish() -> None:
                        bed.hygiene = "ready"
                        self.cleaning_bed = None
                        self._record("cleaning_finished", bed=bed.id)
                        self.check()

                    self._later(self._duration("cleaning", bed.id, (900, 1200, 1500)), finish)
                else:
                    self._record("cleaning_check_failed", bed=bed.id)
        self._later(60, self._dispatch)

    def _allocate(self) -> None:
        if self.observed is None or self.second < self.coordinator_free:
            return
        patients = sorted(
            (p for p in self.observed.patients if p.status == "waiting"),
            key=lambda p: (p.since, p.id),
        )
        beds = sorted(
            (
                b
                for b in self.observed.beds
                if b.hygiene == "ready"
                and b.opened
                and b.occupant is None
                and b.reserved_for is None
            ),
            key=lambda b: b.id,
        )
        for p in patients:
            for b in beds:
                if p.oxygen and not b.oxygen:
                    continue
                if self._reserve(p.id, b.id):
                    return  # One coordinator; another task waits for the next observation.

    def _reserve(self, patient_id: str, bed_id: str, *, coordinated: bool = False) -> bool:
        p, b = self.patients[patient_id], self.beds[bed_id]
        if (
            p.status != "waiting"
            or b.occupant is not None
            or b.reserved_for is not None
            or b.hygiene != "ready"
            or not b.opened
            or (p.oxygen and not b.oxygen)
            or any(x.reserved_for == p.id for x in self.beds.values())
        ):
            return False
        if (
            sum(x.occupant is not None or x.reserved_for is not None for x in self.beds.values())
            >= 3
        ):
            return False
        b.reserved_for = p.id
        if not coordinated:
            self.coordinator_free = self.second + 30
        self._record("reserved", p.id, b.id)

        def install() -> None:
            if (
                b.reserved_for == p.id
                and b.occupant is None
                and b.hygiene == "ready"
                and b.opened
                and p.status == "waiting"
                and (not p.oxygen or b.oxygen)
            ):
                b.reserved_for, b.occupant = None, p.id
                p.status, p.bed = "admitted", b.id
                self._record("installed", p.id, b.id)
            else:
                if b.reserved_for == p.id:
                    b.reserved_for = None
                self._record("installation_failed", p.id, b.id)
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
        # Reading and acting use the same coordinator as baseline assignment.
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
                and bed.occupant is None
                and bed.opened
            ):
                self.priority = bed_id  # Never interrupts a cleaning task already started.
                self._record("cleaning_prioritized", bed=bed_id)
                done("executed")
                return
            if kind == "reserve_bed" and patient_id in self.patients and bed is not None:
                assert patient_id is not None
                if self._reserve(patient_id, bed_id, coordinated=True):
                    done("executed")
                    return
            self._record("action_failed", patient_id, bed_id)
            done("failed")

        self._later(self.coordinator_free - self.second, perform)

    def check(self) -> None:
        occupants = [b.occupant for b in self.beds.values() if b.occupant is not None]
        reservations = [b.reserved_for for b in self.beds.values() if b.reserved_for is not None]
        assert len(occupants) == len(set(occupants))
        assert len(reservations) == len(set(reservations))
        assert sum(b.hygiene == "cleaning" for b in self.beds.values()) <= 1
        for b in self.beds.values():
            if b.occupant:
                p = self.patients[b.occupant]
                assert p.status == "admitted" and p.bed == b.id and b.hygiene == "ready"
            if b.reserved_for:
                assert b.occupant is None and b.hygiene == "ready"
                assert self.patients[b.reserved_for].status == "waiting"
        for p in self.patients.values():
            if p.status == "admitted":
                assert p.bed is not None and self.beds[p.bed].occupant == p.id
