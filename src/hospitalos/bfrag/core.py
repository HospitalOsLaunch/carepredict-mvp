"""B-FRAG core: worlds (scenario families on the frozen HOWM-1 generator), time convention, public
state, 168-hour continuous rollouts, rupture detector, comparators R0, R1/R2, F, O.

Time convention (PROTOCOLE_BFRAG s.4): the decision instant is the START of tick t0 (day 2, 07:00):
- true state  = engine cloned by the frozen generator BEFORE any event of tick t0;
- public      = observations with avail_min < 15 * t0 (strict), i.e. nothing of tick t0;
- action      = applied at t0 on each system's own start state, then the first step processes t0;
- no background plan after t0 (the frozen operator's built-in habitual operations only).
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from scipy.stats import nbinom

from hospitalos.howm import generator as G
from hospitalos.howm.b0 import B0Params
from hospitalos.howm.generator import TruthProvider, refresh_private
from hospitalos.howm.history import PublicStream
from hospitalos.howm.keys import key, u
from hospitalos.howm.rollout import ModelProvider, NewProfileFreq
from hospitalos.howm.world import TPD, TPH, Engine, candidates, uncovered
from hospitalos.howm2 import nowcast as N
from hospitalos.howm2.filter import Ladder, PublicState

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

DECISION_DAY = 2
T0 = DECISION_DAY * TPD + 7 * TPH  # tick 220 = hour 55
HORIZON_H = 168
HORIZONS = (6, 24, 72, 168)
WAIT_LIMIT_MIN = 24 * 60  # synthetic benchmark convention (PROTOCOLE_BFRAG s.3): wait >= 24 h for an admissible bed
K_MIN = 5  # ... for at least K_MIN patients of the same unit simultaneously
MIN_DURATION_TICKS = 4  # >= 1 h
RECOVERY_TICKS = 8  # 2 h without any long wait closes an episode / merges closer episodes
PARTS = {"BFRAG_DEV": 8, "BFRAG_TUNE": 48, "BFRAG_CONF": 96}
FAMILIES = ("SF1_cleaning_window", "SF2_transport_window", "SF3_planned_drop",
            "SC4_high_load_absorbable", "SC5_drop_with_margin", "SC6_low_load")
FRAGILE = FAMILIES[:3]


def register() -> None:
    for p, n in PARTS.items():
        G.PARTITION_SIZES[p] = n
        G.POPULATION_OF[p] = "REF"


# ------------------------------------------------------------------------------ worlds
@dataclass
class World:
    part: str
    idx: int
    family: str
    spec: Any
    drop: dict  # public calendar: {"day": d, "from_h": a, "to_h": b, "minus": k} or {}
    variant: str = "base"
    nominal: dict | None = None  # planned (nominal) capacity driving arrivals; spec.beds = physical beds


def _r(ek: int, name: str, lo: float, hi: float) -> float:
    return lo + (hi - lo) * u(ek, 0, "bfrag", name)


def family_of(idx: int) -> str:
    return FAMILIES[idx % len(FAMILIES)]


def make_world(part: str, idx: int, design: dict, variant: str = "base", family: str | None = None) -> World:
    """Scenario overlay on the frozen REF spec (keys key('HOWM1', part, idx)); parameters drawn with
    keys key-indexed by name (stable RNG); theta kept inside the REF prior support (L4 valid)."""
    register()
    spec = G.establishment(part, idx)
    ek = spec.ekey
    fam = family or family_of(idx)
    d = design.get(fam, {})
    th = dict(spec.theta)
    for name, (lo, hi) in d.get("theta", {}).items():
        th[name] = _r(ek, name, lo, hi)
    c_cl = d.get("c_cl", spec.c_cl)
    c_tr = d.get("c_tr", spec.c_tr)
    drop = dict(d.get("drop", {}))
    if variant == "relaxed":  # paired control: dependency removed / margin added (same keys)
        rel = d.get("relaxed", {})
        c_cl += rel.get("c_cl_plus", 0)
        c_tr += rel.get("c_tr_plus", 0)
        if rel.get("no_drop"):
            drop = {}
    nominal = dict(spec.beds)
    blo, bhi = d.get("buffer", [0.0, 0.0])
    b = _r(ek, "buffer", blo, bhi)
    beds = {un: n + int(round(b * n)) for un, n in nominal.items()}
    iso = {un: max(1, round(0.25 * n)) for un, n in beds.items()}
    spec = replace(spec, theta=th, c_cl=c_cl, c_tr=c_tr, beds=beds, iso_beds=iso)
    NOMINAL[spec.ekey] = nominal
    return World(part, idx, fam, spec, drop, variant, nominal)


NOMINAL: dict[int, dict] = {}


class BFTruthProvider(TruthProvider):
    """Generator law of B-FRAG worlds: identical to the frozen TruthProvider except that arrivals are
    driven by the NOMINAL (planned) capacity, not by the physical beds (buffer beds are a public margin).
    ``nominal`` is passed explicitly by every simulator; the registry is used only by the generator."""

    nominal: dict | None = None

    def arrivals(self, eng: Engine, unit: str, hour: int) -> list:
        nom = self.nominal or NOMINAL.get(self.spec.ekey)
        if nom is None:
            return super().arrivals(eng, unit, hour)
        n_beds = nom[unit]
        mean = n_beds * 0.93 / (self.th["los_days"] * 24) * G.HOUR_PROFILE[hour % 24] * self.th["arr_mult"]
        rr = 3.0
        n = int(nbinom.ppf(self._u("arrivals", unit, hour), rr, rr / (rr + mean)))
        out = []
        for i in range(n):
            a = self._u("acuity", unit, hour, i)
            acuity = 1 if a < G.ACUITY_P[0] else (2 if a < G.ACUITY_P[0] + G.ACUITY_P[1] else 3)
            out.append((self._u("iso", unit, hour, i) < G.P_ISO, acuity, self._u("tr", unit, hour, i) < G.P_TRANSPORT))
        return out


def _derive_generate():
    import inspect

    src = inspect.getsource(G.generate)
    a, b = "    prov = TruthProvider(spec, 0)\n", "    prov = BFTruthProvider(spec, 0)\n"
    if src.count(a) != 1:
        raise RuntimeError("generate derivation: provider pattern not found exactly once")
    ns = dict(G.__dict__)
    ns["BFTruthProvider"] = BFTruthProvider
    ns["EVAL_DAY"] = DECISION_DAY
    exec(compile(src.replace(a, b), "<bfrag-derived generate>", "exec"), ns)  # noqa: S102
    return ns["generate"]


generate_bf = None


def bf_pending_arrivals(prov, eng, revealed):
    """L4-N pending arrivals with the nominal capacity (B-FRAG arrival law)."""
    out = []
    t0 = prov.t0
    nom = NOMINAL[prov.spec.ekey]
    for unit in sorted(eng.units):
        for hour in range(max(0, (t0 - prov.K) // TPH), (t0 - 1) // TPH + 1):
            k = t0 - hour * TPH
            if k <= 0:
                continue
            q = math.exp(-15 * k / prov.lag) if prov.lag > 0 else 0.0
            if q < N.CUTOFF:
                continue
            mu = N.arrivals_mean(prov.th, nom[unit], hour)
            n = revealed.get((unit, hour), 0)
            beta = N.ARR_R / mu
            pp = (beta + 1 - q) / (beta + 1)
            c = int(nbinom.ppf(u(prov.spec.ekey, prov.r, "nowcast-arr", unit, hour), N.ARR_R + n, pp))
            if c > 0:
                out.append((unit, hour, c))
    return out


def drop_at(drop: dict, tick: int) -> int:
    if not drop:
        return 0
    day, hour = tick // TPD, (tick % TPD) // TPH
    return drop["minus"] if day == drop["day"] and drop["from_h"] <= hour < drop["to_h"] else 0


class WithCalendar:
    """Provider proxy adding the PUBLIC planned cleaning-capacity reduction (calendar)."""

    def __init__(self, prov: Any, drop: dict):
        self._p = prov
        self._drop = drop

    def __getattr__(self, n: str) -> Any:
        return getattr(self._p, n)

    def cleaning_capacity_drop(self, eng: Engine, tick: int) -> int:
        return self._p.cleaning_capacity_drop(eng, tick) + drop_at(self._drop, tick)


# ------------------------------------------------------------------------------ instant
@dataclass
class Instant:
    world: World
    ep: Any
    true_eng: Engine
    ps: PublicStream
    peng: Engine
    public_obs: list


def build_instant(w: World) -> Instant:
    global generate_bf
    if generate_bf is None:
        generate_bf = _derive_generate()
    NOMINAL[w.spec.ekey] = w.nominal
    ep = generate_bf(w.spec, keep_instants=True)
    true_eng = ep.instants[T0]
    cut = 15 * T0
    pub = [o for o in ep.observations if o[1] < cut]
    ps = PublicStream(pub)
    ps.advance(cut - 1)
    peng = ps.to_engine(cut - 1)
    peng.tick = T0
    return Instant(w, ep, true_eng, ps, peng, pub)


# ------------------------------------------------------------------------------ rollout + metrics
def rollout168(eng0: Engine, prov: Any, plan: Any, drop: dict, prime: bool = True) -> dict:
    eng = eng0.clone()
    eng.emit_log = False
    p = WithCalendar(prov, drop)
    if prime:
        refresh_private(eng, p)
    t0 = eng.tick
    w0 = dict(eng.waiting_ticks)
    rej0 = eng.rejected
    if plan is not None:
        eng.apply_plan(plan, p)
    rej_plan = eng.rejected - rej0
    long_wait = {un: [] for un in eng.units}
    for _ in range(HORIZON_H * TPH):
        eng.step(p)
        t = eng.tick
        for un in eng.units:
            long_wait[un].append(sum(1 for r in eng.queue.get(un, []) if (t - r.arrival) * 15 >= WAIT_LIMIT_MIN))
    wait_ticks = sum(eng.waiting_ticks.get(un, 0) - w0.get(un, 0) for un in eng.units)
    h0 = t0 // TPH
    term = {un: {"queue": len(eng.queue.get(un, [])),
                 "max_wait_min": max([(eng.tick - r.arrival) * 15 for r in eng.queue.get(un, [])], default=0),
                 "dirty_or_cleaning": sum(eng.beds[b].state in ("dirty", "cleaning") for b in eng.units[un].beds),
                 "ready_not_departed": sum(1 for s in eng.stays.values() if s.unit == un and s.departed is None and s.ready)}
            for un in eng.units}
    return {"wait_patient_min": 15.0 * wait_ticks,
            "uncovered_care_min": uncovered(eng, range(h0, h0 + HORIZON_H)),
            "rejected_total": eng.rejected - rej0, "rejected_at_plan": rej_plan,
            "reinforcement_hours": sum(4 for o in eng.offers.values() if o.req >= t0 and o.confirmed),
            "long_wait": long_wait, "terminal": term}


def episodes(series: list[int]) -> list[tuple[int, int, int]]:
    """Rupture episodes on a per-tick count of patients waiting >= WAIT_LIMIT: runs with count >= K_MIN,
    runs separated by < RECOVERY_TICKS merged; kept if duration >= MIN_DURATION_TICKS.
    Returns (onset_offset_ticks, end_offset_ticks, severity_patient_ticks)."""
    runs = []
    i = 0
    n = len(series)
    while i < n:
        if series[i] >= K_MIN:
            j = i
            while j < n and series[j] >= K_MIN:
                j += 1
            runs.append([i, j])
            i = j
        else:
            i += 1
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and a - merged[-1][1] < RECOVERY_TICKS:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    out = []
    for a, b in merged:
        if b - a >= MIN_DURATION_TICKS:
            out.append((a, b, int(sum(series[a:b]))))
    return out


def rupture_summary(res: dict) -> dict:
    eps = {un: episodes(s) for un, s in res["long_wait"].items()}
    first = min([e[0] for v in eps.values() for e in v], default=None)
    within = {str(h): bool(first is not None and first < h * TPH) for h in HORIZONS}
    onsets = sorted((e[0], un) for un, v in eps.items() for e in v)
    cascade = any(u1 != u2 and 0 <= o2 - o1 <= 24 * TPH for (o1, u1) in onsets for (o2, u2) in onsets)
    return {"episodes": {un: [list(e) for e in v] for un, v in eps.items()}, "first_onset_tick": first,
            "within": within, "severity_patient_min": 15 * sum(e[2] for v in eps.values() for e in v),
            "duration_min": 15 * sum(e[1] - e[0] for v in eps.values() for e in v), "cascade_both_units_24h": cascade,
            "active_at_start": any(s[0] >= K_MIN for s in res["long_wait"].values())}


# ------------------------------------------------------------------------------ comparators
def public_key(inst: Instant) -> int:
    """Simulation key of the PUBLIC methods: derived from public information only (no seed, no
    world identifier, no scenario label)."""
    import hashlib

    st = next(o[5] for o in inst.public_obs if o[2] == "static")
    blob = json_dumps({"static": st, "n_obs": len(inst.public_obs), "first": inst.public_obs[:20]})
    return int(hashlib.sha256(blob.encode()).hexdigest()[:15], 16)


def json_dumps(x: Any) -> str:
    import json

    return json.dumps(x, sort_keys=True, default=str)


def bf_provider(spec: Any, r: int, nominal: dict, **kw: Any) -> BFTruthProvider:
    p = BFTruthProvider(spec, r, **kw)
    p.nominal = dict(nominal)
    return p


def plan_index_R0(peng: Engine) -> int:
    from howm_eval import strengthened_rule

    return int(strengthened_rule(peng))


def score_R0(inst: Instant) -> float:
    """Public operational heuristic (rule-based alert): pressure = max over units of
    (admission queue + dirty/cleaning beds - free beds) / beds, + 0.5 if a planned capacity
    reduction falls within the next 48 h."""
    eng = inst.peng
    best = -1e9
    for un, uu in eng.units.items():
        beds = [eng.beds[b] for b in uu.beds]
        v = (len(eng.queue.get(un, [])) + sum(b.state in ("dirty", "cleaning") for b in beds)
             - sum(b.state == "free" for b in beds)) / len(beds)
        best = max(best, v)
    soon = any(drop_at(inst.world.drop, T0 + k) for k in range(48 * TPH))
    return float(best + (0.5 if soon else 0.0))


class LongModelProvider(ModelProvider):
    """R1: B0-local-long predictions; arrivals beyond 24 h use the same hour-of-day rate (declared)."""

    def arrivals(self, eng: Engine, unit: str, hour: int) -> list:
        k = hour - self.H
        if 0 <= k < 24 or k < 0:
            return super().arrivals(eng, unit, hour)
        cdf = self.arr_cdf["AB".index(unit)][k % 24]
        n = int(np.searchsorted(cdf, self._u("arr", unit, hour)))
        f = self.freq
        out = []
        for i in range(n):
            a = self._u("acu", unit, hour, i)
            acuity = 1 if a < f.p_acuity[0] else (2 if a < f.p_acuity[0] + f.p_acuity[1] else 3)
            out.append((self._u("iso", unit, hour, i) < f.p_iso, acuity, self._u("trn", unit, hour, i) < f.p_transport))
        return out


def r1_providers(inst: Instant, p: B0Params, M: int) -> list:
    from hospitalos.howm2 import data as D
    from hospitalos.howm2.ladder import l2_predict

    H = T0 // TPH
    epf = SimpleNamespace(observations=inst.public_obs)
    od = next(od for h, od, _ps in D.origins(epf, [H]) if h == H)
    est = SimpleNamespace(n_beds=dict(inst.world.nominal))
    pr = l2_predict(p, od, est, inst.ps)
    f = p.new_profile_freq
    fr = NewProfileFreq(f["p_iso"], (f["p_acuity_1"], f["p_acuity_2"], f["p_acuity_3"]), f["p_transport"])
    bk = key("BFRAG-R1", public_key(inst))
    return [LongModelProvider(pr, od, T0, m, bk, fr) for m in range(M)]


class BFNowcastProvider(N.NowcastProvider):
    """L4-N with the strict publication convention of B-FRAG: unpublished iff lag >= 15 k."""

    def _nowcast(self, draw, start: int, ident: tuple):
        lo = max(start, self.t0 - self.K)
        if not self.active or self.K == 0 or lo >= self.t0:
            return None
        for a in range(N.MAX_ATTEMPTS):
            self._attempt = a
            try:
                e = draw(lo - 1)
                acc = u(self.spec.ekey, self.r, "nowcast-acc", a, *ident)
            finally:
                self._attempt = None
            if e >= self.t0:
                return None
            k = self.t0 - e
            if acc < math.exp(-15 * k / self.lag):
                return int(e)
        self.fallbacks += 1
        return None


def f_samples(inst: Instant, M: int) -> list[tuple[Engine, Any]]:
    """F: L4 posterior (theta, mechanism, regime at the last observed hour) + L4-N nowcast of the
    present state; simulator = generator structure with the sampled parameters (keys 201+m)."""
    from howm2_decision import sample_world

    spec = inst.world.spec
    static = next(o[5] for o in inst.public_obs if o[2] == "static")
    lad = Ladder(spec.population, static, dict(inst.world.nominal), None)
    pub = PublicState(spec.population, dict(spec.beds))
    pub.ingest(inst.ps.obs[: inst.ps.i])
    t = 15 * T0 - 1
    ctx = lad.context(pub, inst.ps, t)
    revealed = N.revealed_arrivals(inst.ps, 15 * T0)
    pk = public_key(inst)
    rng = np.random.default_rng(int(key("BFRAG-F", pk) % (2**31)))
    nominal = dict(inst.world.nominal)
    out = []
    for m in range(M):
        th, mech, anchor = sample_world(lad, ctx, rng)
        s2 = replace(spec, theta=th, mech=mech, ekey=key("BFRAG-F-sim", pk))  # public simulation key
        NOMINAL[s2.ekey] = nominal
        prov = BFNowcastProvider(s2, 201 + m, th, anchor, T0, th["lag_min"])
        N.pending_arrivals = bf_pending_arrivals  # B-FRAG arrival law (module attribute in this process)
        eng, _applied = N.nowcast_engine(inst.peng, prov, revealed)
        out.append((eng, bf_provider(s2, 201 + m, nominal, theta=th, regime_anchor=anchor)))
    return out


def o_samples(inst: Instant, M: int) -> list[tuple[Engine, Any]]:
    spec = inst.world.spec
    anchor = G.true_regime_at(inst.ep, T0)
    return [(inst.true_eng, bf_provider(spec, 101 + m, inst.world.nominal, regime_anchor=anchor)) for m in range(M)]


def plan_and_scores(pairs: list[tuple[Engine, Any]], drop: dict) -> dict:
    """16 candidates x M draws (CRN across candidates); planner = argmin mean primary loss (ties:
    fewer interventions, then index); risk scores = P(rupture within h) under candidate 0."""
    from hospitalos.howm.controllers import interventions

    cands = candidates()
    loss = np.zeros((len(pairs), len(cands)))
    within0 = {str(h): [] for h in HORIZONS}
    for m, (eng, prov) in enumerate(pairs):
        for c, plan in enumerate(cands):
            res = rollout168(eng, prov, plan, drop)
            loss[m, c] = res["wait_patient_min"]
            if c == 0:
                rs = rupture_summary(res)
                for h in within0:
                    within0[h].append(rs["within"][h])
    mean = loss.mean(0)
    best = min(range(len(cands)), key=lambda i: (round(mean[i], 6), interventions(cands[i]), i))
    return {"choice": int(best), "mean_loss": mean.tolist(), "risk": {h: float(np.mean(v)) for h, v in within0.items()}}


def evaluate(inst: Instant, plans: dict[str, int], E: int) -> dict:
    """True environment: true engine at t0, fresh futures r = 1..E, true regime anchor."""
    spec = inst.world.spec
    anchor = G.true_regime_at(inst.ep, T0)
    cands = candidates()
    out = {}
    for pi in sorted(set(plans.values())):
        rows = []
        for r in range(1, E + 1):
            res = rollout168(inst.true_eng, bf_provider(spec, r, inst.world.nominal, regime_anchor=anchor), cands[pi], inst.world.drop)
            rs = rupture_summary(res)
            rows.append({k: res[k] for k in ("wait_patient_min", "uncovered_care_min", "rejected_total", "rejected_at_plan",
                                              "reinforcement_hours", "terminal")} | {"rupture": rs})
        out[str(pi)] = rows
    return out
