"""Declared synthetic care pathways, programmed admissions and operational constraints.

No clinical decision can be made by an operations command. Clinical authorizations
and routine logistics progress independently in the fictional background.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from hospitalos.simulator.engine import START, Frame, PhysicalBed, PhysicalPatient

from .config import HospitalConfig
from .engine import VirtualEngine

PARIS = ZoneInfo("Europe/Paris")
UNIT_ROUTES = {
    "geriatrie": ("geriatrie", "medecine"),
    "medecine": ("medecine", "geriatrie"),
    "pneumologie": ("pneumologie", "medecine"),
    "chirurgie": ("chirurgie",),
}


@dataclass
class CareBed(PhysicalBed):
    isolation: bool = False


@dataclass
class CarePatient(PhysicalPatient):
    compatible_units: tuple[str, ...] = ()
    isolation: bool = False
    programmed: bool = False
    discharge_planned: bool = False
    documents_ready: bool = False
    transport_required: bool = False
    transport_requested: bool = False
    transport_ready: bool = False
    downstream_required: bool = False
    downstream_ready: bool = False
    downstream_requested: bool = False
    documents_requested: bool = False


@dataclass(frozen=True)
class CareFrame(Frame):
    staffed_beds: int = 0
    held_beds: tuple[str, ...] = ()


class ClinicalEngine(VirtualEngine):
    def __init__(
        self,
        config: HospitalConfig,
        seed: int,
        deliver: Callable[[Frame], None],
        *,
        epoch: datetime = START,
    ) -> None:
        self.declared_capacity = config.staffed_beds
        self.capacity_version = 0
        self.capacity_reason = "Capacité nominale"
        self.capacity_until: datetime | None = None
        self.closures: dict[str, tuple[int, datetime, str]] = {}
        self.closure_versions: dict[str, int] = {}
        self.holds: dict[str, str] = {}
        self.pending_placements: set[str] = set()
        self.service_requests: set[tuple[str, str]] = set()
        self.completed_admissions: set[str] = set()
        super().__init__(config, seed, deliver, epoch=epoch)
        # Programmed patients are declared 48 hours ahead, independent of recommendations.
        self._schedule_day(epoch.astimezone(PARIS).date().isoformat())

    def _make_bed(self, identifier: str, **kwargs: Any) -> PhysicalBed:
        number = int(identifier.rsplit("G", 1)[-1])
        return CareBed(identifier, isolation=number % 4 == 1, **kwargs)

    def _make_patient(self, identifier: str, since: float, **kwargs: Any) -> PhysicalPatient:
        admitted = kwargs.get("status") == "admitted"
        return CarePatient(
            identifier,
            since,
            compatible_units=UNIT_ROUTES[self.config.unit_id],
            isolation=not admitted and self.draw("isolation", identifier, 0, (0, 0, 0, 0, 1)) == 1,
            **kwargs,
        )

    @property
    def staffed_capacity(self) -> int:
        return self.declared_capacity

    def compatible(self, patient: PhysicalPatient, bed: PhysicalBed) -> bool:
        return (
            super().compatible(patient, bed)
            and isinstance(patient, CarePatient)
            and self.config.unit_id in patient.compatible_units
            and (not patient.isolation or (isinstance(bed, CareBed) and bed.isolation))
        )

    def held_for_other(self, bed_id: str, patient_id: str) -> bool:
        return bed_id in self.holds and self.holds[bed_id] != patient_id

    def _reserve(self, patient_id: str, bed_id: str, *, coordinated: bool = False) -> bool:
        if patient_id in self.pending_placements and not coordinated:
            return False
        protected = next((bed for bed, owner in self.holds.items() if owner == patient_id), None)
        if protected is not None and bed_id != protected:
            return False
        committed = sum(
            b.occupant is not None
            or b.reserved_for is not None
            or (b.id in self.holds and self.holds[b.id] != patient_id)
            for b in self.beds.values()
        )
        if committed >= self.staffed_capacity:
            return False
        result = super()._reserve(patient_id, bed_id, coordinated=coordinated)
        if result and self.holds.get(bed_id) == patient_id:
            del self.holds[bed_id]
        return result

    def set_capacity(self, capacity: int, until: datetime, reason: str) -> None:
        if not 0 <= capacity <= self.config.beds or until <= self.now:
            raise ValueError("invalid_capacity_or_expiry")
        self.declared_capacity, self.capacity_reason, self.capacity_until = capacity, reason, until
        self.capacity_version += 1
        version = self.capacity_version

        def restore() -> None:
            if version == self.capacity_version:
                self.declared_capacity = self.config.staffed_beds
                self.capacity_reason, self.capacity_until = "Capacité nominale", None

        self._later((until - self.now).total_seconds(), restore)

    def close_bed(self, bed_id: str, until: datetime, reason: str) -> None:
        bed = self.beds[bed_id]
        if bed.occupant or bed.reserved_for or bed_id in self.holds or until <= self.now:
            raise ValueError("bed_committed_or_invalid_expiry")
        version = self.closure_versions.get(bed_id, 0) + 1
        self.closure_versions[bed_id] = version
        self.closures[bed_id] = (version, until, reason)
        bed.opened = False

        def restore() -> None:
            if self.closures.get(bed_id, (0, until, reason))[0] == version:
                bed.opened = True
                del self.closures[bed_id]

        self._later((until - self.now).total_seconds(), restore)

    def reopen_bed(self, bed_id: str) -> None:
        self.beds[bed_id].opened = True
        self.closures.pop(bed_id, None)

    def schedule(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        day = start.astimezone(PARIS).date()
        while day <= end.astimezone(PARIS).date():
            for hour in (8, 11, 15):
                at = datetime(day.year, day.month, day.day, hour, tzinfo=PARIS).astimezone(UTC)
                if start <= at <= end:
                    identifier = f"{self.config.unit_id}-P-P{day:%Y%m%d}-{hour}"
                    result.append(
                        {
                            "id": identifier,
                            "unit_id": self.config.unit_id,
                            "at": at.isoformat(),
                            "oxygen": hour == 11,
                            "isolation": False,
                        }
                    )
            day += timedelta(days=1)
        return result

    def _schedule_day(self, date: str) -> None:
        start = datetime.fromisoformat(date).replace(tzinfo=PARIS).astimezone(UTC)
        tomorrow = (start.astimezone(PARIS) + timedelta(days=1)).replace(hour=0).astimezone(UTC)
        for admission in self.schedule(start, tomorrow - timedelta(seconds=1)):
            at = datetime.fromisoformat(admission["at"])
            if at < self.now:
                continue

            def arrive(entry: dict[str, Any] = admission) -> None:
                identifier = str(entry["id"])
                self.patients[identifier] = CarePatient(
                    identifier,
                    self.second,
                    oxygen=bool(entry["oxygen"]),
                    programmed=True,
                    compatible_units=(self.config.unit_id,),
                )
                self.completed_admissions.add(identifier)
                self._record("programmed_arrival", identifier)

            self._later((at - self.now).total_seconds(), arrive)
        self._later(
            (tomorrow - self.now).total_seconds(),
            lambda: self._schedule_day(tomorrow.astimezone(PARIS).date().isoformat()),
        )

    def _schedule_departure(self, patient: PhysicalPatient, delay: float) -> None:
        assert isinstance(patient, CarePatient)

        def plan() -> None:
            patient.discharge_planned = True
            patient.transport_required = self.draw("needs_transport", patient.id, 0, (0, 1, 1)) == 1
            patient.downstream_required = (
                self.draw("needs_downstream", patient.id, 0, (0, 0, 1)) == 1
            )
            self._record("discharge_planned", patient.id, patient.bed)

        def ready() -> None:
            patient.cleared = True
            self._record("medically_cleared", patient.id, patient.bed)
            # Baseline hospital teams also work when nobody uses HospitalOS.
            self._later(900, lambda: self.request_service(patient.id, "documents"))
            if patient.transport_required:
                self._later(1800, lambda: self.request_service(patient.id, "transport"))
            if patient.downstream_required:
                self._later(1800, lambda: self.request_service(patient.id, "downstream"))
            self._try_depart(patient)

        self._later(max(0, delay - 7200), plan)
        self._later(delay, ready)

    def request_service(self, patient_id: str, service: str) -> None:
        patient = self.patients.get(patient_id)
        if not isinstance(patient, CarePatient) or patient.status != "admitted":
            return
        if (patient_id, service) in self.service_requests:
            return
        self.service_requests.add((patient_id, service))
        setattr(patient, f"{service}_requested", True)
        self._record(f"{service}_requested", patient.id, patient.bed)
        supports = {
            "documents": (600, 900, 1200),
            "transport": (1800, 2700, 3600),
            "downstream": (3600, 5400, 7200),
        }
        delay = self.draw(f"{service}_response", patient.id, 0, supports[service])

        def complete() -> None:
            setattr(patient, f"{service}_ready", True)
            self._record(f"{service}_confirmed", patient.id, patient.bed)
            self._try_depart(patient)

        self._later(delay, complete)

    def _try_depart(self, patient: CarePatient) -> None:
        if not (
            patient.status == "admitted"
            and patient.cleared
            and patient.documents_ready
            and (not patient.transport_required or patient.transport_ready)
            and (not patient.downstream_required or patient.downstream_ready)
        ):
            return
        key = (patient.id, "departure")
        if key in self.service_requests:
            return
        self.service_requests.add(key)

        def depart() -> None:
            if patient.status != "admitted":
                return
            bed = self.beds[patient.bed or ""]
            bed.occupant, bed.hygiene = None, "dirty"
            patient.status, patient.bed = "departed", None
            self.departed_at[patient.id] = self.second
            self._record("departed", patient.id, bed.id)
            self.check()

        self._later(self.config.departure_delay_seconds, depart)

    def _observe(self) -> None:
        expired = [key for key, at in self.departed_at.items() if self.second - at > 120]
        for key in expired:
            self.patients.pop(key, None)
            self.departed_at.pop(key, None)
        if self.feed_enabled:
            frame = CareFrame(
                self.now,
                tuple(replace(b) for b in self.beds.values()),
                tuple(replace(p) for p in self.patients.values()),
                self.config.cleaning_teams - len(self.cleaning),
                self.staffed_capacity,
                tuple(self.holds),
            )

            def receive() -> None:
                if self.feed_enabled:
                    self.deliver(frame)
                    self.observed = frame
                    self._allocate()

            self._later(self.config.delivery_seconds, receive)
        self._later(self.config.observation_seconds, self._observe)
