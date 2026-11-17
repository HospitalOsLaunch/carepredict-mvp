"""HOWM-INT-1 episodes: common prefix, closed-loop replanning with policy-own public history, branching of
paired action sequences with trajectory recording (corpus), and outcome metrics.

Time convention: a decision at tick t sees only observations with availability < 15 t minutes (strict).
Futures: realisation r >= 1 of the provider law, anchored on the true hidden regime at the episode origin;
the prefix (common to all policies and futures) is the realisation r = 0 under the background policy.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

import numpy as np

from hospitalos.bfrag import core as K
from hospitalos.howm.generator import refresh_private
from hospitalos.howm.world import TPD, TPH

from . import actions as A
from . import world as W

STEP_TICKS = 2 * TPH  # trajectory recording step (2 h)


def prefix(spec_e: W.IntSpec, h0: int) -> dict:
    """True engine at origin tick h0*TPH under the background policy (no plans), with its observations."""
    prov0 = W.ProvN(spec_e, 0)
    eng = W.initial_engine(spec_e, prov0)
    rec = W.Recorder(spec_e, 0)
    obs0 = W.static_obs(eng, spec_e)
    eng.on_event = rec
    eng.emit_log = False
    while eng.tick < h0 * TPH:
        eng.step(prov0)
    anchor = W.regime_anchor(prov0, eng.tick)
    eng.on_event = None
    return {"eng": eng, "obs": obs0 + rec.obs, "anchor": anchor, "t0": eng.tick}


def start_future(pre: dict, spec_e: W.IntSpec, r: int) -> tuple[Any, Any, W.Recorder]:
    prov = W.ProvN(spec_e, r, regime_anchor=pre["anchor"])
    eng = pre["eng"].clone()
    refresh_private(eng, W._Cal(prov, spec_e.drop))
    rec = W.Recorder(spec_e, r)
    eng.on_event = rec
    eng.emit_log = False
    return eng, prov, rec


def public_view(pre: dict, rec: W.Recorder, t: int) -> tuple[W.PublicStreamN, Any]:
    ps = W.PublicStreamN([o for o in pre["obs"] + rec.obs if o[1] < 15 * t])
    ps.advance(15 * t - 1)
    return ps, ps.to_engine_n(t)


class Tracker:
    """Per-tick outcome accounting on the true engine (wait per unit, patients waiting >= 24 h)."""

    def __init__(self, eng: Any):
        self.w0 = dict(eng.waiting_ticks)
        self.rej0 = eng.rejected
        self.n24: dict[str, list[int]] = {un: [] for un in eng.units}
        self.h0 = eng.tick // TPH

    def tick(self, eng: Any) -> None:
        t = eng.tick
        for un in eng.units:
            self.n24[un].append(sum(1 for r in eng.queue.get(un, []) if (t - r.arrival) * 15 >= K.WAIT_LIMIT_MIN))

    def result(self, eng: Any) -> dict:
        from hospitalos.howm.world import uncovered

        runs = {un: K.episodes(s) for un, s in self.n24.items()}
        wbu = {un: 15.0 * (eng.waiting_ticks.get(un, 0) - self.w0.get(un, 0)) for un in eng.units}
        per_day, tot = A.used_hours(eng)
        return {"wait_patient_min": sum(wbu.values()), "wait_by_unit": wbu,
                "uncovered_care_min": uncovered(eng, range(self.h0, eng.tick // TPH)),
                "rejected": eng.rejected - self.rej0, "rejections": dict(eng.rejections),
                "rupture_minutes": 15 * sum(b - a for v in runs.values() for a, b, _s in v),
                "rupture_onsets": sum(len(v) for v in runs.values()),
                "terminal_queue": sum(len(q) for q in eng.queue.values()),
                "terminal_max_wait_min": max([(eng.tick - r.arrival) * 15 for q in eng.queue.values() for r in q], default=0),
                "aval_blocked_end": len(eng.aval_blocked), "transfer_pending_end": len(eng.transfer_pending),
                "staff_hours": tot, "commitments": len(eng.commitments)}


def closed_loop(spec_e: W.IntSpec, pre: dict, r: int, policy: Callable, n_dec: int, interval_h: int, horizon_h: int,
                log: list | None = None) -> dict:
    """Run ONE policy in closed loop in future r: at each decision it receives only its own public history."""
    eng, prov, rec = start_future(pre, spec_e, r)
    tr = Tracker(eng)
    t_start = eng.tick
    end = t_start + horizon_h * TPH
    dec_ticks = [t_start + k * interval_h * TPH for k in range(n_dec)]
    choices = []
    while eng.tick < end:
        if eng.tick in dec_ticks:
            ps, peng = public_view(pre, rec, eng.tick)
            cat = A.catalogue(peng, spec_e.units)
            adm = [A.admissible(peng, a, spec_e.n, t_start) for a in cat]
            a = policy(ps=ps, peng=peng, cat=cat, adm=adm, t=eng.tick, t_start=t_start, spec=spec_e,
                       view=lambda tt, rec=rec: public_view(pre, rec, tt))
            if a["kind"] in ("cl", "tr", "staff") and not A.admissible(eng, a, spec_e.n, t_start):
                a = cat[0]  # cannot happen: commitments are public (zero-lag plan events); kept as a guard
            A.apply(eng, a, W._Cal(prov, spec_e.drop))
            choices.append(a["id"])
            if log is not None:
                log.append({"t": eng.tick, "action": a["id"]})
        eng.step(prov)
        tr.tick(eng)
    out = tr.result(eng)
    out["choices"] = choices
    return out


def unit_state(eng: Any, un: str) -> list[float]:
    t = eng.tick
    beds = [eng.beds[b] for b in eng.units[un].beds]
    q = eng.queue.get(un, [])
    waits = [(t - r.arrival) * 15 for r in q]
    stays = [s for s in eng.stays.values() if s.unit == un and s.departed is None]
    nb = float(len(beds))
    return [sum(b.state == "occ" for b in beds) / nb, sum(b.state == "free" for b in beds) / nb,
            sum(b.state in ("dirty", "cleaning") for b in beds) / nb, float(len(q)), sum(w >= 720 for w in waits),
            sum(w >= 1440 for w in waits), sum(1 for s in stays if s.ready and s.transport and s.tr_end is None),
            sum(1 for s in stays if getattr(s, "transfer_requested", False)), sum(1 for s in stays if s.sid in eng.aval_blocked)]


STATE_NAMES = ("occ_frac", "free_frac", "dirty_frac", "queue", "q12", "q24", "ready_wait_tr", "transfer_wait", "aval_blocked")


def branch(pre_like: dict, spec_e: W.IntSpec, eng0: Any, seq: list[dict | None], r: int, hours: int, interval_h: int,
           anchor: dict) -> dict:
    """Paired consequence of an action SEQUENCE from a true engine state: a0 now, a1 at +interval (re-resolved on
    the same slot offsets), recorded every 2 h: per-unit true state, per-unit wait accrued, n24 per unit."""
    prov = W.ProvN(spec_e, r, regime_anchor=anchor)
    eng = eng0.clone()
    eng.on_event = None
    eng.emit_log = False
    cal = W._Cal(prov, spec_e.drop)
    refresh_private(eng, cal)
    t0 = eng.tick
    tr = Tracker(eng)
    states, costs, n24 = [], [], []
    last = {un: eng.waiting_ticks.get(un, 0) for un in spec_e.units}
    for i in range(hours * TPH):
        k = i // (interval_h * TPH)
        if i % (interval_h * TPH) == 0 and k < len(seq) and seq[k] is not None:
            a = seq[k]
            if k > 0:  # same intervention type re-resolved at the later decision
                a = _shift(eng, a, t0 + k * interval_h * TPH, spec_e)
            if a is not None and A.admissible(eng, a, spec_e.n, t0):
                A.apply(eng, a, cal)
        eng.step(prov)
        tr.tick(eng)
        if (i + 1) % STEP_TICKS == 0:
            states.append([unit_state(eng, un) for un in spec_e.units])
            now = {un: eng.waiting_ticks.get(un, 0) for un in spec_e.units}
            costs.append([15.0 * (now[un] - last[un]) for un in spec_e.units])
            n24.append([tr.n24[un][-1] for un in spec_e.units])
            last = now
    out = tr.result(eng)
    out.update({"states": np.array(states, np.float32), "step_costs": np.array(costs, np.float32), "n24": np.array(n24, np.int16)})
    return out


def _shift(eng: Any, a: dict, t: int, spec_e: W.IntSpec) -> dict | None:
    if a["kind"] in ("none", "coord", "av"):
        return dict(a, start=t, end=t + (24 * TPH if a["kind"] in ("coord", "av") else 0))
    sl = A.slots(t, 4)
    i = a["slot"] - 1
    if i >= len(sl):
        return None
    s, e = sl[i]
    return dict(a, start=s, end=e)


def sequences(cat: list[dict], adm: list[bool], rng: np.random.Generator | None = None, n_extra: int = 0) -> list[list[dict]]:
    """Candidate sequences (common to every planner): (a0, none) for every admissible a0, (a0, a0 re-resolved one
    decision later) for every admissible reinforcement a0, (none, coord)."""
    out = []
    for a, ok in zip(cat, adm):
        if ok:
            out.append([a, None])
    for a, ok in zip(cat, adm):
        if ok and a["kind"] in ("cl", "tr", "staff", "av"):
            out.append([a, a])
    out.append([cat[0], cat[1]])
    return out


def deep(x: Any) -> Any:
    return copy.deepcopy(x)


__all__ = ["prefix", "closed_loop", "branch", "sequences", "public_view", "Tracker", "TPD"]
