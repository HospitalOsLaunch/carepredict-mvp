"""Shared machinery of HOWM-2 A' (addendum A2-1): instants, L4-N / L5-N draws, truth of the
pending state."""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from hospitalos.howm import generator as G
from hospitalos.howm.generator import EVAL_DAY, INSTANT_HOURS
from hospitalos.howm.history import PublicStream
from hospitalos.howm.world import TPD, TPH, Engine

from . import nowcast as N
from .filter import Ladder, PublicState

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

ELEMENT_TYPES = ("auth", "ready", "conf_transport", "conf_offer", "transport", "cleaning")
TYPES = (*ELEMENT_TYPES, "arrival")
END_KIND = {
    "authorised": "auth",
    "ready": "ready",
    "transport_accepted": "conf_transport",
    "offer_confirmed": "conf_offer",
    "transport_done": "transport",
    "cleaning_done": "cleaning",
}
ARR_WINDOW_H = 14  # >= the largest pending window for lag_min <= 60 (55 ticks)


def taus() -> list[int]:
    return [EVAL_DAY * TPD + h * TPH for h in INSTANT_HOURS]


@dataclass
class Instant:
    part: str
    idx: int
    tau: int
    spec: Any
    ep: Any
    ps: PublicStream
    peng: Engine
    lad: Ladder
    ctx: dict
    revealed: dict


def setup(part: str, idx: int, ep: Any | None = None) -> list[Instant]:
    if ep is None:
        ep = G.generate(G.establishment(part, idx), keep_instants=True)
    spec = ep.spec
    static = next(o[5] for o in ep.observations if o[2] == "static")
    out = []
    for tau in taus():
        t = tau * 15
        ps = PublicStream(ep.observations)
        ps.advance(t)
        peng = ps.to_engine(t)
        lad = Ladder(spec.population, static, dict(spec.beds), None)
        pub = PublicState(spec.population, dict(spec.beds))
        pub.ingest(ps.obs[: ps.i])
        ctx = lad.context(pub, ps, t)
        out.append(Instant(part, idx, tau, spec, ep, ps, peng, lad, ctx, N.revealed_arrivals(ps, t)))
    return out


def l4n_draw(ins: Instant, rng: np.random.Generator, r: int):
    """One L4-N draw: world from the L4 posterior (A's sample_world, consuming ``rng`` exactly as
    A's planner does), then the nowcast engine. -> (th, mech, anchor, s2, prov, eng, applied)."""
    from howm2_decision import sample_world

    th, mech, anchor = sample_world(ins.lad, ins.ctx, rng)
    s2 = replace(ins.spec, theta=th, mech=mech)
    prov = N.NowcastProvider(s2, r, th, anchor, ins.tau, th["lag_min"])
    eng, applied = N.nowcast_engine(ins.peng, prov, ins.revealed)
    return th, mech, anchor, s2, prov, eng, applied


def l5n_draw(ins: Instant, r: int):
    """L5-N: true theta, mechanism, lag mean and past hourly regimes."""
    spec, ep = ins.spec, ins.ep
    anchor = G.true_regime_at(ep, ins.tau)
    prov = N.NowcastProvider(spec, r, dict(spec.theta), anchor, ins.tau, spec.theta["lag_min"])
    H = ins.tau // TPH
    if spec.mech["m2"]:
        teams = ["common"] if spec.mech["m2_common"] else ["transport", "cleaning"]
        for team in teams:
            src = ep.regimes["transport" if team == "common" else team]
            for h in range(H + 1):
                prov._reg[(team, h)] = int(src[h])
    eng, applied = N.nowcast_engine(ins.peng, prov, ins.revealed)
    return prov, eng, applied


def first_order_elements(peng: Engine) -> list[tuple[str, str]]:
    out = []
    for st in sorted(peng.stays.values(), key=lambda s: s.sid):
        if st.departed is not None:
            continue
        if not st.authorised:
            out.append(("auth", st.sid))
        elif not st.ready and st.auth_tick is not None:
            out.append(("ready", st.sid))
        if st.tr_req is not None and not st.tr_accepted:
            out.append(("conf_transport", st.sid))
        if st.tr_start is not None and st.sid in peng.tr_service:
            out.append(("transport", st.sid))
    for b in sorted(peng.beds.values(), key=lambda b: b.bed_id):
        if b.state == "cleaning" and b.clean_start is not None:
            out.append(("cleaning", b.bed_id))
    for oid in sorted(peng.offers):
        o = peng.offers[oid]
        if not o.confirmed and o.source == "pool":
            out.append(("conf_offer", oid))
    return out


def arrival_cells(ins: Instant) -> list[tuple[str, int]]:
    H = ins.tau // TPH
    return [(un, h) for un in sorted(ins.peng.units) for h in range(max(0, H - ARR_WINDOW_H), H)]


def truth_state(ins: Instant) -> dict[str, Any]:
    """Pending truth at t: element indicators, arrival counts per cell, totals per type."""
    t = ins.tau * 15
    pend_end: set[tuple[str, str]] = set()
    clean_pend: dict[str, list[int]] = {}
    totals: Counter = Counter()
    arr: Counter = Counter()
    known_rids = {o[3] for o in ins.ps.obs[: ins.ps.i] if o[2] == "request_arrival"}
    known_rids |= {
        o[5]["rid"] for o in ins.ps.obs[: ins.ps.i] if o[2] == "placed" and "rid" in o[5]
    }
    for ev, av, kind, subj, un, _v in ins.ep.observations:
        if not ev < t < av:
            continue
        if kind in END_KIND:
            typ = END_KIND[kind]
            totals[typ] += 1
            if typ == "cleaning":
                clean_pend.setdefault(subj, []).append(ev)
            else:
                pend_end.add((typ, subj))
        elif kind == "request_arrival" and subj not in known_rids:
            totals["arrival"] += 1
            arr[(un, ev // 60)] += 1
    elems = {}
    for typ, ref in first_order_elements(ins.peng):
        if typ == "cleaning":
            cs = ins.peng.beds[ref].clean_start * 15
            elems[(typ, ref)] = int(any(e >= cs for e in clean_pend.get(ref, [])))
        else:
            elems[(typ, ref)] = int((typ, ref) in pend_end)
    return {
        "elements": elems,
        "arrivals": {c: arr.get(c, 0) for c in arrival_cells(ins)},
        "totals": {k: totals.get(k, 0) for k in TYPES},
    }


def draw_summary(applied: list[tuple[str, str, int]], ins: Instant) -> dict[str, Any]:
    elems = {(typ, ref) for typ, ref, _e in applied if typ != "arrival"}
    arr: Counter = Counter()
    tot: Counter = Counter()
    for typ, ref, _e in applied:
        tot[typ] += 1
        if typ == "arrival":
            un, h = ref.split(":")
            arr[(un, int(h))] += 1
    return {"elements": elems, "arrivals": arr, "totals": {k: tot.get(k, 0) for k in TYPES}}
