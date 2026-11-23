"""HOWM-1 world: explicit state x_t and transition operator (15-minute ticks).

The SAME operator runs the private truth (generator) and every model rollout; only the
``Provider`` differs (who draws durations, latencies, arrivals, presence, care). The operator
applies an event only if its preconditions hold; otherwise it is rejected and counted
(``rejected``), never corrected. It cannot create beds, staff or medical authorisations:
authorisations come from the provider as exogenous times and are never planner actions.

Time: integer ticks of 15 minutes from the episode start (Monday 00:00 Europe/Paris, no DST
change inside the episode window, see generator).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

TICK_MIN = 15
TPH = 4  # ticks per hour
TPD = 96  # ticks per day
SKILLS = ("IDE", "AS")
HABITUAL_TRANSPORT_HOURS = (11, 15)
CLEANING_HOURS = (6, 22)  # cleaning may START in [6, 22) local
ADMISSION_WORK_MIN = 30  # IDE minutes at placement hour
DISCHARGE_WORK_MIN = 20  # IDE minutes at departure hour


def local_hour(tick: int) -> int:
    return (tick % TPD) // TPH


def is_weekday(tick: int) -> bool:
    return (tick // TPD) % 7 < 5


@dataclass
class Bed:
    bed_id: str
    unit: str
    iso: bool
    state: str = "free"  # free | occ | dirty | cleaning
    stay: str | None = None
    dirty_tick: int | None = None
    clean_start: int | None = None
    clean_end: int | None = None  # private (truth) or sampled


@dataclass
class Stay:
    sid: str
    unit: str
    bed: str
    acuity: int
    iso: bool
    transport: bool
    placed_tick: int
    auth_tick: int | None = None  # time of authorisation (exogenous; private until it happens)
    authorised: bool = False
    ready_tick: int | None = None  # private until it happens
    ready: bool = False
    tr_req: int | None = None
    tr_conf: int | None = None  # time the transport request is confirmed (private until then)
    tr_accepted: bool = False
    tr_start: int | None = None
    tr_end: int | None = None
    departed: int | None = None


@dataclass
class Request:
    rid: str
    unit: str
    iso: bool
    acuity: int
    transport: bool
    arrival: int


@dataclass
class Offer:
    oid: str
    unit: str
    skill: str
    source: str  # "pool" | lender unit name
    start: int
    end: int
    req: int
    conf_tick: int | None = None
    confirmed: bool = False
    present: bool | None = None


@dataclass
class Unit:
    name: str
    beds: list[str]
    roster: dict[str, list[int]]  # skill -> staff per absolute hour index
    minimum: dict[str, int]


class Provider(Protocol):
    def auth_tick(self, eng: Engine, st: Stay) -> int: ...
    def ready_tick(self, eng: Engine, st: Stay) -> int: ...
    def confirm_tick(self, eng: Engine, kind: str, ref: str, req: int) -> int: ...
    def transport_end(self, eng: Engine, st: Stay) -> int: ...
    def cleaning_end(self, eng: Engine, bed: Bed) -> int: ...
    def presence(self, eng: Engine, off: Offer) -> bool: ...
    def arrivals(self, eng: Engine, unit: str, hour: int) -> list[tuple[bool, int, bool]]: ...
    def care(self, eng: Engine, st: Stay, hour: int) -> tuple[float, float]: ...
    def cleaning_capacity_drop(self, eng: Engine, tick: int) -> int: ...


@dataclass
class Plan:
    """Decision at an instant: a1 coordinate transports now; a2 cleaning mode; a3 reinforcement."""

    coordinate: bool = False
    cleaning: str = "fifo"  # fifo | compat
    reinforcement: str = "none"  # none | pool_IDE_A | pool_IDE_B | lend_IDE_B_A

    @property
    def cid(self) -> str:
        return f"{int(self.coordinate)}|{self.cleaning}|{self.reinforcement}"


A3_OPTIONS = ("none", "pool_IDE_A", "pool_IDE_B", "lend_IDE_B_A")


def candidates() -> list[Plan]:
    """The 16 public candidates; index 0 is the habitual practice / keep plan (a0)."""
    return [Plan(c, m, r) for c in (False, True) for m in ("fifo", "compat") for r in A3_OPTIONS]


@dataclass
class Engine:
    units: dict[str, Unit]
    beds: dict[str, Bed]
    c_tr: int
    c_cl: int
    tick: int = 0
    stays: dict[str, Stay] = field(default_factory=dict)
    queue: dict[str, list[Request]] = field(default_factory=dict)
    offers: dict[str, Offer] = field(default_factory=dict)
    tr_service: list[str] = field(default_factory=list)
    cleaning_mode: str = "fifo"
    cleaning_mode_until: int = -1
    rejected: int = 0
    rejections: dict[str, int] = field(default_factory=dict)
    log: list[tuple[int, str, str, dict[str, Any]]] = field(default_factory=list)
    emit_log: bool = True
    # hourly accounting (absolute hour -> value)
    demand: dict[tuple[str, str, int], float] = field(default_factory=dict)
    capacity: dict[tuple[str, str, int], int] = field(default_factory=dict)
    waiting_ticks: dict[str, int] = field(default_factory=dict)
    hourly: list[dict[str, Any]] = field(default_factory=list)
    on_event: Callable[[int, str, str, dict[str, Any]], None] | None = None
    _seq: int = 0

    # ------------------------------------------------------------------ helpers
    def _reject(self, reason: str) -> None:
        self.rejected += 1
        self.rejections[reason] = self.rejections.get(reason, 0) + 1

    def emit(self, kind: str, subject: str, **value: Any) -> None:
        if self.emit_log:
            self.log.append((self.tick, kind, subject, value))
        if self.on_event is not None:
            self.on_event(self.tick, kind, subject, value)

    def clone(self) -> Engine:
        cb = self.on_event
        self.on_event = None
        out = copy.deepcopy(self)
        self.on_event = cb
        out.log = []
        out.hourly = []
        return out

    def free_beds(self, unit: str) -> list[Bed]:
        return [self.beds[b] for b in self.units[unit].beds if self.beds[b].state == "free"]

    # ------------------------------------------------------------------ actions
    def apply_plan(self, plan: Plan, prov: Provider) -> None:
        """Planner actions at the current tick (never medical decisions)."""
        if plan.coordinate:
            for st in sorted(self.stays.values(), key=lambda s: s.sid):
                if st.departed is None and st.authorised and st.transport and st.tr_req is None:
                    self.request_transport(st, prov)
        if plan.cleaning == "compat":
            self.cleaning_mode, self.cleaning_mode_until = "compat", self.tick + 24 * TPH
        if plan.reinforcement != "none":
            self.request_reinforcement(plan.reinforcement, prov)

    def request_transport(self, st: Stay, prov: Provider) -> bool:
        if (
            st.departed is not None
            or st.tr_req is not None
            or not st.authorised
            or not st.transport
        ):
            self._reject("transport_request_precondition")
            return False
        st.tr_req = self.tick
        st.tr_conf = prov.confirm_tick(self, "transport", st.sid, self.tick)
        self.emit("transport_requested", st.sid, unit=st.unit)
        return True

    def lender_ok(self, lender: str, skill: str, start: int, end: int) -> bool:
        u = self.units[lender]
        lent = [o for o in self.offers.values() if o.source == lender and o.skill == skill]
        for h in range(start // TPH, (end + TPH - 1) // TPH):
            out = sum(1 for o in lent if o.start // TPH <= h < (o.end + TPH - 1) // TPH)
            if u.roster[skill][h] - out - 1 < u.minimum[skill]:
                return False
        return True

    def request_reinforcement(self, option: str, prov: Provider) -> bool:
        start = (self.tick // TPH + 1) * TPH
        end = start + 4 * TPH
        if option.startswith("pool_"):
            _, skill, unit = option.split("_")
            source = "pool"
        elif option == "lend_IDE_B_A":
            skill, unit, source = "IDE", "A", "B"
            if "B" not in self.units or not self.lender_ok("B", skill, start, end):
                self._reject("lender_minimum")
                return False
        else:
            self._reject("bad_option")
            return False
        if unit not in self.units:
            self._reject("unknown_unit")
            return False
        oid = f"O{unit}{skill}{source}@{start}"
        if oid in self.offers:  # offer_key uniqueness: never counted twice
            self._reject("duplicate_offer")
            return False
        off = Offer(oid, unit, skill, source, start, end, self.tick)
        if source == "pool":
            off.conf_tick = prov.confirm_tick(self, "offer", oid, self.tick)
        else:
            off.conf_tick, off.confirmed = (
                self.tick,
                True,
            )  # presence drawn at slot start (always True)
        self.offers[oid] = off
        self.emit(
            "offer_requested", oid, unit=unit, skill=skill, source=source, start=start, end=end
        )
        if source != "pool":
            self.emit("offer_confirmed", oid)
        return True

    # ------------------------------------------------------------------ dynamics
    def place(self, req: Request, bed: Bed, prov: Provider) -> None:
        if bed.state != "free" or (req.iso and not bed.iso) or bed.unit != req.unit:
            self._reject("placement_precondition")
            return
        sid = f"S{req.rid[1:]}"
        st = Stay(sid, req.unit, bed.bed_id, req.acuity, req.iso, req.transport, self.tick)
        bed.state, bed.stay = "occ", sid
        self.stays[sid] = st
        st.auth_tick = prov.auth_tick(self, st)
        key = (req.unit, "IDE", self.tick // TPH)
        self.demand[key] = self.demand.get(key, 0.0) + ADMISSION_WORK_MIN
        self.emit(
            "placed",
            sid,
            rid=req.rid,
            bed=bed.bed_id,
            unit=req.unit,
            acuity=req.acuity,
            iso=req.iso,
            transport=req.transport,
        )

    def depart(self, st: Stay) -> None:
        bed = self.beds[st.bed]
        if st.departed is not None or bed.stay != st.sid or bed.state != "occ" or not st.ready:
            self._reject("departure_precondition")
            return
        st.departed = self.tick
        bed.state, bed.stay, bed.dirty_tick = "dirty", None, self.tick
        key = (st.unit, "IDE", self.tick // TPH)
        self.demand[key] = self.demand.get(key, 0.0) + DISCHARGE_WORK_MIN
        self.emit("departure", st.sid, bed=bed.bed_id, unit=st.unit)
        self.emit("bed_dirty", bed.bed_id, unit=bed.unit)

    def step(self, prov: Provider) -> None:
        """Advance one tick: apply all events due at self.tick, then increment."""
        t = self.tick
        hour = t // TPH
        for off in self.offers.values():  # presence decided at slot start, BEFORE hourly capacity
            if not off.confirmed and off.conf_tick is not None and off.conf_tick <= t:
                off.confirmed = True
                self.emit("offer_confirmed", off.oid)
            if off.confirmed and off.present is None and off.start <= t:
                off.present = prov.presence(self, off)
                self.emit(
                    "offer_present" if off.present else "offer_absent",
                    off.oid,
                    unit=off.unit,
                    skill=off.skill,
                )
        if t % TPH == 0:
            self._hour_start(prov, hour)
        # authorisations and readiness (exogenous times from the provider)
        for st in sorted(self.stays.values(), key=lambda s: s.sid):
            if st.departed is not None:
                continue
            if not st.authorised and st.auth_tick is not None and st.auth_tick <= t:
                st.authorised = True
                st.ready_tick = prov.ready_tick(self, st)
                self.emit("authorised", st.sid, unit=st.unit)
            if st.authorised and not st.ready and st.ready_tick is not None and st.ready_tick <= t:
                st.ready = True
                self.emit("ready", st.sid, unit=st.unit)
                if not st.transport:
                    self.depart(st)
        # habitual transport requests
        if t % TPH == 0 and local_hour(t) in HABITUAL_TRANSPORT_HOURS:
            for st in sorted(self.stays.values(), key=lambda s: s.sid):
                if st.departed is None and st.ready and st.transport and st.tr_req is None:
                    self.request_transport(st, prov)
        # confirmations
        for st in self.stays.values():
            if (
                st.tr_req is not None
                and not st.tr_accepted
                and st.tr_conf is not None
                and st.tr_conf <= t
            ):
                st.tr_accepted = True
                self.emit("transport_accepted", st.sid, unit=st.unit)
        # transport completions then starts
        for sid in list(self.tr_service):
            st = self.stays[sid]
            if st.tr_end is not None and st.tr_end <= t:
                self.tr_service.remove(sid)
                self.emit("transport_done", sid, unit=st.unit)
                self.depart(st)
        waiting = sorted(
            (
                s
                for s in self.stays.values()
                if s.departed is None and s.ready and s.tr_accepted and s.tr_start is None
            ),
            key=lambda s: (max(s.ready_tick or 0, s.tr_conf or 0), s.sid),
        )
        for st in waiting:
            if len(self.tr_service) >= self.c_tr:
                break
            st.tr_start = t
            st.tr_end = max(t + 1, prov.transport_end(self, st))
            self.tr_service.append(st.sid)
            self.emit("transport_start", st.sid, unit=st.unit)
        # cleaning completions then starts
        for bed in self.beds.values():
            if bed.state == "cleaning" and bed.clean_end is not None and bed.clean_end <= t:
                bed.state, bed.clean_start, bed.clean_end, bed.dirty_tick = "free", None, None, None
                self.emit("cleaning_done", bed.bed_id, unit=bed.unit)
        if self.cleaning_mode_until < t:
            self.cleaning_mode = "fifo"
        lo, hi = CLEANING_HOURS
        if lo <= local_hour(t) < hi:
            cap = max(0, self.c_cl - prov.cleaning_capacity_drop(self, t))
            busy = sum(1 for b in self.beds.values() if b.state == "cleaning")
            dirty = [b for b in self.beds.values() if b.state == "dirty"]
            iso_wait = {u for u, q in self.queue.items() if any(r.iso for r in q)}
            if self.cleaning_mode == "compat":
                dirty.sort(
                    key=lambda b: (not (b.iso and b.unit in iso_wait), b.dirty_tick, b.bed_id)
                )
            else:
                dirty.sort(key=lambda b: (b.dirty_tick, b.bed_id))
            for bed in dirty:
                if busy >= cap:
                    break
                bed.state, bed.clean_start = "cleaning", t
                bed.clean_end = max(t + 1, prov.cleaning_end(self, bed))
                busy += 1
                self.emit("cleaning_start", bed.bed_id, unit=bed.unit)
        # placements (FIFO per unit, first compatible free bed)
        for unit, q in self.queue.items():
            for req in list(q):
                free = self.free_beds(unit)
                cand = (
                    [b for b in free if b.iso]
                    if req.iso
                    else sorted(free, key=lambda b: (b.iso, b.bed_id))
                )
                if cand:
                    q.remove(req)
                    self.place(
                        req, sorted(cand, key=lambda b: b.bed_id)[0] if req.iso else cand[0], prov
                    )
            self.waiting_ticks[unit] = self.waiting_ticks.get(unit, 0) + len(q)
        self.tick += 1

    def _hour_start(self, prov: Provider, hour: int) -> None:
        # arrivals
        for unit in sorted(self.units):
            for i, (iso, acuity, transport) in enumerate(prov.arrivals(self, unit, hour)):
                rid = f"R{unit}{hour:04d}_{i}"
                req = Request(rid, unit, iso, acuity, transport, self.tick)
                self.queue.setdefault(unit, []).append(req)
                self.emit(
                    "request_arrival", rid, unit=unit, iso=iso, acuity=acuity, transport=transport
                )
        # care demand of present stays + staff capacity for this hour
        for st in sorted(self.stays.values(), key=lambda s: s.sid):
            if st.departed is None:
                ide, as_ = prov.care(self, st, hour)
                for skill, v in (("IDE", ide), ("AS", as_)):
                    k = (st.unit, skill, hour)
                    self.demand[k] = self.demand.get(k, 0.0) + v
                self.emit("care_due", st.sid, hour=hour, ide=ide, as_=as_)
        for name, u in self.units.items():
            for skill in SKILLS:
                staff = u.roster[skill][hour]
                for off in self.offers.values():
                    if (
                        off.skill == skill
                        and off.start // TPH <= hour < (off.end + TPH - 1) // TPH
                        and off.present
                    ):
                        if off.unit == name:
                            staff += 1
                        if off.source == name:
                            staff -= 1
                self.capacity[(name, skill, hour)] = staff

    def snapshot_hour(self) -> dict[str, Any]:
        """Business levels at the current tick (used for hourly targets)."""
        out: dict[str, Any] = {"tick": self.tick}
        for name, u in self.units.items():
            beds = [self.beds[b] for b in u.beds]
            out[name] = {
                "occupancy": sum(b.state == "occ" for b in beds),
                "free_beds": sum(b.state == "free" for b in beds),
                "cleaning_queue": sum(b.state in ("dirty", "cleaning") for b in beds),
                "transport_queue": sum(
                    1
                    for s in self.stays.values()
                    if s.unit == name
                    and s.departed is None
                    and s.tr_req is not None
                    and s.tr_end is None
                ),
                "admission_queue": len(self.queue.get(name, [])),
            }
        return out

    def run(self, prov: Provider, until: int, record_hourly: bool = False) -> None:
        while self.tick < until:
            if record_hourly and self.tick % TPH == 0:
                self.hourly.append(self.snapshot_hour())
            self.step(prov)


def uncovered(eng: Engine, hours: range) -> float:
    total = 0.0
    for name in eng.units:
        for skill in SKILLS:
            for h in hours:
                d = eng.demand.get((name, skill, h), 0.0)
                c = eng.capacity.get((name, skill, h))
                if c is None:
                    continue
                total += max(0.0, d - 60.0 * c)
    return total


WAIT_WEIGHT = 15.0  # caregiver-minutes per patient-hour waiting (U-HOWM-1, hypothesis)


def objective_u(eng: Engine, start_tick: int, waiting_at_start: dict[str, int]) -> float:
    """U over (start, start+24h]: uncovered care minutes + 15 x patient-hours waiting."""
    h0 = start_tick // TPH
    unc = uncovered(eng, range(h0, h0 + 24))
    wait_ticks = sum(eng.waiting_ticks.get(u, 0) - waiting_at_start.get(u, 0) for u in eng.units)
    return unc + WAIT_WEIGHT * wait_ticks / TPH
