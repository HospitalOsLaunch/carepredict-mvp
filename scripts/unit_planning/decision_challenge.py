"""Three constructed unit contexts and a separate minute-by-minute active-practice oracle."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import combinations
from random import Random

from hospitalos.hybrid.models import Action, Bed, Discharge, FactEvent, Patient, ResourcePool, Unit
from hospitalos.hybrid.planning import PlanRequest
from hospitalos.hybrid.scenarios import FutureAssumptions, ResourceChange
from hospitalos.hybrid.simulation import Assumptions
from hospitalos.hybrid.unit_schedule import UnitSchedule

D = datetime(2026, 11, 24, 7, 30, tzinfo=UTC)
HORIZON = 720
FAMILIES = ("transport_cleaning", "compatible_beds", "staff_booking")
RULE = ("request_transport", "reserve_bed", "prioritize_cleaning", "reinforce", "prepare_admission")


@dataclass(frozen=True)
class Case:
    family: str
    index: int
    # Beds: id, state at origin, oxygen available. Queue order is the public priority order.
    beds: tuple[tuple[str, str, bool], ...]
    queue: tuple[tuple[str, bool], ...]
    team_delay: int
    already_preparing: bool
    initial_capacity: int
    schedule_capacity: int
    booked_at: int
    booking_work: int
    clean: int
    prep: int
    travel: int

    def request(self, budget: int, *, unit: str = "unit", origin: datetime = D) -> PlanRequest:
        facts = [Unit(id=unit, staffed_beds=self.initial_capacity, cleaning_teams=1)]
        for bid, status, o2 in self.beds:
            facts.append(
                Bed(
                    id=bid,
                    unit_id=unit,
                    state=status,
                    capabilities=("oxygen",) if o2 else (),
                    occupant="out" if status == "occupied" else None,
                )
            )
            if status == "occupied":
                facts.extend(
                    [
                        Patient(
                            id="out",
                            status="admitted",
                            compatible_units=(unit,),
                            bed_id=bid,
                            waiting_since=origin - timedelta(days=2),
                            medically_cleared=True,
                        ),
                        Discharge(
                            id="out",
                            documents_ready=True,
                            escort_required=False,
                            transport_required=True,
                            transport_requested=False,
                            transport_pool_id="pool",
                            downstream_required=False,
                        ),
                        ResourcePool(
                            id="pool", resource="transport", unit_ids=(unit,), available=1
                        ),
                    ]
                )
        for i, (pid, o2) in enumerate(self.queue):
            facts.append(
                Patient(
                    id=pid,
                    status="waiting",
                    compatible_units=(unit,),
                    priority=5 - i,
                    waiting_since=origin - timedelta(minutes=60 - i),
                    requirements=("oxygen",) if o2 else (),
                )
            )
        future = None
        if self.family == "staff_booking":

            def at(m):
                return origin + timedelta(minutes=m)

            facts.append(
                UnitSchedule.model_validate(
                    {
                        "id": unit,
                        "budget_minutes": 240,
                        "offers": [
                            {
                                "option": {
                                    "option_id": "loan",
                                    "skill": "IDE",
                                    "start": at(15),
                                    "end": at(240),
                                    "source": "shared_unit",
                                    "confirmation": "confirmed",
                                    "lending_unit": "donor",
                                    "lending_unit_minimum": 2,
                                    "lending_unit_scheduled": 3,
                                },
                                "staff_id": "team",
                                "staffed_places": 1,
                            }
                        ],
                        "admissions": [
                            {
                                "request": {
                                    "request_id": "booking",
                                    "requirements": ["oxygen"],
                                    "expected_arrival": at(self.booked_at),
                                    "arrival_delay": {"support": [0, 10, 20], "weights": [1, 1, 1]},
                                    "care": [],
                                    "admission_task_minutes": self.booking_work,
                                    "provenance": {
                                        "source": "appointment",
                                        "obs_id": "appointment",
                                        "event_time": origin,
                                        "available_at": origin,
                                    },
                                },
                                "window_start": at(15),
                                "window_end": at(230),
                            }
                        ],
                    }
                )
            )
            future = FutureAssumptions(
                declared_at=origin,
                changes=(
                    ResourceChange(
                        id="new_shift",
                        minute=self.schedule_capacity,
                        target_id=unit,
                        resource="staffed_beds",
                        capacity=1,
                    ),
                ),
            )
        events = tuple(
            FactEvent(
                hospital_id="challenge",
                event_id=f"{f.kind}:{f.id}",
                source="synthetic_public",
                event_time=origin,
                available_at=origin,
                fact=f,
            )
            for f in facts
        )
        return PlanRequest(
            hospital_id="challenge",
            unit_id=unit,
            events=events,
            expected_entities=tuple(e.event_id for e in events),
            at=origin,
            horizon_minutes=HORIZON,
            max_bundle=budget,
            scenarios=4,
            seed=71000 + self.index,
            assumptions=Assumptions(
                cleaning_minutes=(self.clean, self.clean + 10),
                departure_minutes=(self.prep, self.prep + 15),
                transport_minutes=(self.travel, self.travel + 10),
                load_multipliers=(1,),
            ),
            future=future,
        )

    def options(self):
        # Independent catalogue from public facts; the optimizer cannot hide an alternative.
        actions = []
        for bid, status, o2 in self.beds:
            if status == "dirty":
                actions.append(Action(kind="prioritize_cleaning", bed_id=bid))
            if status == "occupied":
                actions.append(Action(kind="request_transport", bed_id=bid, patient_id="out"))
            if status == "clean":
                actions.extend(
                    Action(kind="reserve_bed", bed_id=bid, patient_id=pid)
                    for pid, needs in self.queue
                    if not needs or o2
                )
        if self.family == "staff_booking":
            actions.extend(
                (
                    Action(kind="reinforce", slot_id="loan"),
                    Action(kind="prepare_admission", slot_id="booking", bed_id="A"),
                )
            )
        actions.sort(key=lambda a: (RULE.index(a.kind), a.key))
        return actions

    def programs(self, budget):
        singles = self.options()
        programs = [(), *((a,) for a in singles)]
        if budget == 2:
            for left, right in combinations(singles, 2):
                if left.kind == right.kind == "reserve_bed" and (
                    left.bed_id == right.bed_id or left.patient_id == right.patient_id
                ):
                    continue
                programs.append((left, right))
        return programs


def case(family, index):
    f = FAMILIES.index(family)
    rng = Random(81111 + f * 101 + index)
    queue = ()
    if family == "transport_cleaning":
        beds = (("A", "dirty", False), ("B", "dirty", True), ("C", "occupied", bool(index % 3)))
        queue = tuple((f"w{i}", i == 0 or rng.random() < 0.55) for i in range(2 + index % 2))
    elif family == "compatible_beds":
        beds = (
            ("A", "clean", True),
            ("B", "clean" if index % 3 else "dirty", False),
            ("C", "dirty", bool(index % 2)),
        )
        queue = (("w0", bool(index % 4 == 1)), ("w1", True), ("w2", False))
    else:
        beds = (("A", "clean", True),)
    return Case(
        family,
        index,
        beds,
        queue,
        (30, 60, 120)[index % 3],
        bool(index % 2),
        int(index % 4 == 0) if family == "staff_booking" else len(beds),
        rng.randrange(75, 156),
        rng.randrange(30, 76),
        rng.randrange(40, 106),
        rng.randrange(22, 76),
        rng.randrange(20, 96),
        rng.randrange(15, 66),
    )


@dataclass(frozen=True)
class Realization:
    clean: dict[str, int]
    prep: int
    travel: int
    arrival: int
    desk: int


def realizations(c):
    for j in range(4):
        rng = Random(754000 + FAMILIES.index(c.family) * 3000 + 10 * c.index + j)
        yield Realization(
            {bid: max(1, c.clean + rng.randrange(-12, 23)) for bid, _, _ in c.beds},
            max(1, c.prep + rng.randrange(-12, 29)),
            max(1, c.travel + rng.randrange(-10, 22)),
            c.booked_at + rng.choice((0, 10, 20)),
            max(1, c.booking_work + rng.randrange(-10, 20)),
        )


def booking_outcome(c, kinds, latent, *, active=True, gesture_at=0, shock=False):
    """Waiting and over-staffed-capacity exposure for one scheduled arrival."""
    usual = c.team_delay if active else HORIZON
    setup = gesture_at if "prepare_admission" in kinds else usual
    ready = max(latent.arrival, min(latent.arrival, setup) + latent.desk)
    loan = gesture_at if "reinforce" in kinds else usual
    staffed = 0 if c.initial_capacity else min(c.schedule_capacity, max(15, loan))
    admit = max(staffed, ready)
    over = 0
    if shock:
        if admit < 90:
            over = 60  # already in the bed when its staffing disappears
        elif admit < 150:
            admit = 150
    return min(HORIZON, admit) - latent.arrival, over


def waiting_cost(
    c,
    program,
    latent,
    *,
    active=True,
    gesture_at=0,
    preparing=None,
    resident_exit=None,
    emergency=(),
):
    """Physical opportunities under current practice. Every arm shares the same latent future."""
    kinds = {a.kind for a in program}
    if c.family == "staff_booking":
        return booking_outcome(c, kinds, latent, active=active, gesture_at=gesture_at)[0]
    status = {bid: s for bid, s, _ in c.beds}
    oxygen = {bid: o for bid, _, o in c.beds}
    waiting = dict(c.queue)
    reserved = {}
    priorities = set()
    release = None
    if "occupied" in status.values():
        request_time = (
            gesture_at if "request_transport" in kinds else (c.team_delay if active else HORIZON)
        )
        in_progress = c.already_preparing if preparing is None else preparing
        release = (
            max(request_time, latent.prep) if in_progress else request_time + latent.prep
        ) + latent.travel
    cleaning = None
    dirty_at = {bid: 0 for bid in status if status[bid] == "dirty"}
    area = 0
    incident = {}
    for index, minute in enumerate(emergency):
        if 0 <= minute < HORIZON:
            incident.setdefault(minute, []).append(f"ed-{index}")
    last_arrival = max(incident, default=-1)
    for m in range(HORIZON):
        for pid in incident.get(m, ()):
            waiting[pid] = False
        if m == resident_exit:
            status["D"] = "dirty"
            dirty_at["D"] = m
        if m == release:
            status["C"] = "dirty"
            dirty_at["C"] = m
        if cleaning and cleaning[1] == m:
            status[cleaning[0]] = "clean"
            cleaning = None
        if m == gesture_at:
            for act in program:
                if act.kind == "prioritize_cleaning":
                    priorities.add(act.bed_id)
                if (
                    act.kind == "reserve_bed"
                    and status[act.bed_id] == "clean"
                    and act.patient_id in waiting
                ):
                    reserved[act.bed_id] = act.patient_id
        if active and m == c.team_delay:
            # Team pursues the oxygen bottleneck on its next round in every arm.
            for bid in status:
                if status[bid] == "dirty" and oxygen[bid]:
                    priorities.add(bid)
                    break
            if c.family == "compatible_beds" and status["A"] == "clean" and "A" not in reserved:
                patient = next(
                    (p for p in waiting if waiting[p] and p not in reserved.values()), None
                )
                if patient:
                    reserved["A"] = patient
        for p in tuple(waiting):
            for bid in status:
                if (
                    status[bid] == "clean"
                    and (not waiting[p] or oxygen[bid])
                    and reserved.get(bid, p) == p
                    and (p not in reserved.values() or reserved.get(bid) == p)
                ):
                    status[bid] = "occupied"
                    del waiting[p]
                    reserved.pop(bid, None)
                    break
        if not cleaning:
            candidates = [bid for bid in status if status[bid] == "dirty"]
            if candidates:
                bid = min(candidates, key=lambda b: (b not in priorities, dirty_at[b], b))
                cleaning = (bid, m + latent.clean[bid])
                status[bid] = "cleaning"
        area += len(waiting)
        if not waiting and m >= last_arrival:
            break
    return area
