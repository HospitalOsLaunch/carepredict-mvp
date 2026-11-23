"""HOWM-1 generator G_main: populations REF/DIAG, private truth, public observations.

Synthetic only. Every mechanism (m0-m5) is an engineering hypothesis (DESIGN 1.6, NORM N6).
Every draw is keyed by (establishment key, realisation r, primitive, entity) — never by call
order. The generator never imports or reads any model output (T-GEN-09).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import NormalDist
from typing import Any
from zoneinfo import ZoneInfo

from scipy.stats import nbinom

from .keys import key, u
from .world import SKILLS, TPD, TPH, Bed, Engine, Offer, Plan, Stay, Unit, candidates, local_hour

N01 = NormalDist()
PARIS = ZoneInfo("Europe/Paris")
EPISODE_DAYS = 8
EPISODE_TICKS = EPISODE_DAYS * TPD
INSTANT_HOURS = (7, 11, 15, 19)
EVAL_DAY = 5
PARTITION_SIZES = {
    "TRAIN": 48,
    "VAL": 12,
    "DEVTEST": 24,
    "DIAG_DEV": 12,
    "RESERVE_REF": 48,
    "RESERVE_DIAG": 16,
}
POPULATION_OF = {
    "TRAIN": "REF",
    "VAL": "REF",
    "DEVTEST": "REF",
    "DIAG_DEV": "DIAG",
    "RESERVE_REF": "REF",
    "RESERVE_DIAG": "DIAG",
}
SEALED = {"RESERVE_REF", "RESERVE_DIAG"}
CARE_MEAN = {"IDE": {1: 8.0, 2: 12.0, 3: 20.0}, "AS": {1: 10.0, 2: 14.0, 3: 22.0}}
ACUITY_P = (0.4, 0.4, 0.2)
P_ISO, P_TRANSPORT = 0.15, 0.6
HOUR_PROFILE = [
    0.3,
    0.2,
    0.2,
    0.2,
    0.2,
    0.3,
    0.5,
    0.8,
    1.2,
    1.5,
    1.6,
    1.6,
    1.5,
    1.5,
    1.6,
    1.6,
    1.5,
    1.4,
    1.2,
    1.0,
    0.8,
    0.6,
    0.5,
    0.4,
]
_HP = sum(HOUR_PROFILE) / 24.0
HOUR_PROFILE = [x / _HP for x in HOUR_PROFILE]
PRIOR_CENTRE = {
    "los_days": 3.75,
    "ready_h": 3.0,
    "tr_min": 60.0,
    "cl_min": 52.5,
    "conf_tr_min": 67.5,
    "conf_off_min": 135.0,
    "noshow": 0.125,
    "arr_mult": 1.0,
    "care_mult": 1.0,
    "lag_min": 30.0,
}


class SealedPartitionError(RuntimeError):
    pass


def lognormal_minutes(median: float, sigma: float, uu: float) -> float:
    return median * math.exp(sigma * N01.inv_cdf(min(max(uu, 1e-12), 1 - 1e-12)))


def cond_uniform(cdf_elapsed: float, uu: float) -> float:
    """Uniform conditional on exceeding an elapsed quantile (fresh innovation given survival)."""
    return cdf_elapsed + uu * (1.0 - cdf_elapsed)


def lognormal_cdf(x: float, median: float, sigma: float) -> float:
    if x <= 0:
        return 0.0
    return N01.cdf(math.log(x / median) / sigma)


@dataclass(frozen=True)
class EstablishmentSpec:
    partition: str
    index: int
    population: str
    ekey: int
    start_utc: str
    beds: dict[str, int]
    iso_beds: dict[str, int]
    c_tr: int
    c_cl: int
    theta: dict[str, float]
    mech: dict[str, Any]


def establishment(partition: str, index: int, token: str | None = None) -> EstablishmentSpec:
    if partition in SEALED and token != "RESERVE-UNSEALED-BY-PROTOCOL":
        raise SealedPartitionError(f"partition {partition} is sealed (G0): generation refused")
    if partition not in PARTITION_SIZES or not 0 <= index < PARTITION_SIZES[partition]:
        raise ValueError(f"unknown establishment {partition}/{index}")
    pop = POPULATION_OF[partition]
    ek = key("HOWM1", partition, index)

    def r(name: str, lo: float, hi: float) -> float:
        return lo + (hi - lo) * u(ek, 0, "theta", name)

    beds = {un: 8 + int(u(ek, 0, "beds", un) * 17) for un in ("A", "B")}
    iso = {un: max(1, round(0.25 * n)) for un, n in beds.items()}
    c_tr = (1, 2, 2, 3)[int(u(ek, 0, "c_tr", "") * 4)]
    c_cl = 1 + int(u(ek, 0, "c_cl", "") * 2)
    theta = {
        "los_days": r("los", 2.5, 5.0),
        "ready_h": r("ready", 1.0, 5.0),
        "tr_min": r("tr", 30, 90),
        "cl_min": r("cl", 30, 75),
        "conf_tr_min": r("conf_tr", 15, 120),
        "conf_off_min": r("conf_off", 30, 240),
        "noshow": r("noshow", 0.0, 0.25),
        "arr_mult": r("arr", 0.85, 1.15),
        "care_mult": r("care", 0.85, 1.15),
        "lag_min": r("lag", 0.0, 60.0 if pop == "REF" else 120.0),
    }
    if pop == "REF":
        simple = u(ek, 0, "mix", "simple") < 0.3
        m2 = (not simple) and u(ek, 0, "mix", "m2") < 0.5 / 0.7
        mech = {
            "m2": m2,
            "m2_common": False,
            "slow": 1.8,
            "m3_kappa": 0.0 if simple else 0.5,
            "m5_drop": False,
            "simple": simple,
        }
    else:
        mech = {
            "m2": True,
            "m2_common": True,
            "slow": 2.5,
            "m3_kappa": 1.5,
            "m5_drop": True,
            "simple": False,
        }
    mondays = [datetime(2027, 1, 4) + timedelta(days=7 * k) for k in range(11)]
    local0 = mondays[int(u(ek, 0, "start", "") * len(mondays))].replace(tzinfo=PARIS)
    return EstablishmentSpec(
        partition,
        index,
        pop,
        ek,
        local0.astimezone(UTC).isoformat(),
        beds,
        iso,
        c_tr,
        c_cl,
        theta,
        mech,
    )


def roster_for(n_beds: int, skill: str, hours: int) -> list[int]:
    mean_care = sum(p * CARE_MEAN[skill][a + 1] for a, p in enumerate(ACUITY_P))
    out = []
    for h in range(hours):
        day = 7 <= h % 24 < 21
        expected = n_beds * 0.9 * mean_care * (1.25 if day else 0.6)
        out.append(max(1, round(expected / 60.0)))
    return out


@dataclass
class TruthProvider:
    """Private truth for realisation r. r=0 is the corpus realisation; r>=1 are fresh futures.
    ``theta`` may be the true one (truth, C_param, C_full) or the prior centre (C_pub-snap)."""

    spec: EstablishmentSpec
    r: int = 0
    theta: dict[str, float] | None = None
    regime_anchor: dict[str, tuple[int, int]] = field(default_factory=dict)  # team -> (hour, state)
    _reg: dict[tuple[str, int], int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.theta is None:
            self.theta = dict(self.spec.theta)

    @property
    def th(self) -> dict[str, float]:
        assert self.theta is not None
        return self.theta

    def _u(self, *parts: object) -> float:
        return u(self.spec.ekey, self.r, *parts)

    # ---- hidden team slowdown regime (m2 / m5 common regime)
    def regime(self, team: str, hour: int) -> int:
        m = self.spec.mech
        if not m["m2"]:
            return 0
        team = "common" if m["m2_common"] else team
        if (team, hour) in self._reg:
            return self._reg[(team, hour)]
        a_hour, a_state = self.regime_anchor.get(team, (0, 0))
        if hour <= a_hour:
            return a_state
        state = (
            self._reg.get((team, hour - 1))
            if (team, hour - 1) in self._reg
            else self.regime(team, hour - 1)
        )
        p = 1.0 / 6.0 if state else 1.0 / 24.0
        new = (1 - state) if self._u("regime", team, hour) < p else state
        self._reg[(team, hour)] = new
        return new

    def slow(self, team: str, tick: int) -> float:
        return self.spec.mech["slow"] if self.regime(team, tick // TPH) else 1.0

    # ---- provider interface
    def auth_tick(self, eng: Engine, st: Stay) -> int:
        med = self.th["los_days"] * 24 * 60
        elapsed = (eng.tick - st.placed_tick) * 15
        uu = cond_uniform(lognormal_cdf(elapsed, med, 0.5), self._u("auth", st.sid))
        t = st.placed_tick + max(1, math.ceil(lognormal_minutes(med, 0.5, uu) / 15))
        t = max(t, eng.tick + 1)
        if not 8 <= local_hour(t) < 18:  # authorisations are issued in daytime
            day = t // TPD + (1 if local_hour(t) >= 18 else 0)
            t = day * TPD + 8 * TPH + int(self._u("auth_shift", st.sid) * 12)
        return t

    def _load(self, eng: Engine, unit: str, hour: int) -> float:
        dem = sum(
            CARE_MEAN["IDE"][s.acuity]
            for s in eng.stays.values()
            if s.unit == unit and s.departed is None
        )
        dem *= 1.25 if 7 <= hour % 24 < 21 else 0.6
        cap = 60.0 * max(
            1, eng.units[unit].roster["IDE"][min(hour, len(eng.units[unit].roster["IDE"]) - 1)]
        )
        return dem / cap

    def ready_tick(self, eng: Engine, st: Stay) -> int:
        med = self.th["ready_h"] * 60
        kappa = self.spec.mech["m3_kappa"]
        start = st.auth_tick if st.auth_tick is not None else eng.tick
        if kappa:
            med *= 1.0 + kappa * max(0.0, self._load(eng, st.unit, start // TPH) - 0.9)
        elapsed = (eng.tick - start) * 15
        uu = cond_uniform(lognormal_cdf(elapsed, med, 0.6), self._u("ready", st.sid))
        t = start + max(1, math.ceil(lognormal_minutes(med, 0.6, uu) / 15))
        t = max(t, eng.tick + 1)
        if not 7 <= local_hour(t) < 21:
            day = t // TPD + (1 if local_hour(t) >= 21 else 0)
            t = day * TPD + 7 * TPH + int(self._u("ready_shift", st.sid) * 8)
        return t

    def confirm_tick(self, eng: Engine, kind: str, ref: str, req: int) -> int:
        med = self.th["conf_tr_min"] if kind == "transport" else self.th["conf_off_min"]
        sig = 0.6 if kind == "transport" else 0.5
        elapsed = (eng.tick - req) * 15
        uu = cond_uniform(lognormal_cdf(elapsed, med, sig), self._u("confirm", kind, ref))
        return max(eng.tick + 1, req + max(1, math.ceil(lognormal_minutes(med, sig, uu) / 15)))

    def transport_end(self, eng: Engine, st: Stay) -> int:
        start = st.tr_start if st.tr_start is not None else eng.tick
        med = self.th["tr_min"] * self.slow("transport", start)
        elapsed = (eng.tick - start) * 15
        uu = cond_uniform(lognormal_cdf(elapsed, med, 0.4), self._u("transport", st.sid))
        return max(eng.tick + 1, start + max(1, math.ceil(lognormal_minutes(med, 0.4, uu) / 15)))

    def cleaning_end(self, eng: Engine, bed: Bed) -> int:
        start = bed.clean_start if bed.clean_start is not None else eng.tick
        med = self.th["cl_min"] * self.slow("cleaning", start)
        elapsed = (eng.tick - start) * 15
        uu = cond_uniform(
            lognormal_cdf(elapsed, med, 0.35), self._u("cleaning", bed.bed_id, bed.dirty_tick)
        )
        return max(eng.tick + 1, start + max(1, math.ceil(lognormal_minutes(med, 0.35, uu) / 15)))

    def presence(self, eng: Engine, off: Offer) -> bool:
        if off.source != "pool":
            return True
        return self._u("presence", off.oid) >= self.th["noshow"]

    def arrivals(self, eng: Engine, unit: str, hour: int) -> list[tuple[bool, int, bool]]:
        n_beds = len(eng.units[unit].beds)
        mean = (
            n_beds
            * 0.93
            / (self.th["los_days"] * 24)
            * HOUR_PROFILE[hour % 24]
            * self.th["arr_mult"]
        )
        rr = 3.0
        n = int(nbinom.ppf(self._u("arrivals", unit, hour), rr, rr / (rr + mean)))
        out = []
        for i in range(n):
            a = self._u("acuity", unit, hour, i)
            acuity = 1 if a < ACUITY_P[0] else (2 if a < ACUITY_P[0] + ACUITY_P[1] else 3)
            out.append(
                (
                    self._u("iso", unit, hour, i) < P_ISO,
                    acuity,
                    self._u("tr", unit, hour, i) < P_TRANSPORT,
                )
            )
        return out

    def care(self, eng: Engine, st: Stay, hour: int) -> tuple[float, float]:
        day = 7 <= hour % 24 < 21
        out = []
        for skill in SKILLS:
            med = (
                CARE_MEAN[skill][st.acuity]
                * (1.25 if day else 0.6)
                * self.th["care_mult"]
                / math.exp(0.125)
            )
            out.append(round(lognormal_minutes(med, 0.5, self._u("care", st.sid, hour, skill))))
        return float(out[0]), float(out[1])

    def cleaning_capacity_drop(self, eng: Engine, tick: int) -> int:
        if not self.spec.mech["m5_drop"]:
            return 0
        day = tick // TPD
        if self._u("drop_on", day) >= 0.5:
            return 0
        start = day * TPD + (8 + int(self._u("drop_start", day) * 8)) * TPH
        length = (4 + int(self._u("drop_len", day) * 5)) * TPH
        return 1 if start <= tick < start + length else 0


def initial_engine(spec: EstablishmentSpec, prov: TruthProvider) -> Engine:
    units, beds = {}, {}
    hours = EPISODE_TICKS // TPH + 48
    for un in ("A", "B"):
        ids = [f"B{un}{i:02d}" for i in range(spec.beds[un])]
        for i, b in enumerate(ids):
            beds[b] = Bed(b, un, iso=i < spec.iso_beds[un])
        roster = {sk: roster_for(spec.beds[un], sk, hours) for sk in SKILLS}
        units[un] = Unit(un, ids, roster, {sk: min(roster[sk]) for sk in SKILLS})
    eng = Engine(units, beds, spec.c_tr, spec.c_cl)
    # initial occupancy (warm-up day 0 absorbs transients); stays placed in the past
    for un in ("A", "B"):
        for b in units[un].beds:
            if u(spec.ekey, 0, "init_occ", b) < 0.9:
                bed = beds[b]
                sid = f"S{un}init_{b}"
                a = u(spec.ekey, 0, "init_acuity", b)
                acuity = 1 if a < 0.4 else (2 if a < 0.8 else 3)
                placed = -int(u(spec.ekey, 0, "init_age", b) * 4 * TPD)
                st = Stay(
                    sid,
                    un,
                    b,
                    acuity,
                    bed.iso and u(spec.ekey, 0, "init_iso", b) < 0.5,
                    u(spec.ekey, 0, "init_tr", b) < P_TRANSPORT,
                    placed,
                )
                bed.state, bed.stay = "occ", sid
                eng.stays[sid] = st
                st.auth_tick = prov.auth_tick(eng, st)
    return eng


@dataclass
class Episode:
    spec: EstablishmentSpec
    observations: list[
        tuple[int, int, str, str, str, dict[str, Any]]
    ]  # (event_min, avail_min, kind, subject, unit, value)
    hourly: list[dict[str, Any]]
    demand: dict[tuple[str, str, int], float]
    capacity: dict[tuple[str, str, int], int]
    stays: dict[str, dict[str, Any]]  # private per-stay truth (labels)
    instants: dict[
        int, Engine
    ]  # true engine at evaluated decision instants (before the behaviour action)
    regimes: dict[str, list[int]]
    truth_log: list[tuple[int, str, str, dict[str, Any]]]
    rejected: int
    rejections: dict[str, int]
    static: dict[str, Any]


ZERO_LAG = {"transport_requested", "offer_requested", "plan", "static"}


def behaviour_plan(spec: EstablishmentSpec, tick: int) -> Plan:
    if u(spec.ekey, 0, "behaviour", "habitual", tick) < 0.5:
        return candidates()[0]
    cands = candidates()
    return cands[int(u(spec.ekey, 0, "behaviour", "pick", tick) * len(cands))]


def generate(spec: EstablishmentSpec, keep_instants: bool = False) -> Episode:
    prov = TruthProvider(spec, 0)
    eng = initial_engine(spec, prov)
    obs: list[tuple[int, int, str, str, str, dict[str, Any]]] = []
    truth_log: list[
        tuple[int, str, str, dict[str, Any]]
    ] = []  # private emission order (verifier only)

    def on_event(tick: int, kind: str, subject: str, value: dict[str, Any]) -> None:
        truth_log.append((tick, kind, subject, dict(value)))
        ev_min = tick * 15 + (60 if kind == "care_due" else 0)
        lag = (
            0
            if kind in ZERO_LAG
            else int(
                -spec.theta["lag_min"]
                * math.log(1 - u(spec.ekey, 0, "lag", kind, subject, tick) * 0.999999)
            )
        )
        obs.append((ev_min, ev_min + lag, kind, subject, str(value.get("unit", "")), dict(value)))

    eng.on_event = on_event
    eng.emit_log = False
    static = {
        "units": {
            n: {
                "beds": [(b, eng.beds[b].iso) for b in un.beds],
                "roster": {k: v[: EPISODE_TICKS // TPH + 48] for k, v in un.roster.items()},
                "minimum": un.minimum,
            }
            for n, un in eng.units.items()
        },
        "c_tr": spec.c_tr,
        "c_cl": spec.c_cl,
        "start_utc": spec.start_utc,
    }
    obs.append(
        (
            0,
            0,
            "static",
            "establishment",
            "",
            {"units": static["units"], "c_tr": spec.c_tr, "c_cl": spec.c_cl},
        )
    )
    # initial public state: stays present at t0 (with their public attributes)
    for st in sorted(eng.stays.values(), key=lambda s: s.sid):
        obs.append(
            (
                0,
                0,
                "placed",
                st.sid,
                st.unit,
                {
                    "bed": st.bed,
                    "unit": st.unit,
                    "acuity": st.acuity,
                    "iso": st.iso,
                    "transport": st.transport,
                    "placed_min": st.placed_tick * 15,
                },
            )
        )
    instants: dict[int, Engine] = {}
    eval_ticks = {EVAL_DAY * TPD + h * TPH for h in INSTANT_HOURS}
    while eng.tick < EPISODE_TICKS:
        t = eng.tick
        if t % TPH == 0:
            eng.hourly.append(eng.snapshot_hour())
        if t % TPH == 0 and local_hour(t) in INSTANT_HOURS:
            if keep_instants and t in eval_ticks:
                instants[t] = eng.clone()
            plan = behaviour_plan(spec, t)
            if plan.cid != candidates()[0].cid:
                obs.append(
                    (
                        t * 15,
                        t * 15,
                        "plan",
                        plan.cid,
                        "",
                        {
                            "coordinate": plan.coordinate,
                            "cleaning": plan.cleaning,
                            "reinforcement": plan.reinforcement,
                        },
                    )
                )
            eng.apply_plan(plan, prov)
        eng.step(prov)
    stays = {
        s.sid: {
            "unit": s.unit,
            "placed": s.placed_tick,
            "auth": s.auth_tick,
            "ready": s.ready_tick,
            "departed": s.departed,
            "acuity": s.acuity,
        }
        for s in eng.stays.values()
    }
    regimes = {
        team: [prov.regime(team, h) for h in range(EPISODE_TICKS // TPH)]
        for team in ("transport", "cleaning")
    }
    obs.sort(key=lambda o: (o[1], o[0], o[2], o[3]))
    init_log = [
        (0, "placed", o[3], o[5])
        for o in obs
        if o[2] == "placed" and o[0] == 0 and "placed_min" in o[5]
    ]
    return Episode(
        spec,
        obs,
        eng.hourly,
        dict(eng.demand),
        dict(eng.capacity),
        stays,
        instants,
        regimes,
        init_log + truth_log,
        eng.rejected,
        dict(eng.rejections),
        static,
    )


def refresh_private(eng: Engine, prov: Any) -> None:
    """Redraw every private FUTURE time of a cloned engine with provider ``prov`` (fresh
    innovations conditional on what has already elapsed). Used for realisations r>=1 at an
    instant, and to prime a public-state engine before a rollout."""
    for st in sorted(eng.stays.values(), key=lambda s: s.sid):
        if st.departed is not None:
            continue
        if not st.authorised:
            st.auth_tick = prov.auth_tick(eng, st)
        elif not st.ready:
            st.ready_tick = prov.ready_tick(eng, st)
        if st.tr_req is not None and not st.tr_accepted:
            st.tr_conf = prov.confirm_tick(eng, "transport", st.sid, st.tr_req)
        if st.tr_start is not None and st.tr_end is not None and not st.public_transport_done:
            st.tr_end = prov.transport_end(eng, st)
    for bed in eng.beds.values():
        if bed.state == "cleaning":
            bed.clean_end = prov.cleaning_end(eng, bed)
    for off in eng.offers.values():
        if not off.confirmed and off.source == "pool":
            off.conf_tick = prov.confirm_tick(eng, "offer", off.oid, off.req)


def true_regime_at(ep: Episode, tick: int) -> dict[str, tuple[int, int]]:
    h = tick // TPH
    if ep.spec.mech["m2_common"]:
        return {"common": (h, ep.regimes["transport"][h])}
    return {team: (h, ep.regimes[team][h]) for team in ("transport", "cleaning")}


def stationary_regime(spec: EstablishmentSpec, r: int, tick: int) -> dict[str, tuple[int, int]]:
    h = tick // TPH
    teams = ["common"] if spec.mech["m2_common"] else ["transport", "cleaning"]
    return {t: (h, int(u(spec.ekey, r, "stationary", t, h) < 0.2)) for t in teams}
