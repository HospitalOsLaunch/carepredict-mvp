"""HOWM-INT-1 public inputs (identical for W and D): a graph of unit nodes and resource nodes built ONLY from
the policy's own public history (observations available strictly before the decision tick).

Unit node (UNIT_F): capacity and isolation, public bed states, admission queue and waits, readiness and
transport backlog, transfers (out pending / in queued), external-downstream blocking, staff roster and
public offers, plus history summaries (deltas over 6 h and 24 h, public event counts over 6 h and 24 h).
Resource nodes: cleaning (team size, busy, dirty beds, public calendar drop now/next 24 h, extra committed),
transport (team size, busy, requested/accepted backlog, extra committed), external downstream (slots per day,
used today, blocked, purchased). Global: clock, day, budgets left, compat mode, horizon index.
Edges: unit-resource (all units use cleaning and transport; units with downstream flags use 'aval'), unit->unit
transfer edges (public structural probabilities are NOT used: only observed transfer requests in the last 72 h
and the public 'route' destinations of present stays)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from hospitalos.bfrag import core as K
from hospitalos.howm.world import TPD, TPH, local_hour

from . import actions as A

UNIT_F = ("beds", "nominal", "iso_beds", "occ", "free", "free_iso", "dirty", "cleaning", "queue", "q_iso", "maxwait_h", "q12", "q24",
          "auth_not_ready", "ready_wait_tr", "tr_requested", "acuity3", "transfer_out_wait", "transfer_in_queue", "dest_flagged",
          "aval_flagged", "aval_blocked", "roster_ide_now", "roster_ide_8h", "offers_active", "commit_staff_8h")
HIST_KEYS = ("occ", "queue", "q12", "dirty", "ready_wait_tr", "transfer_out_wait", "aval_blocked")
EV_KINDS = ("request_arrival", "placed", "departure", "cleaning_done", "transport_done", "ready", "authorised")
UNIT_DIM = len(UNIT_F) + 2 * len(HIST_KEYS) + 2 * len(EV_KINDS)
RES = ("cleaning", "transport", "aval")
RES_F = ("team", "busy", "backlog", "backlog_iso_pressure", "drop_now", "drop_next24", "extra_now", "extra_next24", "slots", "used_today")
RES_DIM = len(RES_F)
GLOB_F = ("hsin", "hcos", "day_frac", "weekday", "budget_day_left", "budget_week_left", "compat_active", "n_units")
GLOB_DIM = len(GLOB_F)


def unit_raw(eng: Any, ps: Any, un: str) -> dict[str, float]:
    t = eng.tick
    u = eng.units[un]
    beds = [eng.beds[b] for b in u.beds]
    q = eng.queue.get(un, [])
    waits = [(t - r.arrival) * 15 for r in q]
    stays = [s for s in eng.stays.values() if s.unit == un and s.departed is None]
    h = t // TPH
    ro = u.roster["IDE"]
    offers = [o for o in eng.offers.values() if o.unit == un and o.start <= t + 8 * TPH and o.end > t and o.present is not False]
    return {"beds": len(beds), "nominal": float((ps.static or {}).get("nominal", {}).get(un, len(beds))), "iso_beds": sum(b.iso for b in beds),
            "occ": sum(b.state == "occ" for b in beds), "free": sum(b.state == "free" for b in beds),
            "free_iso": sum(b.state == "free" and b.iso for b in beds), "dirty": sum(b.state == "dirty" for b in beds),
            "cleaning": sum(b.state == "cleaning" for b in beds), "queue": len(q), "q_iso": sum(r.iso for r in q),
            "maxwait_h": max(waits, default=0) / 60, "q12": sum(w >= 720 for w in waits), "q24": sum(w >= 1440 for w in waits),
            "auth_not_ready": sum(1 for s in stays if s.authorised and not s.ready),
            "ready_wait_tr": sum(1 for s in stays if s.ready and s.transport and s.tr_end is None),
            "tr_requested": sum(1 for s in stays if s.tr_req is not None and not s.tr_accepted), "acuity3": sum(s.acuity == 3 for s in stays),
            "transfer_out_wait": sum(1 for s in stays if getattr(s, "transfer_requested", False)),
            "transfer_in_queue": sum(1 for r in q if r.rid.startswith("T")), "dest_flagged": sum(1 for s in stays if getattr(s, "dest", None)),
            "aval_flagged": sum(1 for s in stays if getattr(s, "aval", False)), "aval_blocked": sum(1 for s in stays if s.sid in eng.aval_blocked),
            "roster_ide_now": ro[min(h, len(ro) - 1)], "roster_ide_8h": ro[min(h + 8, len(ro) - 1)], "offers_active": len(offers),
            "commit_staff_8h": sum(c["k"] for c in eng.commitments if c["res"] == "staff" and c["unit"] == un and c["start"] < t + 8 * TPH and c["end"] > t)}


def _ev_counts(ps: Any, un: str, t: int, hours: int) -> list[float]:
    lo = 15 * t - hours * 60
    win = [o for o in ps.obs[: ps.i] if o[0] >= lo and o[4] == un]
    return [float(sum(1 for o in win if o[2] == k)) for k in EV_KINDS]


def graph(eng: Any, ps: Any, hist: dict[int, dict] | None, units: list[str], t_start: int, n_units: int) -> dict[str, np.ndarray]:
    """Graph tensors at the decision tick. ``hist`` maps lag hours (6, 24) -> {unit: unit_raw} computed at t - lag
    from the SAME policy's public stream (None -> zeros)."""
    t = eng.tick
    rows = []
    raws = {un: unit_raw(eng, ps, un) for un in units}
    for un in units:
        r = raws[un]
        v = [float(r[k]) for k in UNIT_F]
        for lag in (6, 24):
            prev = (hist or {}).get(lag, {}).get(un)
            v += [float(r[k] - prev[k]) if prev else 0.0 for k in HIST_KEYS]
        v += _ev_counts(ps, un, t, 6) + _ev_counts(ps, un, t, 24)
        rows.append(v)
    drop = eng.spec_meta.get("drop", {})
    beds = list(eng.beds.values())
    present = [s for s in eng.stays.values() if s.departed is None]
    cl = [eng.base_c_cl, sum(b.state == "cleaning" for b in beds), sum(b.state == "dirty" for b in beds),
          sum(1 for r in sum(eng.queue.values(), []) if r.iso), float(K.drop_at(drop, t)),
          float(sum(K.drop_at(drop, t + k) for k in range(0, 24 * TPH, TPH))) / 24, eng.active_extra("cl", t),
          float(sum(eng.active_extra("cl", t + k) for k in range(0, 24 * TPH, TPH))) / 24, 0.0, 0.0]
    tr = [eng.base_c_tr, len(eng.tr_service), sum(1 for s in present if s.ready and s.transport and s.tr_end is None),
          sum(1 for s in present if s.tr_req is not None and not s.tr_accepted), 0.0, 0.0, eng.active_extra("tr", t),
          float(sum(eng.active_extra("tr", t + k) for k in range(0, 24 * TPH, TPH))) / 24, 0.0, 0.0]
    av = [0.0, 0.0, float(len(eng.aval_blocked)), 0.0, 0.0, 0.0, eng.active_extra("av", t), 0.0, float(eng.aval_cap(t)),
          float(eng.aval_used.get(t // TPD, 0))]
    day_cap, week_cap = A.budgets(n_units)
    per_day, _tot = A.used_hours(eng)
    week = sum(v for d, v in per_day.items() if d >= t_start // TPD)
    g = [math.sin(2 * math.pi * local_hour(t) / 24), math.cos(2 * math.pi * local_hour(t) / 24), ((t - t_start) / TPD) / 7,
         float((t // TPD) % 7 < 5), (day_cap - per_day.get(t // TPD, 0.0)) / day_cap, (week_cap - week) / week_cap,
         float(eng.cleaning_mode_until >= t), n_units / 12]
    # edges: unit -> resource (always cleaning, transport; aval if structure has slots), unit -> unit (observed transfers)
    src, dst = [], []
    for i, un in enumerate(units):
        for j in (0, 1):
            src.append(i)
            dst.append(j)
        if eng.spec_meta.get("aval_slots", 0) > 0:
            src.append(i)
            dst.append(2)
    uu = np.zeros((len(units), len(units)), np.float32)
    idx = {un: i for i, un in enumerate(units)}
    for s in present:
        d = getattr(s, "dest", None)
        if d in idx:
            uu[idx[s.unit], idx[d]] += 1.0
    for r in sum(eng.queue.values(), []):
        if r.rid.startswith("T"):
            o = eng.stays.get(r.rid[1:])
            if o is not None and o.unit in idx:
                uu[idx[o.unit], idx[r.unit]] += 1.0
    return {"unit": np.array(rows, np.float32), "res": np.array([cl, tr, av], np.float32), "glob": np.array(g, np.float32),
            "ur_src": np.array(src, np.int16), "ur_dst": np.array(dst, np.int16), "uu": uu}


def schedule(seq: list[dict | None], units: list[str], t0: int, n_steps: int, interval_h: int, drop: dict, step_h: int = 2) -> dict:
    """Exogenous per-step inputs of an action SEQUENCE, derived only from the descriptors and the public calendar:
    unit nodes [n_steps, n_units, 3] (staff +k coverage, coord-at-step, compat coverage) and resource nodes
    [n_steps, 3, 3] (extra agents/slots coverage, calendar drop, decision-boundary flag); clock [n_steps, 3]."""
    U = np.zeros((n_steps, len(units), 3), np.float32)
    R = np.zeros((n_steps, 3, 3), np.float32)
    C = np.zeros((n_steps, 3), np.float32)
    idx = {un: i for i, un in enumerate(units)}
    for k in range(n_steps):
        lo, hi = t0 + k * step_h * TPH, t0 + (k + 1) * step_h * TPH

        def cover(a: int, b: int) -> float:
            return max(0, min(hi, b) - max(lo, a)) / (step_h * TPH)
        for j, a in enumerate(seq):
            if a is None:
                continue
            off = j * interval_h * TPH
            s, e = a["start"] + (off if j and a["kind"] in ("none", "coord", "av") else 0), a["end"]
            if j and a["kind"] in ("cl", "tr", "staff"):
                sl = A.slots(t0 + off, 4)
                s, e = sl[a["slot"] - 1] if a["slot"] - 1 < len(sl) else (0, 0)
            if j and a["kind"] in ("coord", "av"):
                e = s + 24 * TPH
            c = cover(s, e)
            if a["kind"] == "staff":
                U[k, idx[a["unit"]], 0] += c * a.get("k", 1)
            elif a["kind"] == "coord":
                U[k, :, 2] += c
                if lo <= s < hi:
                    U[k, :, 1] += 1.0
            elif a["kind"] in ("cl", "tr", "av"):
                R[k, ("cl", "tr", "av").index(a["kind"]), 0] += c * a.get("k", 1)
        R[k, 0, 1] = float(np.mean([K.drop_at(drop, x) for x in range(lo, hi)]))
        R[k, :, 2] = float(any(lo == t0 + j * interval_h * TPH for j in range(1, 8)))
        hr = local_hour(lo)
        C[k] = [math.sin(2 * math.pi * hr / 24), math.cos(2 * math.pi * hr / 24), k / max(1, n_steps)]
    return {"U": U, "R": R, "C": C}


def seq_descriptor(seq: list[dict | None], t0: int) -> np.ndarray:
    out = []
    for a in seq:
        out += A.descriptor(a, t0) if a is not None else [1.0] + [0.0] * (len(A.DESC_NAMES) - 1)
    return np.array(out, np.float32)
