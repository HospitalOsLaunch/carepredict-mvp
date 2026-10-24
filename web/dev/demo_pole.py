"""Three more fictional units of the same medical pole, for the unit switcher.

Same rules as demo_unit.py: pseudonymous identifiers, synthetic durations, no claim.
Each unit is shaped to exercise a different planner outcome on the REAL planner:
heavy tension, a calm unit, and a unit whose data is too old to plan on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from demo_unit import ASSUMPTIONS, AT, HOSPITAL, SOURCE

from hospitalos.hybrid.models import Bed, Discharge, Fact, FactEvent, Patient, ResourcePool, Unit
from hospitalos.hybrid.planning import PlanRequest

O2 = ("oxygene",)


@dataclass
class Spec:
    unit: str
    staffed: int
    cleaning: int
    facts: list[tuple[Fact, int]] = field(default_factory=list)

    def bed(
        self, bid: str, state: str, *, occupant: str | None = None, o2: bool = False, age: int = 3
    ) -> None:
        self.facts.append(
            (
                Bed(
                    id=bid,
                    unit_id=self.unit,
                    state=state,  # type: ignore[arg-type]
                    occupant=occupant,
                    capabilities=O2 if o2 else (),
                ),
                age,
            )
        )

    def admitted(
        self,
        pid: str,
        bid: str,
        *,
        hours: int,
        cleared: bool | None = None,
        aval: bool | None = None,
        age: int = 15,
        o2: bool = False,
    ) -> None:
        self.bed(bid, "occupied", occupant=pid, o2=o2, age=min(age, 5) if age < 60 else age)
        self.facts.append(
            (
                Patient(
                    id=pid,
                    status="admitted",
                    bed_id=bid,
                    compatible_units=(self.unit,),
                    waiting_since=AT - timedelta(hours=hours),
                    medically_cleared=cleared,
                    downstream_confirmed=aval,
                ),
                age,
            )
        )

    def waiting(self, pid: str, *, minutes: int, priority: int, o2: bool = False) -> None:
        self.facts.append(
            (
                Patient(
                    id=pid,
                    status="waiting",
                    compatible_units=(self.unit,),
                    requirements=O2 if o2 else (),
                    priority=priority,
                    waiting_since=AT - timedelta(minutes=minutes),
                ),
                5,
            )
        )

    def request(self) -> PlanRequest:
        facts = [
            (Unit(id=self.unit, staffed_beds=self.staffed, cleaning_teams=self.cleaning), 2),
            *self.facts,
        ]
        return PlanRequest(
            hospital_id=HOSPITAL,
            at=AT,
            expected_entities=tuple(f"{f.kind}:{f.id}" for f, _ in facts),
            events=tuple(
                FactEvent(
                    hospital_id=HOSPITAL,
                    event_id=f"demo:{self.unit}:{f.kind}:{f.id}",
                    source=SOURCE,
                    event_time=AT - timedelta(minutes=age),
                    available_at=AT - timedelta(minutes=age),
                    fact=f,
                )
                for f, age in facts
            ),
            assumptions=ASSUMPTIONS,
            horizon_minutes=480,
            scenarios=32,
        )


def geriatrie() -> PlanRequest:
    """Court séjour gériatrique: 6 patients waiting downstream of the ED, no clean bed."""
    s = Spec("court-sejour-geriatrique", staffed=18, cleaning=1)
    pools = (
        ResourcePool(
            id="transport-sanitaire", resource="transport", unit_ids=(s.unit,), available=1
        ),
        ResourcePool(
            id="ehpad-partenaires", resource="downstream", unit_ids=(s.unit,), available=1
        ),
    )
    s.facts += [(p, 8) for p in pools]
    long_stays = [("P-0503", 220), ("P-0511", 190), ("P-0517", 160), ("P-0522", 140)]
    for n, (pid, hours) in enumerate(long_stays, start=1):
        s.admitted(pid, f"G{n:02d}", hours=hours, o2=n == 2)
    s.admitted("P-0531", "G05", hours=120, cleared=True, aval=True, age=12)
    s.facts.append(
        (
            Discharge(
                id="P-0531",
                documents_ready=True,
                escort_required=False,
                downstream_required=True,
                downstream_pool_id="ehpad-partenaires",
                transport_required=True,
                transport_pool_id="transport-sanitaire",
                transport_requested=True,
            ),
            12,
        )
    )
    s.admitted("P-0536", "G06", hours=96, cleared=True, age=20)
    s.facts.append(
        (
            Discharge(
                id="P-0536",
                documents_ready=True,
                escort_required=True,
                escort_confirmed=True,
                downstream_required=False,
                transport_required=False,
            ),
            20,
        )
    )
    s.admitted("P-0540", "G07", hours=80, cleared=None, age=34)
    s.facts.append(
        (
            Discharge(
                id="P-0540", downstream_required=True, downstream_pool_id="ehpad-partenaires"
            ),
            34,
        )
    )
    stays = ["P-0544", "P-0548", "P-0552", "P-0556", "P-0561", "P-0565", "P-0569"]
    for n, pid in enumerate(stays, start=8):
        s.admitted(pid, f"G{n:02d}", hours=24 + 9 * n, o2=n in (9, 13))
    s.bed("G15", "dirty", o2=True, age=18)
    s.bed("G16", "dirty", age=41)
    s.bed("G17", "dirty", age=9)
    s.bed("G18", "closed", age=30)
    for pid, minutes, prio, o2 in [
        ("U-2011", 612, 4, True),
        ("U-2014", 540, 4, False),
        ("U-2019", 395, 3, False),
        ("U-2023", 260, 3, True),
        ("U-2026", 150, 2, False),
        ("U-2030", 64, 1, False),
    ]:
        s.waiting(pid, minutes=minutes, priority=prio, o2=o2)
    return s.request()


def medecine_interne() -> PlanRequest:
    """Médecine interne: calm morning, a clean bed already fits the only waiting patient."""
    s = Spec("medecine-interne", staffed=12, cleaning=1)
    s.facts.append(
        (
            ResourcePool(
                id="transport-sanitaire", resource="transport", unit_ids=(s.unit,), available=2
            ),
            6,
        )
    )
    for n in range(1, 10):
        s.admitted(f"P-06{n:02d}", f"I{n:02d}", hours=20 + 11 * n)
    s.admitted("P-0612", "I10", hours=70, cleared=True, age=25)
    s.facts.append(
        (
            Discharge(
                id="P-0612",
                documents_ready=False,
                escort_required=False,
                downstream_required=False,
                transport_required=False,
            ),
            25,
        )
    )
    s.bed("I11", "clean", age=12)
    s.bed("I12", "clean", age=12)
    s.waiting("U-3004", minutes=95, priority=2)
    return s.request()


def pneumologie() -> PlanRequest:
    """Pneumologie: the bed-board feed stopped 1 h 40 ago; HospitalOS must abstain."""
    s = Spec("pneumologie", staffed=16, cleaning=1)
    for n in range(1, 14):
        s.admitted(f"P-07{n:02d}", f"R{n:02d}", hours=18 + 7 * n, o2=n % 2 == 0, age=100)
    s.bed("R14", "dirty", o2=True, age=100)
    s.bed("R15", "clean", o2=True, age=100)
    s.bed("R16", "closed", age=100)
    for pid, minutes, prio in [("U-4002", 330, 3), ("U-4007", 120, 2)]:
        s.waiting(pid, minutes=minutes, priority=prio, o2=True)
    return s.request()
