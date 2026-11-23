"""HOWM-INT-1 world: parametrisable N-unit hospital (2 / 4 / 8 / 12 units) built on the frozen HOWM-1
operator (15-minute ticks). Mechanisms (each with a role, physical units, parameters and a coherence test):

  M1 shared cleaning team (c_cl agents, minutes per bed; existing)       M2 shared transport team (existing)
  M3 isolation bed compatibility (existing)                               M4 unit staff rosters + pool/lending (existing,
  M5 internal downstream: transfer of a stay from unit i to unit j;          generalised to any unit)
     the patient KEEPS its bed in i until placed in j (bed-blocking)       M6 external downstream (aval): stays flagged
  M7 public planned cleaning-capacity calendar (B-FRAG)                       'aval' leave only within a daily number of
  M8 hidden slowdown regimes and load-dependent readiness (existing m2/m3)    external slots shared by all units

Two-unit mode = the B-FRAG 2 world (D2 design, units A/B, same keys and laws); M5/M6 off.
Every exogenous draw is keyed by (episode key, realisation, primitive, entity/event) -- never by call
order -- so all policies share the same exogenous events (common random numbers)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hospitalos.bfrag import core as K
from hospitalos.howm import generator as G
from hospitalos.howm.generator import refresh_private
from hospitalos.howm.history import PublicStream
from hospitalos.howm.keys import key, u
from hospitalos.howm.world import SKILLS, TPD, TPH, Bed, Engine, Offer, Request, Stay, Unit

ROOT = Path(__file__).resolve().parents[3]
D2 = json.loads((ROOT / "docs/howm2/bfrag/DESIGN_D2.json").read_text())
HORIZON_TICKS = (72 + 168 + 48) * TPH  # latest origin 72 h + 168 h + margin -> rosters long enough
ROSTER_HOURS = HORIZON_TICKS // TPH + 24
REGIMES = ("nominal", "tense", "fragile")
BOTTLENECKS = ("cleaning", "transport", "aval", "transfer", "calendar")
ZERO_LAG = {"transport_requested", "offer_requested", "plan", "static"}


def unit_names(n: int) -> list[str]:
    return ["A", "B"] if n == 2 else [f"U{i}" for i in range(n)]


@dataclass
class IntSpec:
    """Structure (establishment) spec; an EPISODE sets ``ekey`` (all exogenous draws of the episode)."""

    part: str
    idx: int
    n: int
    units: list[str]
    ekey: int
    start_utc: str
    beds: dict[str, int]
    iso_beds: dict[str, int]
    nominal: dict[str, int]
    c_tr: int
    c_cl: int
    theta: dict[str, float]
    mech: dict[str, Any]
    drop: dict = field(default_factory=dict)
    transfer: dict[str, dict[str, float]] = field(default_factory=dict)  # origin -> {dest: probability}
    p_aval: dict[str, float] = field(default_factory=dict)
    aval_slots_per_day: int = 0
    lend_pairs: list[tuple[str, str]] = field(default_factory=list)
    family: str = ""
    regime: str = ""
    bottlenecks: tuple[str, ...] = ()
    population: str = "REF"
    skey: int = 0  # structure key (static draws)


# ------------------------------------------------------------------------------ structures
def _r(sk: int, name: str, lo: float, hi: float) -> float:
    return lo + (hi - lo) * u(sk, 0, "int-struct", name)


def two_unit_structure(part: str, idx: int) -> IntSpec:
    """B-FRAG 2 world (D2 families) with the family drawn by key (decorrelated from the index)."""
    K.register()
    from hospitalos.bfrag2w import core_w  # registers B-FRAG 2 partitions

    core_w.register()
    if part not in G.PARTITION_SIZES:
        G.PARTITION_SIZES[part] = 100000
        G.POPULATION_OF[part] = "REF"
    sk = key("INT-struct", part, idx)
    fam = K.FAMILIES[int(u(sk, 0, "family", "") * len(K.FAMILIES))]
    w = K.make_world(part, idx, D2, family=fam)
    sp = w.spec
    return IntSpec(part, idx, 2, ["A", "B"], sp.ekey, sp.start_utc, dict(sp.beds), dict(sp.iso_beds), dict(w.nominal), sp.c_tr, sp.c_cl,
                   dict(sp.theta), dict(sp.mech), dict(w.drop), family=fam, regime=_two_unit_regime(fam), skey=sp.ekey)


def _two_unit_regime(fam: str) -> str:
    return {"SC6_low_load": "nominal", "SC4_high_load_absorbable": "tense", "SC5_drop_with_margin": "tense"}.get(fam, "fragile")


def n_unit_structure(part: str, idx: int, n: int, regime: str | None = None, bottlenecks: tuple[str, ...] | None = None,
                     intensity: float = 1.0) -> IntSpec:
    """N-unit structure (n in 4, 8, 12). Regime and bottleneck set drawn by key unless forced (test panels).

    Regimes act on the buffer (physical beds / nominal beds) and load: nominal 0.40-0.60, tense 0.25-0.40,
    fragile 0.15-0.30 plus 1-2 bottlenecks; ``intensity`` scales bottleneck severity (new-combination tests)."""
    sk = key("INT-struct", part, idx)
    if regime is None:
        x = u(sk, 0, "regime", "")
        regime = "nominal" if x < 0.3 else ("tense" if x < 0.65 else "fragile")
    if bottlenecks is None:
        nb = 0 if regime == "nominal" else (1 if regime == "tense" else 1 + int(u(sk, 0, "nb", "") < 0.5))
        pool = list(BOTTLENECKS)
        chosen: list[str] = []
        for k in range(nb):
            j = int(u(sk, 0, "bneck", k) * len(pool))
            chosen.append(pool.pop(j))
        bottlenecks = tuple(sorted(chosen))
    names = unit_names(n)
    blo, bhi = {"nominal": (0.40, 0.60), "tense": (0.25, 0.40), "fragile": (0.15, 0.30)}[regime]
    nominal = {un: 8 + int(u(sk, 0, "beds", un) * 17) for un in names}
    beds = {un: m + int(round(_r(sk, f"buffer_{un}", blo, bhi) * m)) for un, m in nominal.items()}
    iso = {un: max(1, round(0.25 * b)) for un, b in beds.items()}
    total = sum(beds.values())
    c_cl = max(1, round(total / 25 * _r(sk, "c_cl", 0.8, 1.2)))
    c_tr = max(1, round(total / 22 * _r(sk, "c_tr", 0.8, 1.2)))
    theta = {"los_days": _r(sk, "los", 2.5, 5.0), "ready_h": _r(sk, "ready", 1.0, 5.0), "tr_min": _r(sk, "tr", 30, 70),
             "cl_min": _r(sk, "cl", 30, 60), "conf_tr_min": _r(sk, "conf_tr", 15, 90), "conf_off_min": _r(sk, "conf_off", 30, 240),
             "noshow": _r(sk, "noshow", 0.0, 0.25), "arr_mult": _r(sk, "arr", 0.9, 1.1), "care_mult": _r(sk, "care", 0.85, 1.15),
             "lag_min": _r(sk, "lag", 0.0, 60.0)}
    if regime != "nominal":
        theta["arr_mult"] = _r(sk, "arr_t", 1.0, 1.12)
    simple = u(sk, 0, "mix", "simple") < 0.3
    mech = {"m2": (not simple) and u(sk, 0, "mix", "m2") < 0.5 / 0.7, "m2_common": False, "slow": 1.8,
            "m3_kappa": 0.0 if simple else 0.5, "m5_drop": False, "simple": simple}
    s = intensity
    drop: dict = {}
    if "cleaning" in bottlenecks:
        theta["cl_min"] = min(90.0, _r(sk, "cl_b", 60, 75) * s)
        c_cl = max(1, round(c_cl * 0.75 / max(1.0, s)))
    if "transport" in bottlenecks:
        theta["tr_min"] = min(120.0, _r(sk, "tr_b", 70, 90) * s)
        c_tr = max(1, round(c_tr * 0.75 / max(1.0, s)))
    if "calendar" in bottlenecks:
        drop = {"day": 3, "from_h": 6, "to_h": 22, "minus": max(1, round(c_cl * 0.34 * s))}
    # topology: the first half of the units are 'upstream' (admission) units feeding downstream wards
    up = names[: max(1, n // 2)]
    down = names[max(1, n // 2):]
    transfer: dict[str, dict[str, float]] = {}
    p_tr_base = 0.10 if "transfer" not in bottlenecks else min(0.5, 0.25 * s)
    for i, a in enumerate(up):
        d1 = down[i % len(down)]
        d2 = down[(i + 1) % len(down)]
        transfer[a] = {d1: p_tr_base * 0.7, d2: p_tr_base * 0.3} if d1 != d2 else {d1: p_tr_base}
    p_aval = {un: (0.30 if "aval" in bottlenecks else 0.10) * (1.0 if un in down else 0.5) for un in names}
    # daily external downstream slots: expected aval discharges/day x margin (scarce if bottleneck)
    exp_aval = sum(nominal[un] * 0.93 / theta["los_days"] * p_aval[un] for un in names)
    margin = (0.85 / max(1.0, s)) if "aval" in bottlenecks else 1.6
    slots = max(1, int(round(exp_aval * margin)))
    lend_pairs = [(down[i % len(down)], up[i % len(up)]) for i in range(max(len(up), len(down)))]
    mondays = ["2027-01-04", "2027-01-11", "2027-01-18", "2027-01-25", "2027-02-01", "2027-02-08"]
    start = f"{mondays[int(u(sk, 0, 'start', '') * len(mondays))]}T00:00:00+01:00"
    fam = f"N{n}_{regime}_" + ("+".join(bottlenecks) or "none")
    return IntSpec(part, idx, n, names, sk, start, beds, iso, nominal, c_tr, c_cl, theta, mech, drop, transfer, p_aval, slots,
                   lend_pairs, fam, regime, tuple(bottlenecks), skey=sk)


def structure(part: str, idx: int, n: int, **kw: Any) -> IntSpec:
    return two_unit_structure(part, idx) if n == 2 else n_unit_structure(part, idx, n, **kw)


def episode(spec: IntSpec, e: int) -> IntSpec:
    from dataclasses import replace

    return replace(spec, ekey=key("INT-ep", spec.part, spec.idx, e))


# ------------------------------------------------------------------------------ provider
@dataclass
class ProvN(G.TruthProvider):
    """Truth law: frozen TruthProvider + nominal-capacity arrivals (B-FRAG law) + routing draws (M5/M6)."""

    def arrivals(self, eng: Engine, unit: str, hour: int) -> list:
        sp = self.spec
        mean = sp.nominal[unit] * 0.93 / (self.th["los_days"] * 24) * G.HOUR_PROFILE[hour % 24] * self.th["arr_mult"]
        from scipy.stats import nbinom

        n = int(nbinom.ppf(self._u("arrivals", unit, hour), 3.0, 3.0 / (3.0 + mean)))
        out = []
        for i in range(n):
            a = self._u("acuity", unit, hour, i)
            acuity = 1 if a < G.ACUITY_P[0] else (2 if a < G.ACUITY_P[0] + G.ACUITY_P[1] else 3)
            out.append((self._u("iso", unit, hour, i) < G.P_ISO, acuity, self._u("tr", unit, hour, i) < G.P_TRANSPORT))
        return out

    def route(self, st: Stay) -> tuple[str | None, bool]:
        """Destination of a stay at placement: transfer to another unit (M5), external downstream (M6) or home.
        Drawn ONCE per stay (keyed by the stay id, realisation-independent: a structural attribute)."""
        sp = self.spec
        x = u(sp.ekey, 0, "route", st.sid)
        acc = 0.0
        if not st.sid.startswith("SS"):  # a transferred stay (id "SS...") is not transferred again
            for dest, p in sorted(sp.transfer.get(st.unit, {}).items()):
                acc += p
                if x < acc:
                    return dest, False
        return None, u(sp.ekey, 0, "aval", st.sid) < sp.p_aval.get(st.unit, 0.0)


# ------------------------------------------------------------------------------ engine
class EngineN(Engine):
    """Frozen operator + M5 (transfer with bed holding), M6 (daily external slots), commitments (scheduled
    capacity: +k cleaning / transport agents on [start, end); staff offers), budgets, public calendar M7."""

    def setup(self, spec: IntSpec) -> EngineN:
        self.spec_meta = {"aval_slots": spec.aval_slots_per_day, "drop": dict(spec.drop), "lend_pairs": list(spec.lend_pairs)}
        self.base_c_cl, self.base_c_tr = self.c_cl, self.c_tr
        self.aval_used: dict[int, int] = {}
        self.aval_blocked: list[str] = []
        self.transfer_pending: dict[str, str] = {}  # transfer request id -> origin stay id
        self.commitments: list[dict] = []
        self.coord_ticks: list[int] = []
        self.hold_bed = True  # propagation control: False releases the origin bed at the transfer request
        return self

    # ---- M5 / M6
    def place(self, req: Request, bed: Bed, prov: Any) -> None:
        n_before = len(self.stays)
        super().place(req, bed, prov)
        if len(self.stays) == n_before:
            return
        st = self.stays[f"S{req.rid[1:]}"]
        if req.rid in self.transfer_pending:
            origin = self.stays[self.transfer_pending.pop(req.rid)]
            if origin.departed is None:
                Engine.depart(self, origin)  # the origin bed is released only now (bed-blocking)
        dest, aval = prov.route(st) if hasattr(prov, "route") else (None, False)
        st.dest, st.aval, st.transfer_requested = dest, aval, False
        if dest is not None:
            st.transport = False  # internal move by unit staff; the destination bed is the constraint
        self.emit("route", st.sid, unit=st.unit, dest=dest or "", aval=aval)

    def depart(self, st: Stay) -> None:
        dest = getattr(st, "dest", None)
        if dest is not None:
            if not st.transfer_requested and st.ready and st.departed is None:
                rid = f"T{st.sid}"  # placed stay id will be "S" + origin id ("SS...")
                self.transfer_pending[rid] = st.sid
                st.transfer_requested = True
                self.queue.setdefault(dest, []).append(Request(rid, dest, st.iso, st.acuity, False, self.tick))
                self.emit("request_arrival", rid, unit=dest, iso=st.iso, acuity=st.acuity, transport=False, from_sid=st.sid)
                if not getattr(self, "hold_bed", True):
                    Engine.depart(self, st)  # control: bed released now, the patient waits for the destination elsewhere
            return
        if getattr(st, "aval", False) and st.departed is None:
            day = self.tick // TPD
            if self.aval_used.get(day, 0) < self.aval_cap(self.tick) and (not self.aval_blocked or self.aval_blocked[0] == st.sid):
                self.aval_used[day] = self.aval_used.get(day, 0) + 1
                if st.sid in self.aval_blocked:
                    self.aval_blocked.remove(st.sid)
                Engine.depart(self, st)
            elif st.sid not in self.aval_blocked:
                self.aval_blocked.append(st.sid)
            return
        Engine.depart(self, st)

    # ---- commitments (scheduled capacity) and calendar
    def aval_cap(self, t: int) -> int:
        """External downstream slots of the day: structural slots + purchased slots active at t (commitment 'av')."""
        return self.spec_meta["aval_slots"] + self.active_extra("av", t)

    def active_extra(self, res: str, t: int) -> int:
        return sum(c["k"] for c in self.commitments if c["res"] == res and c["start"] <= t < c["end"])

    def step(self, prov: Any) -> None:
        t = self.tick
        if t % TPH == 0 and self.aval_blocked:
            for sid in list(self.aval_blocked):
                st = self.stays[sid]
                if self.aval_used.get(t // TPD, 0) >= self.aval_cap(t):
                    break
                self.aval_blocked.remove(sid)
                self.aval_used[t // TPD] = self.aval_used.get(t // TPD, 0) + 1
                Engine.depart(self, st)
        self.c_cl = self.base_c_cl + self.active_extra("cl", t)
        self.c_tr = self.base_c_tr + self.active_extra("tr", t)
        super().step(_Cal(prov, self.spec_meta["drop"]))
        self.c_cl, self.c_tr = self.base_c_cl, self.base_c_tr

    def add_staff(self, unit: str, start: int, end: int, prov: Any, source: str = "pool") -> bool:
        oid = f"O{unit}IDE{source}@{start}"
        if oid in self.offers or unit not in self.units:
            self._reject("duplicate_offer")
            return False
        if source != "pool" and not self.lender_ok(source, "IDE", start, end):
            self._reject("lender_minimum")
            return False
        off = Offer(oid, unit, "IDE", source, start, end, self.tick)
        if source == "pool":
            off.conf_tick = prov.confirm_tick(self, "offer", oid, self.tick)
        else:
            off.conf_tick, off.confirmed = self.tick, True
        self.offers[oid] = off
        self.emit("offer_requested", oid, unit=unit, skill="IDE", source=source, start=start, end=end)
        if source != "pool":
            self.emit("offer_confirmed", oid)
        return True


class _Cal:
    """Provider proxy adding the PUBLIC planned cleaning-capacity reduction (M7, B-FRAG WithCalendar law)."""

    def __init__(self, prov: Any, drop: dict):
        self._p, self._drop = prov, drop

    def __getattr__(self, n: str) -> Any:
        return getattr(self._p, n)

    def cleaning_capacity_drop(self, eng: Engine, tick: int) -> int:
        return self._p.cleaning_capacity_drop(eng, tick) + K.drop_at(self._drop, tick)


def initial_engine(spec: IntSpec, prov: ProvN) -> EngineN:
    units, beds = {}, {}
    for un in spec.units:
        ids = [f"B{un}{i:02d}" for i in range(spec.beds[un])]
        for i, b in enumerate(ids):
            beds[b] = Bed(b, un, iso=i < spec.iso_beds[un])
        roster = {sk: G.roster_for(spec.beds[un], sk, ROSTER_HOURS) for sk in SKILLS}
        units[un] = Unit(un, ids, roster, {sk: min(roster[sk]) for sk in SKILLS})
    eng = EngineN(units, beds, spec.c_tr, spec.c_cl).setup(spec)
    for un in spec.units:
        for b in units[un].beds:
            thr = 0.9 if spec.n == 2 else 0.9 * spec.nominal[un] / spec.beds[un] + 0.05  # 2 units: frozen HOWM-1 rule
            if u(spec.ekey, 0, "init_occ", b) < thr:
                bed = beds[b]
                sid = f"S{un}init_{b}"
                a = u(spec.ekey, 0, "init_acuity", b)
                acuity = 1 if a < 0.4 else (2 if a < 0.8 else 3)
                st = Stay(sid, un, b, acuity, bed.iso and u(spec.ekey, 0, "init_iso", b) < 0.5,
                          u(spec.ekey, 0, "init_tr", b) < G.P_TRANSPORT, -int(u(spec.ekey, 0, "init_age", b) * 4 * TPD))
                bed.state, bed.stay = "occ", sid
                eng.stays[sid] = st
                st.auth_tick = prov.auth_tick(eng, st)
                st.dest, st.aval = prov.route(st)
                st.transfer_requested = False
                if st.dest is not None:
                    st.transport = False
    return eng


# ------------------------------------------------------------------------------ observation stream
class Recorder:
    """Public observations of ONE trajectory (event_min, avail_min, kind, subject, unit, value); the lag of an
    event is keyed by (episode, realisation, kind, subject, tick)."""

    def __init__(self, spec: IntSpec, r: int):
        self.spec, self.r, self.obs = spec, r, []

    def __call__(self, tick: int, kind: str, subject: str, value: dict) -> None:
        ev = tick * 15 + (60 if kind == "care_due" else 0)
        lag = 0 if kind in ZERO_LAG or kind == "route" else int(
            -self.spec.theta["lag_min"] * math.log(1 - u(self.spec.ekey, self.r, "lag", kind, subject, tick) * 0.999999))
        self.obs.append((ev, ev + lag, kind, subject, str(value.get("unit", "")), dict(value)))


def static_obs(eng: EngineN, spec: IntSpec) -> list:
    st = {"units": {n: {"beds": [(b, eng.beds[b].iso) for b in un.beds], "roster": {k: v for k, v in un.roster.items()},
                        "minimum": un.minimum} for n, un in eng.units.items()},
          "c_tr": spec.c_tr, "c_cl": spec.c_cl, "start_utc": spec.start_utc, "drop": spec.drop, "aval_slots": spec.aval_slots_per_day,
          "lend_pairs": spec.lend_pairs, "nominal": spec.nominal}
    out = [(0, 0, "static", "establishment", "", st)]
    for s in sorted(eng.stays.values(), key=lambda x: x.sid):
        out.append((0, 0, "placed", s.sid, s.unit, {"bed": s.bed, "unit": s.unit, "acuity": s.acuity, "iso": s.iso, "transport": s.transport,
                                                     "placed_min": s.placed_tick * 15}))
        out.append((0, 0, "route", s.sid, s.unit, {"unit": s.unit, "dest": s.dest or "", "aval": s.aval}))
    return out


class PublicStreamN(PublicStream):
    """Frozen public replay + the public extensions: routing of a stay (destination, external downstream),
    transfer requests (origin stay), commitments (plan events)."""

    def __init__(self, observations: list):
        super().__init__(observations)
        self.routes: dict[str, dict] = {}
        self.transfer_from: dict[str, str] = {}

    def _bed(self, bed: str, ev: int, state: str, **extra: Any) -> None:
        """Resolve same-tick lifecycle events in physical, not delivery, order.

        Within a tick, Engine.step departs, then completes cleanings, then starts cleanings, then places patients.
        The phase table ranks dirty < cleaning < free < occ: a bed cannot both start and complete a cleaning in
        the same tick (clean_end >= clean_start + 1), so that pair never collides on one bed and the table
        orders every same-tick pair that can occur. A delayed cleaning_done must never erase a known same-tick
        placement.
        Event time still takes precedence across distinct ticks.
        """
        phase = {"dirty": 0, "cleaning": 1, "free": 2, "occ": 3}
        old = self.beds.get(bed)
        if old is not None and old.last == ev:
            if phase[state] < phase.get(old.data.get("state"), -1):
                return
        super()._bed(bed, ev, state, **extra)

    def _apply(self, o: tuple) -> None:
        ev, _avail, kind, subj, unit, v = o
        if kind == "route":
            self.routes[subj] = {"dest": v.get("dest") or None, "aval": bool(v.get("aval"))}
            return
        if kind == "request_arrival" and v.get("from_sid"):
            self.transfer_from[subj] = v["from_sid"]
        super()._apply(o)

    @staticmethod
    def _implied_departure(eng: EngineN, s: Any, tick: int) -> None:
        """Apply a departure implied by a later public stage: the stay leaves at ``tick`` and its bed becomes dirty
        then, unless the public bed record already shows a later state for that bed."""
        s.departed = tick
        if s.sid in eng.tr_service:
            eng.tr_service.remove(s.sid)
        bed = eng.beds.get(s.bed)
        if bed is not None and bed.state == "occ" and bed.stay == s.sid:
            bed.state, bed.stay, bed.dirty_tick = "dirty", None, tick

    def to_engine_n(self, t_tick: int) -> EngineN:
        base = self.to_engine(t_tick * 15 - 1)  # observations available strictly before the decision tick
        base.tick = t_tick
        eng = EngineN.__new__(EngineN)
        eng.__dict__.update(base.__dict__)
        st = self.static or {}
        eng.spec_meta = {"aval_slots": st.get("aval_slots", 0), "drop": dict(st.get("drop") or {}), "lend_pairs": st.get("lend_pairs", [])}
        eng.base_c_cl, eng.base_c_tr = eng.c_cl, eng.c_tr
        eng.aval_used, eng.aval_blocked, eng.commitments, eng.coord_ticks = {}, [], [], []
        eng.transfer_pending = {rid: sid for rid, sid in self.transfer_from.items()
                                if rid not in self.placed_rids and sid in eng.stays}
        for sid, s in eng.stays.items():
            r = self.routes.get(sid, {"dest": None, "aval": False})
            s.dest, s.aval = r["dest"], r["aval"]
            s.transfer_requested = any(v == sid for v in self.transfer_from.values())
            pub = self.stays.get(sid, {})
            # A later public stage implies its prerequisites, even if their
            # individual notifications have not arrived yet.
            transport_time = pub.get("transport_start", pub.get("transport_done"))
            ready_time = pub.get("ready", transport_time)
            if ready_time is not None:
                s.authorised = True
                s.auth_tick = s.auth_tick if s.auth_tick is not None else ready_time // 15
            if transport_time is not None:
                s.ready, s.tr_accepted = True, True
                s.ready_tick = s.ready_tick if s.ready_tick is not None else transport_time // 15
                # the request and its acceptance precede the start: without them the engine would issue a second
                # habitual request for a patient already in transport
                s.tr_req = s.tr_req if s.tr_req is not None else transport_time // 15
                s.tr_conf = s.tr_conf if s.tr_conf is not None else transport_time // 15
                # set even when only the completion is known, so that the engine does not start the transport
                # again; its end time is the known completion (below), and the stay is not in tr_service
                s.tr_start = transport_time // 15
            if "transport_done" in pub:  # completion may arrive before start
                if sid in eng.tr_service:
                    eng.tr_service.remove(sid)
                s.tr_end = pub["transport_done"] // 15
            if s.ready and s.aval and s.departed is None and not s.dest and (not s.transport or "transport_done" in pub):
                eng.aval_blocked.append(sid)  # ready and still present: waiting for an external downstream slot
            elif s.departed is None and not s.dest and not s.aval:
                # the engine departs such a stay at the tick it becomes ready (no transport) or its transport ends;
                # a departure report still in flight must not keep the bed occupied for the whole rollout
                implied = pub.get("transport_done") if s.transport else pub.get("ready")
                if implied is not None:
                    self._implied_departure(eng, s, implied // 15)
        day = t_tick // TPD
        eng.aval_used[day] = sum(1 for sid, s in self.stays.items() if s.get("departure") is not None and s["departure"] // 15 // TPD == day
                                 and self.routes.get(sid, {}).get("aval"))
        for t_plan, p in self.plans:
            if "commit" in p:
                eng.commitments.append(dict(p["commit"]))
            if p.get("coordinate"):
                eng.coord_ticks.append(t_plan // 15)
        return eng


def regime_anchor(prov: ProvN, tick: int) -> dict:
    h = tick // TPH
    if prov.spec.mech["m2_common"]:
        return {"common": (h, prov.regime("transport", h))}
    return {team: (h, prov.regime(team, h)) for team in ("transport", "cleaning")}
