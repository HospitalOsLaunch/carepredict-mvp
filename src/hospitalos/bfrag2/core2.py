"""B-FRAG 2 core (PROTOCOLE_BFRAG2): structures x episodes, continuous reference trajectory with
dependency traces, as-of public views S0/S1/S2, risk scores (R0, R1, F, O), deferred-intervention
catalogue and 168-hour counterfactual rollouts.

Vocabulary (protocol s.1): STRUCTURE = B-FRAG 1 world spec (units, nominal/physical beds, isolation
compatibility, resources c_tr/c_cl, theta, mechanism flags, planned calendar), keyed by
key('HOWM1', partition, s); EPISODE e = an independent history in that structure (event draws keyed
by key('BF2-ep', partition, s, e)); ORIGIN = observation instant of the episode (every 6 h);
FUTURE REALISATION = conditional draw r (labels come from the episode's own continuation under the
common background policy; intervention evaluation uses fresh futures r = 1..E).
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from hospitalos.bfrag import core as K
from hospitalos.howm import generator as G
from hospitalos.howm.generator import refresh_private
from hospitalos.howm.history import PublicStream
from hospitalos.howm.keys import key
from hospitalos.howm.world import TPD, TPH, Engine, Plan, candidates, is_weekday, local_hour, uncovered
from hospitalos.howm2 import nowcast as N
from hospitalos.howm2.filter import Ladder, PublicState

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

ORIGIN_HOURS = list(range(36, 121, 6))  # 15 origins; 120 + 72 = 192 = episode end -> no censoring
SNAP_HOURS = list(range(6, 121, 6))  # public snapshots used by S1 and the S2 history deltas
DECISION_HOURS = (42, 54, 66)  # decision origin of episode e = DECISION_HOURS[e % 3]; 66 + 168 <= 240 (roster)
WINDOW_H = 72
SECONDARY_H = 24
PARTS = {"BF2_DEV": 6, "BF2_TRAIN": 200, "BF2_VAL": 100, "BF2_CONF": 200}  # registered sizes (used: protocol s.5)
EPISODES = 3
MANIFEST_WAIT_H, MANIFEST_K = 12, 3  # public "manifest pressure": >= 3 patients waiting >= 12 h in a unit


def register() -> None:
    K.register()
    for p, n in PARTS.items():
        G.PARTITION_SIZES[p] = n
        G.POPULATION_OF[p] = "REF"


def structure(part: str, s: int, design: dict) -> K.World:
    register()
    return K.make_world(part, s, design)


def episode_spec(w: K.World, e: int):
    spec = replace(w.spec, ekey=key("BF2-ep", w.part, w.idx, e))
    K.NOMINAL[spec.ekey] = dict(w.nominal)
    return spec


# ------------------------------------------------------------------------------ derived generator
_GEN = None
TRACE: list = []


def _trace(eng: Engine) -> None:
    t = eng.tick
    row = {}
    for un, uu in eng.units.items():
        q = eng.queue.get(un, [])
        beds = [eng.beds[b] for b in uu.beds]
        free = [b for b in beds if b.state == "free"]
        iso_free = sum(1 for b in free if b.iso)
        waits = [(t - r.arrival) * 15 for r in q]
        iso_wait = sum(1 for r in q if r.iso)
        ready_tr = sum(1 for st in eng.stays.values() if st.unit == un and st.departed is None and st.ready and st.transport)
        dirty = sum(1 for b in beds if b.state in ("dirty", "cleaning"))
        row[un] = {"n24": sum(1 for w_ in waits if w_ >= K.WAIT_LIMIT_MIN), "q": len(q),
                   "block_compat": int(bool(iso_wait) and iso_free == 0 and len(free) > 0),
                   "block_clean": int(len(q) > 0 and len(free) == 0 and dirty > 0),
                   "block_transport": int(len(q) > 0 and len(free) == 0 and ready_tr > 0)}
    TRACE.append(row)


def generate2(spec: Any, origin_ticks: list[int]) -> tuple[Any, list]:
    """Frozen generator, derived: B-FRAG arrival law (nominal capacity), NO background plans (common
    background policy = the frozen operator's built-in habitual operations), clones at every origin,
    and a per-tick dependency trace."""
    global _GEN
    if _GEN is None:
        src = inspect.getsource(G.generate)
        subs = [("    prov = TruthProvider(spec, 0)\n", "    prov = BFTruthProvider(spec, 0)\n"),
                ("    eval_ticks = {EVAL_DAY * TPD + h * TPH for h in INSTANT_HOURS}\n", "    eval_ticks = set(BF2_TICKS)\n"),
                ("        if t % TPH == 0 and local_hour(t) in INSTANT_HOURS:\n            if keep_instants and t in eval_ticks:\n"
                 "                instants[t] = eng.clone()\n            plan = behaviour_plan(spec, t)\n",
                 "        if keep_instants and t in eval_ticks:\n            instants[t] = eng.clone()\n"
                 "        if False:  # B-FRAG 2: no background plans\n            plan = behaviour_plan(spec, t)\n"),
                ("        eng.step(prov)\n    stays = {", "        eng.step(prov)\n        BF2_TRACE(eng)\n    stays = {")]
        for a, b in subs:
            if src.count(a) != 1:
                raise RuntimeError(f"generate2 derivation: pattern not found exactly once: {a[:60]!r}")
            src = src.replace(a, b)
        ns = dict(G.__dict__)
        ns.update({"BFTruthProvider": K.BFTruthProvider, "BF2_TRACE": _trace, "BF2_TICKS": []})
        exec(compile(src, "<bfrag2-derived generate>", "exec"), ns)  # noqa: S102
        _GEN = ns
    _GEN["BF2_TICKS"] = list(origin_ticks)
    TRACE.clear()
    ep = _GEN["generate"](spec, keep_instants=True)
    return ep, list(TRACE)


# ------------------------------------------------------------------------------ labels
def rupture_runs(trace: list) -> dict:
    """Per unit: episodes on the per-tick count of patients waiting >= 24 h (B-FRAG 1 rule).
    trace[i] is the state after the step of tick i."""
    return {un: K.episodes([row[un]["n24"] for row in trace]) for un in trace[0]}


def labels_at(runs: dict, t0: int, n_ticks: int) -> dict:
    """Origin t0 (state before tick t0 = trace index t0-1). Label: a rupture onset at trace index in
    [t0, t0 + 72 h). Censored if the 72-h window exceeds the trace (never labelled 'no rupture')."""
    onsets = sorted(a for v in runs.values() for a, _b, _s in v)
    active = any(a <= t0 - 1 < b for v in runs.values() for a, b, _s in v)
    nxt = next((o for o in onsets if o >= t0), None)
    censored = t0 + WINDOW_H * TPH > n_ticks
    return {"active": active, "censored": censored, "y72": None if censored else int(nxt is not None and nxt < t0 + WINDOW_H * TPH),
            "y24": int(nxt is not None and nxt < t0 + SECONDARY_H * TPH), "next_onset": nxt}


# ------------------------------------------------------------------------------ public views
def public_state(ep: Any, t0: int) -> tuple[list, PublicStream, Engine]:
    cut = 15 * t0
    pub = [o for o in ep.observations if o[1] < cut]
    ps = PublicStream(pub)
    ps.advance(cut - 1)
    peng = ps.to_engine(cut - 1)
    peng.tick = t0
    return pub, ps, peng


def s0_features(w: K.World, t0: int) -> dict:
    sp = w.spec
    f = {"nom_A": w.nominal["A"], "nom_B": w.nominal["B"], "beds_A": sp.beds["A"], "beds_B": sp.beds["B"],
         "iso_A": sp.iso_beds["A"], "iso_B": sp.iso_beds["B"], "c_tr": sp.c_tr, "c_cl": sp.c_cl,
         "buffer": (sp.beds["A"] + sp.beds["B"]) / max(1, w.nominal["A"] + w.nominal["B"]) - 1,
         "hour_sin": math.sin(2 * math.pi * local_hour(t0) / 24), "hour_cos": math.cos(2 * math.pi * local_hour(t0) / 24),
         "day": t0 / TPD, "weekday": float(is_weekday(t0))}
    for a, b in ((0, 24), (24, 48), (48, 72)):
        f[f"drop_{a}_{b}"] = float(any(K.drop_at(w.drop, t0 + k) for k in range(a * TPH, b * TPH)))
    return f


def s1_features(peng: Engine) -> dict:
    t = peng.tick
    f = {}
    for un, uu in peng.units.items():
        beds = [peng.beds[b] for b in uu.beds]
        q = peng.queue.get(un, [])
        waits = [(t - r.arrival) * 15 for r in q]
        stays = [s for s in peng.stays.values() if s.unit == un and s.departed is None]
        f.update({f"{un}_occ": sum(b.state == "occ" for b in beds) / len(beds), f"{un}_free": sum(b.state == "free" for b in beds),
                  f"{un}_free_iso": sum(b.state == "free" and b.iso for b in beds),
                  f"{un}_dirty": sum(b.state == "dirty" for b in beds), f"{un}_cleaning": sum(b.state == "cleaning" for b in beds),
                  f"{un}_q": len(q), f"{un}_maxwait_h": max(waits, default=0) / 60, f"{un}_q12": sum(w_ >= 720 for w_ in waits),
                  f"{un}_q24": sum(w_ >= 1440 for w_ in waits), f"{un}_q_iso": sum(r.iso for r in q),
                  f"{un}_ready_wait_tr": sum(1 for s in stays if s.ready and s.transport),
                  f"{un}_auth_not_ready": sum(1 for s in stays if s.authorised and not s.ready),
                  f"{un}_tr_requested": sum(1 for s in stays if s.tr_req is not None and not s.tr_accepted),
                  f"{un}_acuity3": sum(1 for s in stays if s.acuity == 3)})
    f["tr_busy"] = len(peng.tr_service)
    f["cl_busy"] = sum(1 for b in peng.beds.values() if b.state == "cleaning")
    return f


def manifest_pressure(f1: dict) -> bool:
    return f1["A_q12"] >= MANIFEST_K or f1["B_q12"] >= MANIFEST_K


S1_DELTA_KEYS = ("A_q", "B_q", "A_q12", "B_q12", "A_dirty", "B_dirty", "A_occ", "B_occ", "A_ready_wait_tr", "B_ready_wait_tr")


def s2_history(pub: list, t0: int, snaps: dict) -> dict:
    cut = 15 * t0
    f = {}
    for k in S1_DELTA_KEYS:
        for lag in (6, 24):
            prev = snaps.get(t0 // TPH - lag)
            f[f"d{lag}_{k}"] = snaps[t0 // TPH][k] - prev[k] if prev is not None else 0.0
    for wh in (6, 24):
        lo = cut - wh * 60
        win = [o for o in pub if o[0] >= lo]
        for kind in ("request_arrival", "placed", "departure", "cleaning_done", "transport_done", "ready", "authorised"):
            f[f"n{wh}_{kind}"] = sum(1 for o in win if o[2] == kind)
    first: dict = {}
    durs = {"cleaning": [], "transport": []}
    for ev, _av, kind, subj, _u, _v in pub:
        if kind in ("cleaning_start", "transport_start"):
            first[(kind, subj)] = ev
        elif kind == "cleaning_done" and ("cleaning_start", subj) in first and ev >= cut - 1440:
            durs["cleaning"].append(ev - first.pop(("cleaning_start", subj)))
        elif kind == "transport_done" and ("transport_start", subj) in first and ev >= cut - 1440:
            durs["transport"].append(ev - first.pop(("transport_start", subj)))
    f["dur24_cleaning"] = float(np.mean(durs["cleaning"])) if durs["cleaning"] else 0.0
    f["dur24_transport"] = float(np.mean(durs["transport"])) if durs["transport"] else 0.0
    lags = [av - ev for ev, av, kind, *_ in pub if ev >= cut - 1440 and kind not in G.ZERO_LAG]
    f["lag24_mean"] = float(np.mean(lags)) if lags else 0.0
    f["arr_rate_all"] = sum(1 for o in pub if o[2] == "request_arrival") / max(1.0, cut / 60)
    return f


# ------------------------------------------------------------------------------ risk scores (72 h)
def public_key2(pub: list) -> int:
    st = next(o[5] for o in pub if o[2] == "static")
    blob = json.dumps({"static": st, "n_obs": len(pub), "first": pub[:20], "last": pub[-5:]}, sort_keys=True, default=str)
    return int(hashlib.sha256(blob.encode()).hexdigest()[:15], 16)


def rollout_sched(eng0: Engine, prov: Any, plan: Plan | None, drop: dict, hours: int, extra: dict | None = None,
                  prime: bool = True) -> dict:
    """Continuous rollout; ``extra`` = {"cl": (start, end), "tr": (start, end)}: +1 agent in [start, end) ticks."""
    eng = eng0.clone()
    eng.emit_log = False
    p = K.WithCalendar(prov, drop)
    if prime:
        refresh_private(eng, p)
    t0 = eng.tick
    w0 = dict(eng.waiting_ticks)
    rej0 = eng.rejected
    base_cl, base_tr = eng.c_cl, eng.c_tr
    if plan is not None:
        eng.apply_plan(plan, p)
    rej_plan = eng.rejected - rej0
    n24 = {un: [] for un in eng.units}
    extra = extra or {}
    for _ in range(hours * TPH):
        t = eng.tick
        eng.c_cl = base_cl + (1 if "cl" in extra and extra["cl"][0] <= t < extra["cl"][1] else 0)
        eng.c_tr = base_tr + (1 if "tr" in extra and extra["tr"][0] <= t < extra["tr"][1] else 0)
        eng.step(p)
        tt = eng.tick
        for un in eng.units:
            n24[un].append(sum(1 for r in eng.queue.get(un, []) if (tt - r.arrival) * 15 >= K.WAIT_LIMIT_MIN))
    eng.c_cl, eng.c_tr = base_cl, base_tr
    runs = {un: K.episodes(s) for un, s in n24.items()}
    first = min([a for v in runs.values() for a, _b, _s in v], default=None)
    h0 = t0 // TPH
    return {"wait_patient_min": 15.0 * sum(eng.waiting_ticks.get(un, 0) - w0.get(un, 0) for un in eng.units),
            "uncovered_care_min": uncovered(eng, range(h0, h0 + hours)), "rejected_at_plan": rej_plan,
            "rejected_total": eng.rejected - rej0, "first_onset": first,
            "rupture": first is not None, "rupture_minutes": 15 * sum(b - a for v in runs.values() for a, b, _s in v),
            "terminal_queue": sum(len(q) for q in eng.queue.values()),
            "terminal_max_wait_min": max([(eng.tick - r.arrival) * 15 for q in eng.queue.values() for r in q], default=0)}


def f_pairs(w: K.World, pub: list, ps: PublicStream, peng: Engine, t0: int, M: int, rep: int = 0) -> list:
    """F (historical B-FRAG 1 chain, generalised to any origin): L4 posterior + L4-N nowcast (strict
    convention) + generator-structure simulator; keys derived from the public history (+ repetition)."""
    from howm2_decision import sample_world

    spec = w.spec
    static = next(o[5] for o in pub if o[2] == "static")
    lad = Ladder(spec.population, static, dict(w.nominal), None)
    pst = PublicState(spec.population, dict(spec.beds))
    pst.ingest(ps.obs[: ps.i])
    ctx = lad.context(pst, ps, 15 * t0 - 1)
    revealed = N.revealed_arrivals(ps, 15 * t0)
    pk = public_key2(pub)
    rng = np.random.default_rng(int(key("BF2-F", pk, rep) % (2**31)))
    out = []
    for m in range(M):
        th, mech, anchor = sample_world(lad, ctx, rng)
        s2 = replace(spec, theta=th, mech=mech, ekey=key("BF2-F-sim", pk, rep))
        K.NOMINAL[s2.ekey] = dict(w.nominal)
        prov = K.BFNowcastProvider(s2, 201 + m, th, anchor, t0, th["lag_min"])
        N.pending_arrivals = K.bf_pending_arrivals
        eng, _ = N.nowcast_engine(peng, prov, revealed)
        out.append((eng, K.bf_provider(s2, 201 + m, w.nominal, theta=th, regime_anchor=anchor)))
    return out


def o_pairs(w: K.World, spec_e: Any, ep: Any, t0: int, M: int, rep: int = 0) -> list:
    anchor = G.true_regime_at(ep, t0)
    return [(ep.instants[t0], K.bf_provider(spec_e, 101 + m + 1000 * rep, w.nominal, regime_anchor=anchor)) for m in range(M)]


def r1_pairs(w: K.World, pub: list, ps: PublicStream, peng: Engine, t0: int, p: Any, M: int, rep: int = 0) -> list:
    from hospitalos.howm.rollout import NewProfileFreq
    from hospitalos.howm2 import data as D
    from hospitalos.howm2.ladder import l2_predict

    H = t0 // TPH
    od = next(od for h, od, _ps in D.origins(SimpleNamespace(observations=pub), [H]) if h == H)
    pr = l2_predict(p, od, SimpleNamespace(n_beds=dict(w.nominal)), ps)
    f = p.new_profile_freq
    fr = NewProfileFreq(f["p_iso"], (f["p_acuity_1"], f["p_acuity_2"], f["p_acuity_3"]), f["p_transport"])
    bk = key("BF2-R1", public_key2(pub), rep)
    return [(peng, K.LongModelProvider(pr, od, t0, m, bk, fr)) for m in range(M)]


def risk72(pairs: list, drop: dict) -> float:
    return float(np.mean([rollout_sched(e, pv, None, drop, WINDOW_H)["rupture"] for e, pv in pairs]))


def score_R0(w: K.World, peng: Engine, t0: int) -> float:
    best = -1e9
    for un, uu in peng.units.items():
        beds = [peng.beds[b] for b in uu.beds]
        v = (len(peng.queue.get(un, [])) + sum(b.state in ("dirty", "cleaning") for b in beds) - sum(b.state == "free" for b in beds)) / len(beds)
        best = max(best, v)
    soon = any(K.drop_at(w.drop, t0 + k) for k in range(48 * TPH))
    return float(best + (0.5 if soon else 0.0))


# ------------------------------------------------------------------------------ intervention catalogue
STAFF_HOURS = 8
NOTICE_TICKS = 2 * TPH


def windows(t0: int) -> list[tuple[int, int]]:
    """The first four future 8-h cleaning-hour slots [06,14) / [14,22) starting >= 2 h after t0."""
    out = []
    day = t0 // TPD
    while len(out) < 4:
        for h in (6, 14):
            s = day * TPD + h * TPH
            if s >= t0 + NOTICE_TICKS:
                out.append((s, s + 8 * TPH))
                if len(out) == 4:
                    break
        day += 1
    return out


def catalogue(t0: int) -> list[dict]:
    w = windows(t0)
    acts = [{"id": "none", "plan": None, "extra": {}, "staff_hours": 0},
            {"id": "hist_coord_compat", "plan": Plan(True, "compat", "none"), "extra": {}, "staff_hours": 0}]
    for res in ("cl", "tr"):
        for k, win in enumerate(w):
            acts.append({"id": f"{res}+1_w{k + 1}", "plan": None, "extra": {res: win}, "staff_hours": STAFF_HOURS})
    return acts


def planner(pairs: list, drop: dict, acts: list[dict]) -> dict:
    loss = np.array([[rollout_sched(e, pv, a["plan"], drop, 168, a["extra"])["wait_patient_min"] for a in acts] for e, pv in pairs])
    mean = loss.mean(0)
    best = min(range(len(acts)), key=lambda i: (round(float(mean[i]), 6), acts[i]["staff_hours"], i))
    return {"choice": int(best), "mean_loss": mean.tolist()}


def evaluate_actions(w: K.World, spec_e: Any, ep: Any, t0: int, acts: list[dict], E: int) -> list[list[dict]]:
    anchor = G.true_regime_at(ep, t0)
    return [[rollout_sched(ep.instants[t0], K.bf_provider(spec_e, r, w.nominal, regime_anchor=anchor), a["plan"], w.drop, 168, a["extra"])
             for r in range(1, E + 1)] for a in acts]
