"""Mode-1 rollouts: explicit operator + a model provider sampling from a ``Prediction``.

Common random numbers: a draw is keyed by (sample m, primitive, entity), never by candidate or
call order (T-ROLL-04). Sampled events are applied by the operator (preconditions, rejection
counting) and reinjected in the explicit state only (NORM N6.6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.special import ndtri
from scipy.stats import nbinom

from .generator import refresh_private
from .heads import BIN_MIN, NB, hazard_logits, hazard_sample
from .keys import key, u, u_vec
from .predict import Prediction, profile_index
from .world import SKILLS, TPH, Engine, Offer, Plan, Stay, objective_u

N01_INV = None


def _norm_inv(p: float) -> float:
    from statistics import NormalDist

    global N01_INV
    if N01_INV is None:
        N01_INV = NormalDist().inv_cdf
    return N01_INV(min(max(p, 1e-12), 1 - 1e-12))


@dataclass
class NewProfileFreq:
    p_iso: float
    p_acuity: tuple[float, float, float]
    p_transport: float


class ModelProvider:
    """Draws from a member's Prediction; ``origin_tick`` = 4H."""

    def __init__(
        self,
        pred: Prediction,
        od: Any,
        origin_tick: int,
        m: int,
        base_key: int,
        freq: NewProfileFreq,
    ):
        self.p = pred
        self.t0 = origin_tick
        self.H = origin_tick // TPH
        self.m = m
        self.bk = base_key
        self.freq = freq
        self.item_delta: dict[tuple[str, str], float] = {}
        for fam, arr in pred.delta_items.items():
            for it, d in zip(od.items.get(fam, []), arr, strict=True):
                self.item_delta[(fam, it["ref"])] = float(d)
        self.pres_p = {
            it["ref"]: float(pp) for it, pp in zip(od.items.get("presence", []), pred.presence_p)
        }
        self.care_row = {sid: i for i, sid in enumerate(od.care_ref)}
        cdf = pred.meta.get("_arr_cdf")
        if cdf is None:  # computed once per Prediction, shared by its providers
            cdf = [
                [
                    nbinom.cdf(
                        np.arange(60), pred.arr_r, pred.arr_r / (pred.arr_r + pred.arr_mu[ui, k])
                    )
                    for k in range(24)
                ]
                for ui in range(2)
            ]
            pred.meta["_arr_cdf"] = cdf
        self.arr_cdf = cdf
        self._care_z: dict[str, np.ndarray] = {}

    def _u(self, *parts: object) -> float:
        return u(self.bk, self.m, *parts)

    def _delta(self, fam: str, ref: str, st: Stay | None) -> float:
        d = self.item_delta.get((fam, ref))
        if d is not None:
            return d
        ent_ref = ref.split(":", 1)[1] if fam == "confirmation" else ref
        d = self.p.delta_entity.get(fam, {}).get(ent_ref)
        if d is not None:
            return d
        if st is not None:
            return float(
                self.p.delta_new[fam][profile_index(st.unit, st.acuity, st.iso, st.transport)]
            )
        return float(self.p.conf_offer_delta_new) if fam == "confirmation" else 0.0

    def _sample(self, fam: str, ref: str, st: Stay | None, start_tick: int, now: int) -> int:
        width = BIN_MIN[fam] // 15  # ticks per bin
        q = np.array([start_tick % 96])
        logits = hazard_logits(
            self.p.base[fam], self.p.tod[fam], np.array([self._delta(fam, ref, st)]), q, width
        )
        e = np.array([min(NB, max(0, (now - start_tick) // width))])
        b = int(hazard_sample(logits, e, np.array([self._u(fam, ref, start_tick)]))[0])
        if b >= NB:
            return 10**9
        t = start_tick + b * width + (int(self._u(fam, "in", ref) * width) if width > 1 else 0)
        return max(now + 1, t)

    def auth_tick(self, eng: Engine, st: Stay) -> int:
        return self._sample("auth", st.sid, st, st.placed_tick, eng.tick)

    def ready_tick(self, eng: Engine, st: Stay) -> int:
        start = st.auth_tick if st.auth_tick is not None and st.auth_tick <= eng.tick else eng.tick
        return self._sample("ready", st.sid, st, start, eng.tick)

    def confirm_tick(self, eng: Engine, kind: str, ref: str, req: int) -> int:
        r = ("T:" if kind == "transport" else "O:") + ref
        st = eng.stays.get(ref) if kind == "transport" else None
        return self._sample("confirmation", r, st, req, eng.tick)

    def transport_end(self, eng: Engine, st: Stay) -> int:
        start = st.tr_start if st.tr_start is not None else eng.tick
        return self._sample("transport", st.sid, st, start, eng.tick)

    def cleaning_end(self, eng: Engine, bed: Any) -> int:
        start = bed.clean_start if bed.clean_start is not None else eng.tick
        return self._sample("cleaning", bed.bed_id, None, start, eng.tick)

    def presence(self, eng: Engine, off: Offer) -> bool:
        if off.source != "pool":
            return True
        p = self.pres_p.get(off.oid, self.p.presence_p_new)
        return self._u("presence", off.oid) < p

    def arrivals(self, eng: Engine, unit: str, hour: int) -> list[tuple[bool, int, bool]]:
        k = hour - self.H
        if not 0 <= k < 24:
            return []
        cdf = self.arr_cdf["AB".index(unit)][k]
        n = int(np.searchsorted(cdf, self._u("arr", unit, hour)))
        out = []
        f = self.freq
        for i in range(n):
            a = self._u("acu", unit, hour, i)
            acuity = 1 if a < f.p_acuity[0] else (2 if a < f.p_acuity[0] + f.p_acuity[1] else 3)
            out.append(
                (
                    self._u("iso", unit, hour, i) < f.p_iso,
                    acuity,
                    self._u("trn", unit, hour, i) < f.p_transport,
                )
            )
        return out

    def care(self, eng: Engine, st: Stay, hour: int) -> tuple[float, float]:
        k = min(max(hour - self.H, 0), 23)
        z = self._care_z.get(st.sid)
        if (
            z is None
        ):  # one keyed hash per stay, then 48 vectorised uniforms (CRN: keyed by sample + stay)
            z = ndtri(u_vec(key(self.bk, self.m, "care", st.sid), np.arange(48))).reshape(24, 2)
            self._care_z[st.sid] = z
        row = self.care_row.get(st.sid)
        if row is not None:
            mu = self.p.care_mu[row, k]
        else:
            mu = self.p.care_mu_new["AB".index(st.unit), st.acuity - 1, k]
        v = np.round(np.exp(mu + self.p.care_sigma * z[k]))
        return float(v[0]), float(v[1])

    def cleaning_capacity_drop(self, eng: Engine, tick: int) -> int:
        return 0  # unannounced drops are private (m5); models only know the published capacity


TARGETS = ("occupancy", "free_beds", "transport_queue", "cleaning_queue")


def rollout(
    engine0: Engine, prov: Any, plan: Plan | None, hours: int = 24, prime: bool = True
) -> dict[str, Any]:
    eng = engine0.clone()
    eng.emit_log = False
    if prime:
        refresh_private(eng, prov)
    t0 = eng.tick
    wait0 = dict(eng.waiting_ticks)
    if plan is not None:
        eng.apply_plan(plan, prov)
    snaps = {}
    end = t0 + hours * TPH
    while eng.tick < end:
        if (eng.tick - t0) in (TPH, 6 * TPH):
            snaps[(eng.tick - t0) // TPH] = eng.snapshot_hour()
        eng.step(prov)
    snaps[hours] = eng.snapshot_hour()
    h0 = t0 // TPH
    care = {
        (un, sk, h): eng.demand.get((un, sk, h0 + h - 1), 0.0)
        for un in eng.units
        for sk in SKILLS
        for h in (1, 6, 24)
    }
    return {
        "U": objective_u(eng, t0, wait0),
        "snaps": snaps,
        "care": care,
        "rejected": eng.rejected,
        "reinforcement_hours": sum(4 for o in eng.offers.values() if o.req >= t0 and o.confirmed),
        "present_hours": sum(4 for o in eng.offers.values() if o.req >= t0 and o.present),
    }


def target_vector(res: dict[str, Any], h: int, units: tuple[str, ...] = ("A", "B")) -> list[float]:
    s = res["snaps"][h]
    vec = []
    for un in units:
        vec += [float(s[un][k]) for k in TARGETS]
        vec += [res["care"][(un, sk, h)] for sk in SKILLS]
    return vec


def truth_vector(
    ep: Any, H: int, h: int, units: tuple[str, ...] = ("A", "B")
) -> list[float] | None:
    j = H + h
    if j >= len(ep.hourly):
        return None
    s = ep.hourly[j]
    vec = []
    for un in units:
        vec += [float(s[un][k]) for k in TARGETS]
        vec += [ep.demand.get((un, sk, j - 1), 0.0) for sk in SKILLS]
    return vec


TARGET_NAMES = [f"{un}:{k}" for un in ("A", "B") for k in (*TARGETS, "care_IDE", "care_AS")]


def crps_samples(samples: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Fair (unbiased) sample CRPS per target. samples [M, T], y [T]."""
    m = samples.shape[0]
    t1 = np.mean(np.abs(samples - y[None, :]), axis=0)
    diff = np.abs(samples[:, None, :] - samples[None, :, :]).sum(axis=(0, 1))
    return t1 - diff / (2 * m * (m - 1))


def rollout_key(partition: str, index: int, H: int) -> int:
    return key("HOWM1-roll", partition, index, H)
