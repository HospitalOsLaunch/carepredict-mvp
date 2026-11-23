"""Decision n.8 pilot core: public inputs, action/calendar descriptors, 2-h step schedule and a
trajectory-recording 168-h rollout (same dynamics as core2.rollout_sched, plus state/cost every step)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from hospitalos.bfrag import core as K
from hospitalos.bfrag2 import core2 as C
from hospitalos.howm import generator as G
from hospitalos.howm.generator import refresh_private
from hospitalos.howm.world import TPH, Engine, Plan, local_hour, uncovered

ROOT = Path(__file__).resolve().parents[3]
DESIGN = json.loads((ROOT / "docs/howm2/bfrag/DESIGN_D2.json").read_text())
STEP_H = 2
STEP_TICKS = STEP_H * TPH
HORIZON_H = 168
N_STEPS = HORIZON_H // STEP_H  # 84
NEW_PARTS = {"BF2W_CONF": 200}  # final evaluation partition: NEW structures (registered size; used: protocol)
STATE_KEYS = None  # set from s1_features order at first use
COMPAT_H = 24  # hist_coord_compat: cleaning mode 'compat' for 24 h (frozen engine), transports requested at t0


def register() -> None:
    C.register()
    for p, n in NEW_PARTS.items():
        G.PARTITION_SIZES[p] = n
        G.POPULATION_OF[p] = "REF"


def structure(part: str, s: int) -> K.World:
    register()
    return K.make_world(part, s, DESIGN)


def public_inputs(w: K.World, ep: Any, t0: int) -> dict:
    """S0, S1, S2 at t0 exactly as the B-FRAG 2 driver computes them (snapshots at t0, t0-6h, t0-24h)."""
    h = t0 // TPH
    snaps = {}
    for hh in (h - 24, h - 6, h):
        if hh >= 0:
            snaps[hh] = C.s1_features(C.public_state(ep, hh * TPH)[2])
    pub, _ps, _pe = C.public_state(ep, t0)
    return {"S0": C.s0_features(w, t0), "S1": snaps[h], "S2": C.s2_history(pub, t0, snaps)}


def action_descriptor(a: dict, t0: int) -> dict:
    """Nature, resource, intensity, slot (start offset and duration in hours) -- not an opaque id."""
    is_coord = a["plan"] is not None
    res = next(iter(a["extra"]), None)
    start, end = a["extra"][res] if res else (t0, t0)
    return {"a_none": float(a["id"] == "none"), "a_coord": float(is_coord), "a_reinf": float(res is not None),
            "a_res_cl": float(res == "cl"), "a_res_tr": float(res == "tr"), "a_intensity": float(res is not None),
            "a_start_h": (start - t0) / TPH if res else 0.0, "a_dur_h": (end - start) / TPH if res else 0.0,
            "a_compat_h": float(COMPAT_H if is_coord else 0), "a_staff_h": float(a["staff_hours"])}


def calendar_descriptor(drop: dict, t0: int) -> dict:
    """Public planned drop relative to the origin, within the 168-h horizon."""
    ticks = [k for k in range(HORIZON_H * TPH) if K.drop_at(drop, t0 + k)]
    if not ticks:
        return {"c_has_drop": 0.0, "c_drop_start_h": 0.0, "c_drop_end_h": 0.0, "c_drop_minus": 0.0}
    return {"c_has_drop": 1.0, "c_drop_start_h": ticks[0] / TPH, "c_drop_end_h": (ticks[-1] + 1) / TPH, "c_drop_minus": float(drop["minus"])}


def step_schedule(adesc: dict, cdesc: dict, t0: int) -> np.ndarray:
    """Per 2-h step exogenous inputs derived ONLY from the descriptors and the origin time:
    [extra_cl, extra_tr, drop, compat_mode, coord_at_t0, hour_sin, hour_cos, step/84]; fractions of the
    step covered (exact when a boundary falls inside a step)."""
    out = np.zeros((N_STEPS, 8), np.float32)
    for k in range(N_STEPS):
        lo, hi = k * STEP_H, (k + 1) * STEP_H

        def cover(a, b):
            return max(0.0, min(hi, b) - max(lo, a)) / STEP_H
        if adesc["a_reinf"]:
            c = cover(adesc["a_start_h"], adesc["a_start_h"] + adesc["a_dur_h"])
            out[k, 0] = c * adesc["a_res_cl"]
            out[k, 1] = c * adesc["a_res_tr"]
        if cdesc["c_has_drop"]:
            out[k, 2] = cover(cdesc["c_drop_start_h"], cdesc["c_drop_end_h"]) * cdesc["c_drop_minus"]
        out[k, 3] = cover(0.0, adesc["a_compat_h"]) if adesc["a_coord"] else 0.0
        out[k, 4] = 1.0 if (k == 0 and adesc["a_coord"]) else 0.0
        hr = local_hour(t0) + lo
        out[k, 5], out[k, 6] = math.sin(2 * math.pi * hr / 24), math.cos(2 * math.pi * hr / 24)
        out[k, 7] = k / N_STEPS
    return out


def rollout_traj(eng0: Engine, prov: Any, plan: Plan | None, drop: dict, extra: dict | None = None) -> dict:
    """core2.rollout_sched dynamics (prime, plan at t0, capacity overrides, public calendar) for 168 h,
    recording at each 2-h step end the TRUE state (s1_features of the true engine) and the waiting
    patient-minutes accrued in the step per unit. Totals identical to rollout_sched (test)."""
    eng = eng0.clone()
    eng.emit_log = False
    p = K.WithCalendar(prov, drop)
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
    states, costs = [], []
    last = {un: eng.waiting_ticks.get(un, 0) for un in eng.units}
    for i in range(HORIZON_H * TPH):
        t = eng.tick
        eng.c_cl = base_cl + (1 if "cl" in extra and extra["cl"][0] <= t < extra["cl"][1] else 0)
        eng.c_tr = base_tr + (1 if "tr" in extra and extra["tr"][0] <= t < extra["tr"][1] else 0)
        eng.step(p)
        tt = eng.tick
        for un in eng.units:
            n24[un].append(sum(1 for r in eng.queue.get(un, []) if (tt - r.arrival) * 15 >= K.WAIT_LIMIT_MIN))
        if (i + 1) % STEP_TICKS == 0:
            cb, cc = eng.c_cl, eng.c_tr
            eng.c_cl, eng.c_tr = base_cl, base_tr
            states.append(list(C.s1_features(eng).values()))
            eng.c_cl, eng.c_tr = cb, cc
            now = {un: eng.waiting_ticks.get(un, 0) for un in eng.units}
            costs.append([15.0 * (now[un] - last[un]) for un in sorted(eng.units)])
            last = now
    eng.c_cl, eng.c_tr = base_cl, base_tr
    runs = {un: K.episodes(s) for un, s in n24.items()}
    first = min([a for v in runs.values() for a, _b, _s in v], default=None)
    h0 = t0 // TPH
    wbu = {un: 15.0 * (eng.waiting_ticks.get(un, 0) - w0.get(un, 0)) for un in eng.units}
    return {"wait_patient_min": sum(wbu.values()), "wait_by_unit": wbu, "uncovered_care_min": uncovered(eng, range(h0, h0 + HORIZON_H)),
            "rejected_at_plan": rej_plan, "rejected_total": eng.rejected - rej0, "first_onset": first, "rupture": first is not None,
            "rupture_minutes": 15 * sum(b - a for v in runs.values() for a, b, _s in v),
            "terminal_queue": sum(len(q) for q in eng.queue.values()),
            "terminal_max_wait_min": max([(eng.tick - r.arrival) * 15 for q in eng.queue.values() for r in q], default=0),
            "states": states, "step_costs": costs}
