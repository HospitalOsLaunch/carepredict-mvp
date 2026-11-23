"""L4-N / L5-N: filter of the present state (HOWM-2 A', programme section 2, addendum A2-1).

A draw of S_true(t) given the public history is built in three steps:
1. a world draw (theta, mechanism, regime at tau, publication-lag mean) from the L4 posterior
   (unchanged; L5-N uses the true values);
2. for every PUBLIC in-progress element, its pending end event: the end time E is drawn from the
   generator law of the element given its stage start, and accepted with the probability that it
   is still unpublished at t (E >= t0, or lag > t - E for E < t0); rejection sampling with keyed
   draws (CRN), at most MAX_ATTEMPTS attempts, otherwise the element is declared not pending;
   unpublished arrivals per (unit, past hour): exact negative-binomial thinning posterior;
3. the events with E < t0 are applied to a clone of S_pub(t) in time order, at their own tick,
   by the engine's own semantics (authorisation -> readiness draw, readiness -> departure for a
   stay without transport, transport end -> departure, cleaning end, confirmations); chained
   stages are drawn the same way. Precondition violations are counted (``eng.rejected``), never
   corrected. Operator decisions (placements, transport and cleaning starts) are NOT back-dated:
   the operator takes them from the nowcast state at t0.

Only generator laws and priors are used; no private quantity enters L4-N.
"""

from __future__ import annotations

import heapq
import math
from typing import Any

from scipy.stats import nbinom

from hospitalos.howm import generator as G
from hospitalos.howm.keys import u as ku
from hospitalos.howm.world import TPH, Engine, Request

CUTOFF = 1e-6  # a past tick whose pending probability is below this is treated as published
MAX_ATTEMPTS = 64
ARR_R = 3.0


def pending_survival(theta_lag: float, k: int) -> float:
    """P(lag > 15k) for an event k ticks before t0: lag = floor(Exp(theta)) minutes."""
    if theta_lag <= 0:
        return 0.0
    return math.exp(-(15 * k + 1) / theta_lag)


def window_ticks(theta_lag: float) -> int:
    """Largest k >= 1 with pending_survival >= CUTOFF (0 if none)."""
    if theta_lag <= 0:
        return 0
    k = int(math.floor((-theta_lag * math.log(CUTOFF) - 1) / 15))
    return max(0, k)


class _At:
    """Engine view with a different ``tick`` (for conditional draws from an earlier time)."""

    def __init__(self, eng: Engine, tick: int):
        self._e = eng
        self.tick = tick

    def __getattr__(self, n: str) -> Any:
        return getattr(self._e, n)


class NowcastProvider(G.TruthProvider):
    """TruthProvider whose draws for elements started before t0 are conditioned on
    non-publication at t (only while ``active``). Draw keys carry the attempt number."""

    def __init__(self, spec: Any, r: int, theta: dict, regime_anchor: dict, t0: int, lag: float):
        super().__init__(spec, r, theta=theta, regime_anchor=regime_anchor)
        self.t0 = t0
        self.lag = lag
        self.K = window_ticks(lag)
        self.active = False
        self._attempt: int | None = None
        self.fallbacks = 0

    def _u(self, *parts: object) -> float:
        if self._attempt is None:
            return super()._u(*parts)
        return ku(self.spec.ekey, self.r, "nowcast", self._attempt, *parts)

    def _nowcast(self, draw, start: int, ident: tuple) -> int | None:
        """-> pending tick E < t0, or None (not pending)."""
        lo = max(start, self.t0 - self.K)
        if not self.active or self.K == 0 or lo >= self.t0:
            return None
        for a in range(MAX_ATTEMPTS):
            self._attempt = a
            try:
                e = draw(lo - 1)
                acc = ku(self.spec.ekey, self.r, "nowcast-acc", a, *ident)
            finally:
                self._attempt = None
            if e >= self.t0:
                return None
            if acc < pending_survival(self.lag, self.t0 - e):
                return int(e)
        self.fallbacks += 1
        return None

    # element-level pending draws (the engine argument is the real engine)
    def pend_auth(self, eng: Engine, st: Any) -> int | None:
        return self._nowcast(
            lambda f: G.TruthProvider.auth_tick(self, _At(eng, f), st),
            st.placed_tick,
            ("auth", st.sid),
        )

    def pend_ready(self, eng: Engine, st: Any) -> int | None:
        return self._nowcast(
            lambda f: G.TruthProvider.ready_tick(self, _At(eng, f), st),
            st.auth_tick,
            ("ready", st.sid),
        )

    def pend_conf(self, eng: Engine, kind: str, ref: str, req: int) -> int | None:
        return self._nowcast(
            lambda f: G.TruthProvider.confirm_tick(self, _At(eng, f), kind, ref, req),
            req,
            ("conf", kind, ref),
        )

    def pend_transport(self, eng: Engine, st: Any) -> int | None:
        return self._nowcast(
            lambda f: G.TruthProvider.transport_end(self, _At(eng, f), st),
            st.tr_start,
            ("transport", st.sid),
        )

    def pend_cleaning(self, eng: Engine, bed: Any) -> int | None:
        return self._nowcast(
            lambda f: G.TruthProvider.cleaning_end(self, _At(eng, f), bed),
            bed.clean_start,
            ("cleaning", bed.bed_id),
        )


def arrivals_mean(theta: dict, n_beds: int, hour: int) -> float:
    return (
        n_beds * 0.93 / (theta["los_days"] * 24) * G.HOUR_PROFILE[hour % 24] * theta["arr_mult"]
    )


def pending_arrivals(
    prov: NowcastProvider, eng: Engine, revealed: dict[tuple[str, int], int]
) -> list[tuple[str, int, int]]:
    """Unpublished, unrevealed arrivals: list of (unit, hour, count). ``revealed[(unit, hour)]`` =
    arrivals of that hour already known (published arrival event or revealed by a placement)."""
    out = []
    t0 = prov.t0
    for unit in sorted(eng.units):
        n_beds = len(eng.units[unit].beds)
        for hour in range(max(0, (t0 - prov.K) // TPH), (t0 - 1) // TPH + 1):
            k = t0 - hour * TPH
            if k <= 0:
                continue
            q = pending_survival(prov.lag, k)
            if q < CUTOFF:
                continue
            mu = arrivals_mean(prov.th, n_beds, hour)
            n = revealed.get((unit, hour), 0)
            beta = ARR_R / mu
            p = (beta + 1 - q) / (beta + 1)
            c = int(nbinom.ppf(ku(prov.spec.ekey, prov.r, "nowcast-arr", unit, hour), ARR_R + n, p))
            if c > 0:
                out.append((unit, hour, c))
    return out


def revealed_arrivals(ps: Any, t: int) -> dict[tuple[str, int], int]:
    """Arrivals known at t per (unit, hour): published arrival events plus requests revealed only
    by a published placement (rid R<unit><hour>_<i>)."""
    out: dict[tuple[str, int], int] = {}
    seen = set()
    for ev, _av, kind, subj, un, v in ps.obs[: ps.i]:
        if kind == "request_arrival":
            out[(un, ev // 60)] = out.get((un, ev // 60), 0) + 1
            seen.add(subj)
        elif kind == "placed" and "rid" in v and v["rid"] not in seen:
            rid = v["rid"]
            if rid.startswith("R") and "_" in rid:
                unit, hh = rid[1], int(rid[2:].split("_")[0])
                if hh * 60 < t:
                    out[(unit, hh)] = out.get((unit, hh), 0) + 1
                    seen.add(rid)
    return out


def nowcast_engine(
    peng: Engine, prov: NowcastProvider, revealed: dict[tuple[str, int], int]
) -> tuple[Engine, list[tuple[str, str, int]]]:
    """-> (engine at t0 with the pending events applied, list of (type, ref, tick) applied).
    When no pending event is possible (K = 0) the public engine is returned unchanged."""
    if prov.K == 0:
        return peng, []
    eng = peng.clone()
    eng.emit_log = False
    t0 = prov.t0
    assert eng.tick == t0
    prov.active = True
    heap: list[tuple[int, int, str, str]] = []
    seq = 0

    def push(e: int | None, typ: str, ref: str) -> None:
        nonlocal seq
        if e is not None and e < t0:
            heapq.heappush(heap, (e, seq, typ, ref))
            seq += 1

    for st in sorted(eng.stays.values(), key=lambda s: s.sid):
        if st.departed is not None:
            continue
        if not st.authorised:
            push(prov.pend_auth(eng, st), "auth", st.sid)
        elif not st.ready and st.auth_tick is not None:
            push(prov.pend_ready(eng, st), "ready", st.sid)
        if st.tr_req is not None and not st.tr_accepted:
            push(prov.pend_conf(eng, "transport", st.sid, st.tr_req), "conf_transport", st.sid)
        if st.tr_start is not None and st.sid in eng.tr_service:
            push(prov.pend_transport(eng, st), "transport", st.sid)
    for bed in sorted(eng.beds.values(), key=lambda b: b.bed_id):
        if bed.state == "cleaning" and bed.clean_start is not None:
            push(prov.pend_cleaning(eng, bed), "cleaning", bed.bed_id)
    for oid in sorted(eng.offers):
        off = eng.offers[oid]
        if not off.confirmed and off.source == "pool":
            push(prov.pend_conf(eng, "offer", oid, off.req), "conf_offer", oid)
    applied: list[tuple[str, str, int]] = []
    while heap:
        e, _s, typ, ref = heapq.heappop(heap)
        eng.tick = e
        if typ == "auth":
            st = eng.stays[ref]
            st.authorised, st.auth_tick = True, e
            push(prov.pend_ready(eng, st), "ready", ref)
        elif typ == "ready":
            st = eng.stays[ref]
            st.ready, st.ready_tick = True, e
            if not st.transport:
                eng.depart(st)
        elif typ == "conf_transport":
            st = eng.stays[ref]
            st.tr_accepted, st.tr_conf = True, e
        elif typ == "transport":
            st = eng.stays[ref]
            eng.tr_service.remove(ref)
            st.tr_end = e
            eng.depart(st)
        elif typ == "cleaning":
            bed = eng.beds[ref]
            bed.state, bed.clean_start, bed.clean_end, bed.dirty_tick = "free", None, None, None
        elif typ == "conf_offer":
            off = eng.offers[ref]
            off.confirmed, off.conf_tick = True, e
        applied.append((typ, ref, e))
    eng.tick = t0
    prov.active = False
    for unit, hour, c in pending_arrivals(prov, eng, revealed):
        for j in range(c):
            a = ku(prov.spec.ekey, prov.r, "nowcast-acu", unit, hour, j)
            acuity = 1 if a < G.ACUITY_P[0] else (2 if a < G.ACUITY_P[0] + G.ACUITY_P[1] else 3)
            req = Request(
                f"N{unit}{hour:04d}_{j}",
                unit,
                ku(prov.spec.ekey, prov.r, "nowcast-iso", unit, hour, j) < G.P_ISO,
                acuity,
                ku(prov.spec.ekey, prov.r, "nowcast-tr", unit, hour, j) < G.P_TRANSPORT,
                hour * TPH,
            )
            eng.queue.setdefault(unit, []).append(req)
            applied.append(("arrival", f"{unit}:{hour}", hour * TPH))
    for unit in eng.queue:
        eng.queue[unit].sort(key=lambda r: (r.arrival, r.rid))
    return eng, applied
