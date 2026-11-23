"""Per-establishment data: public inputs (via history) + labels/masks (truth side, never inputs).

Origins are hour indices H (time t = 60 H minutes). For each origin:
  * public cohort items (history.PublicStream.cohort at t) with their item features;
  * labels from the realised corpus (end-event availability, arrivals, care, presence);
  * the care mask M(s, j) = stay s truly present at hour j (scoring/loss only, NORM N3.2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from .generator import EPISODE_TICKS, Episode
from .history import NODE_DIMS, NODE_TYPES, PublicStream, hourly_tables

N_HOURS = EPISODE_TICKS // 4
DATA_END_MIN = N_HOURS * 60
NB = 192  # hazard bins of 15 min (48 h); index 192 = tail "T >= 48 h"
HAZARD_FAMILIES = ("auth", "ready", "transport", "cleaning", "confirmation")
SCORED_HAZARD = (
    "ready",
    "transport",
    "cleaning",
    "confirmation",
)  # 'departure' = ready (NORM N3.4)
ITEM_DIM = 20
CARE_EDGES = np.array([5.0 * k for k in range(1, 121)])  # bin uppers 5..600; last bin [600, inf)
TYPED_RELATIONS = (
    ("stay", "occupies", "bed"),
    ("stay", "belongs_to", "unit"),
    ("bed", "belongs_to", "unit"),
    ("stay", "waits_for", "team"),
    ("bed", "waits_for", "team"),
    ("team", "serves", "unit"),
    ("offer", "reserves", "unit"),
    ("unit", "lends_to", "unit"),
)


def item_features(fam: str, it: dict[str, Any], t: int) -> list[float]:
    fams = ("auth", "ready", "transport", "cleaning", "confirmation", "presence")
    start = it.get("start", it.get("slot_start", t))
    q = (start // 15) % 96
    return [
        *[float(fam == f) for f in fams],
        float(it.get("unit") == "A"),
        float(it.get("acuity") == 1),
        float(it.get("acuity") == 2),
        float(it.get("acuity") == 3),
        float(bool(it.get("iso"))),
        float(bool(it.get("transport"))),
        max(0.0, (t - start)) / 1440.0,
        math.sin(2 * math.pi * q / 96),
        math.cos(2 * math.pi * q / 96),
        float(it.get("kind") == "offer"),
        float(it.get("skill") == "IDE"),
        float(it.get("source") == "pool"),
        (start - t) / 240.0 if fam == "presence" else 0.0,
        1.0,
    ]


@dataclass
class OriginData:
    H: int
    items: dict[str, list[dict[str, Any]]]  # family -> items (public) with 'x', labels
    arrivals: np.ndarray  # [2, 24] true counts for hours H..H+23 (-1 beyond data)
    care_ref: list[str]  # cohort stays (public)
    care_x: np.ndarray  # [n, ITEM_DIM]
    care: np.ndarray  # [n, 24, 2] true minutes
    care_mask: np.ndarray  # [n, 24] truly present (label side only)
    window: dict[str, Any]  # B0-local public window statistics


@dataclass
class EstablishmentData:
    partition: str
    index: int
    population: str
    n_beds: dict[str, int]
    b2: np.ndarray  # [N_HOURS, B2_DIM]
    nodes: dict[str, np.ndarray]  # type -> [N_HOURS, n_type, dim]
    present: dict[str, np.ndarray]  # type -> [N_HOURS, n_type] bool
    refs: dict[str, list[str]]  # type -> refs (join keys only)
    edges: list[dict[str, np.ndarray]]  # per hour: relation key -> [E, 2] (type-local indices)
    origins: dict[int, OriginData]
    mech: dict[str, Any]  # for stratified reporting only (never an input)
    bed_unit: dict[str, str]  # join table from the public static description


def _end_index(obs: list[tuple[int, int, str, str, str, dict[str, Any]]]) -> dict[str, Any]:
    first: dict[tuple[str, str], tuple[int, int]] = {}
    clean_done: dict[str, list[tuple[int, int]]] = {}
    for ev, av, kind, subj, _u, _v in obs:
        if kind == "cleaning_done":
            clean_done.setdefault(subj, []).append((ev, av))
        elif (kind, subj) not in first:
            first[(kind, subj)] = (ev, av)
    for v in clean_done.values():
        v.sort()
    return {"first": first, "clean_done": clean_done}


def hazard_label(fam: str, it: dict[str, Any], idx: dict[str, Any]) -> int | None:
    """Availability time (min) of the item's end event, or None if not in the data."""
    first = idx["first"]
    if fam == "auth":
        e = first.get(("authorised", it["ref"]))
    elif fam == "ready":
        e = first.get(("ready", it["ref"]))
    elif fam == "transport":
        e = first.get(("transport_done", it["ref"]))
    elif fam == "confirmation":
        kind, ref = it["ref"].split(":", 1)
        e = first.get(("transport_accepted" if kind == "T" else "offer_confirmed", ref))
    elif fam == "cleaning":
        e = next(
            ((ev, av) for ev, av in idx["clean_done"].get(it["ref"], []) if ev >= it["start"]), None
        )
    else:
        raise ValueError(fam)
    return None if e is None else e[1]


def build(ep: Episode, origins: list[int]) -> EstablishmentData:
    """Single pass over the public stream (hourly tables) + labels for the requested origins."""
    obs = ep.observations
    tables = hourly_tables(obs, N_HOURS)
    idx = _end_index(obs)
    # entity index per type over the whole episode (join keys only)
    refs: dict[str, list[str]] = {t: [] for t in NODE_TYPES}
    pos: dict[str, dict[str, int]] = {t: {} for t in NODE_TYPES}
    for g in tables.graphs:
        for t in NODE_TYPES:
            for ref, _ in g["nodes"][t]:
                if ref not in pos[t]:
                    pos[t][ref] = len(refs[t])
                    refs[t].append(ref)
    nodes = {
        t: np.zeros((N_HOURS, max(1, len(refs[t])), NODE_DIMS[t]), np.float32) for t in NODE_TYPES
    }
    present = {t: np.zeros((N_HOURS, max(1, len(refs[t]))), bool) for t in NODE_TYPES}
    edges: list[dict[str, np.ndarray]] = []
    for h, g in enumerate(tables.graphs):
        for t in NODE_TYPES:
            for ref, feats in g["nodes"][t]:
                i = pos[t][ref]
                nodes[t][h, i] = feats
                present[t][h, i] = True
        e_h: dict[str, list[tuple[int, int]]] = {}
        for rel, pairs in g["edges"].items():
            for a, b in pairs:
                ta, ra = a.split(":", 1)
                tb, rb = b.split(":", 1)
                if ra in pos[ta] and rb in pos[tb]:
                    e_h.setdefault(f"{ta}|{rel}|{tb}", []).append((pos[ta][ra], pos[tb][rb]))
        edges.append({k: np.asarray(v, np.int64) for k, v in e_h.items()})
    # labels
    arrivals_true = np.zeros((2, N_HOURS), np.int64)
    care_true: dict[str, dict[int, tuple[float, float]]] = {}
    presence: dict[str, bool] = {}
    for ev, _av, kind, subj, un, v in obs:
        if kind == "request_arrival":
            arrivals_true["AB".index(un), ev // 60] += 1
        elif kind == "care_due":
            care_true.setdefault(subj, {})[v["hour"]] = (v["ide"], v["as_"])
        elif kind in ("offer_present", "offer_absent"):
            presence[subj] = kind == "offer_present"
    out: dict[int, OriginData] = {}
    ps = PublicStream(obs)
    want = sorted(set(origins))
    for H in want:
        t = H * 60
        ps.advance(t)
        coh = ps.cohort(t)
        items: dict[str, list[dict[str, Any]]] = {}
        for fam, lst in coh.items():
            rows = []
            for it in lst:
                it = dict(it)
                it["x"] = item_features(fam, it, t)
                if fam == "presence":
                    it["label"] = presence.get(it["ref"])
                else:
                    it["end_avail"] = hazard_label(fam, it, idx)
                rows.append(it)
            items[fam] = rows
        arr = np.full((2, 24), -1, np.int64)
        for k in range(24):
            if H + k < N_HOURS:
                arr[:, k] = arrivals_true[:, H + k]
        stays = ps.present_stays()
        care_ref = sorted(stays)
        n = len(care_ref)
        care = np.zeros((n, 24, 2), np.float32)
        mask = np.zeros((n, 24), bool)
        cx = np.zeros((n, ITEM_DIM), np.float32)
        for i, sid in enumerate(care_ref):
            st = stays[sid]
            cx[i] = item_features(
                "care",
                {
                    "unit": st["unit"],
                    "acuity": st["acuity"],
                    "iso": st["iso"],
                    "transport": st["transport"],
                    "start": st["placed"],
                },
                t,
            )
            for k in range(24):
                val = care_true.get(sid, {}).get(H + k)
                if val is not None:
                    care[i, k] = val
                    mask[i, k] = True
        out[H] = OriginData(
            H,
            items,
            arr,
            care_ref,
            cx,
            care,
            mask,
            _window(ps, t, arrivals_obs=_arrivals_known(ps, t)),
        )
    return EstablishmentData(
        ep.spec.partition,
        ep.spec.index,
        ep.spec.population,
        dict(ep.spec.beds),
        tables.b2,
        nodes,
        present,
        refs,
        edges,
        out,
        dict(ep.spec.mech),
        {b: un for un, d in _public_static(obs)["units"].items() for b, _ in d["beds"]},
    )


def _public_static(obs: list[tuple[int, int, str, str, str, dict[str, Any]]]) -> dict[str, Any]:
    return next(o[5] for o in obs if o[2] == "static")


def _arrivals_known(ps: PublicStream, t: int) -> np.ndarray:
    """Arrival counts per unit for the 24 hours before t, as KNOWN at t (public)."""
    cnt = np.zeros((2, 24), np.int64)
    for o in ps.obs[: ps.i]:
        if o[2] == "request_arrival" and t - 1440 <= o[0] < t:
            cnt["AB".index(o[4]), (o[0] - (t - 1440)) // 60] += 1
    return cnt


def _window(ps: PublicStream, t: int, arrivals_obs: np.ndarray) -> dict[str, Any]:
    """Public statistics of the window (t-24h, t] for B0-local (NORM: same window W as the nets)."""
    lo = t - 1440
    w: dict[str, list[tuple[int, int | None, dict[str, Any]]]] = {f: [] for f in HAZARD_FAMILIES}
    known = ps.obs[: ps.i]
    first: dict[tuple[str, str], int] = {}
    for ev, av, kind, subj, _u, _v in known:
        first.setdefault((kind, subj), ev)
    starts = {
        "auth": "placed",
        "ready": "authorised",
        "transport": "transport_start",
        "confirmation": "transport_requested",
    }
    ends = {
        "auth": "authorised",
        "ready": "ready",
        "transport": "transport_done",
        "confirmation": "transport_accepted",
    }
    avail_end: dict[tuple[str, str], int] = {}
    for ev, av, kind, subj, _u, _v in known:
        avail_end.setdefault((kind, subj), av)
    for fam in ("auth", "ready", "transport", "confirmation"):
        for (kind, subj), ev in first.items():
            if kind != starts[fam] or ev < lo:
                continue
            end = avail_end.get((ends[fam], subj))
            w[fam].append((ev, end, {}))
    cl_start: dict[str, int] = {}
    for ev, av, kind, subj, _u, _v in known:
        if kind == "cleaning_start" and ev >= lo:
            cl_start[f"{subj}@{ev}"] = ev
    done = sorted((ev, av, subj) for ev, av, kind, subj, _u, _v in known if kind == "cleaning_done")
    for keyv, s in cl_start.items():
        bed = keyv.split("@")[0]
        end = next((av for ev, av, b in done if b == bed and ev >= s), None)
        w["cleaning"].append((s, end, {}))
    care = [
        (v["ide"], v["as_"])
        for ev, av, kind, subj, _u, v in known
        if kind == "care_due" and ev >= lo
    ]
    pres = [
        kind == "offer_present"
        for ev, av, kind, subj, _u, v in known
        if kind in ("offer_present", "offer_absent") and ev >= lo
    ]
    return {"t": t, "hazard": w, "arrivals": arrivals_obs, "care": care, "presence": pres}
