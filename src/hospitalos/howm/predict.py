"""Common prediction format, B0 predictions, and the paired log-score (A1.1 / NORM N3).

Every system (B0-pool, B0-local, B2, H1) produces, per origin and per ensemble member, a
``Prediction`` holding the parameters of the SAME discrete heads. Scores are computed by one
numpy function for all systems; an ensemble is the equal-weight mixture of its members.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.special import logsumexp

from .b0 import B0Params, day_period, local_deltas, to_bins
from .dataset import DATA_END_MIN, HAZARD_FAMILIES, EstablishmentData, OriginData
from .heads import (
    BIN_MIN,
    NB,
    bernoulli_logprob,
    care_logprob,
    hazard_logits,
    hazard_logprob,
    nb_logpmf,
)

HORIZONS = (1, 6, 24)
SCORED_FAMILIES = ("ready", "transport", "cleaning", "confirmation", "presence", "arrivals", "care")
N_PROFILES = 24  # unit(2) x acuity(3) x iso(2) x transport(2)


def profile_index(unit: str, acuity: int, iso: bool, transport: bool) -> int:
    return (("AB".index(unit) * 3 + (acuity - 1)) * 2 + int(iso)) * 2 + int(transport)


@dataclass
class Prediction:
    base: dict[str, np.ndarray]
    tod: dict[str, np.ndarray]
    delta_items: dict[str, np.ndarray]  # cohort items (order of od.items[fam]) for hazard families
    delta_entity: dict[
        str, dict[str, float]
    ]  # fam -> entity ref -> delta (future items of existing entities)
    delta_new: dict[str, np.ndarray]  # fam -> [N_PROFILES] (new stays during a rollout)
    arr_mu: np.ndarray  # [2, 24]
    arr_r: float
    care_mu: np.ndarray  # [n_stays, 24, 2]
    care_sigma: np.ndarray  # [2]
    care_mu_new: np.ndarray  # [2 units, 3 acuity, 24, 2 skills]
    presence_p: np.ndarray  # [n presence items]
    presence_p_new: float
    conf_offer_delta_new: float
    meta: dict[str, Any] = field(default_factory=dict)


def b0_predict(p: B0Params, od: OriginData, est: EstablishmentData, local: bool) -> Prediction:
    d = (
        local_deltas(p, od.window, est.n_beds)
        if local
        else dict.fromkeys((*HAZARD_FAMILIES, "arrivals", "care", "presence"), 0.0)
    )
    t = od.H * 60
    delta_items = {fam: np.full(len(od.items.get(fam, [])), d[fam]) for fam in HAZARD_FAMILIES}
    delta_entity: dict[str, dict[str, float]] = {fam: {} for fam in HAZARD_FAMILIES}
    delta_new = {fam: np.full(N_PROFILES, d[fam]) for fam in HAZARD_FAMILIES}
    arr_mu = np.array(
        [
            [
                math.exp(
                    p.arr_a + math.log(est.n_beds[un]) + p.arr_tod[(od.H + k) % 24] + d["arrivals"]
                )
                for k in range(24)
            ]
            for un in "AB"
        ]
    )
    acu = [int(np.argmax(x[7:10])) for x in od.care_x] if len(od.care_x) else []
    care_mu = np.zeros((len(od.care_ref), 24, 2))
    for i, a in enumerate(acu):
        for k in range(24):
            for s in range(2):
                care_mu[i, k, s] = p.care_mu[s, a, day_period(od.H + k)] + d["care"]
    care_mu_new = np.zeros((2, 3, 24, 2))
    for a in range(3):
        for k in range(24):
            for s in range(2):
                care_mu_new[:, a, k, s] = p.care_mu[s, a, day_period(od.H + k)] + d["care"]
    lp = math.log(p.presence_p / (1 - p.presence_p)) + d["presence"]
    pp = 1 / (1 + math.exp(-lp))
    return Prediction(
        dict(p.base),
        dict(p.tod),
        delta_items,
        delta_entity,
        delta_new,
        arr_mu,
        p.arr_r,
        care_mu,
        p.care_sigma.copy(),
        care_mu_new,
        np.full(len(od.items.get("presence", [])), pp),
        pp,
        d["confirmation"],
        {"system": "B0-local" if local else "B0-pool", "deltas": d, "t": t},
    )


# ------------------------------------------------------------------------------ log-scores
def _member_hazard_lp(
    pr: Prediction, fam: str, items: list[dict[str, Any]], t: int, h: int
) -> np.ndarray:
    if not items:
        return np.zeros(0)
    width = BIN_MIN[fam]
    cutoff = min(t + 60 * h, DATA_END_MIN)
    bins = [to_bins(it["start"], t, it.get("end_avail"), cutoff, width) for it in items]
    q = np.array([b[0] for b in bins], np.int64)
    e = np.array([b[1] for b in bins], np.int64)
    ev = np.array([b[2] for b in bins], bool)
    bb = np.array([b[3] for b in bins], np.int64)
    logits = hazard_logits(pr.base[fam], pr.tod[fam], pr.delta_items[fam], q, width // 15)
    return hazard_logprob(logits, e, bb, ev)


def member_logscores(pr: Prediction, od: OriginData, h: int) -> dict[str, np.ndarray]:
    t = od.H * 60
    out = {fam: _member_hazard_lp(pr, fam, od.items.get(fam, []), t, h) for fam in HAZARD_FAMILIES}
    pres = od.items.get("presence", [])
    sel = [
        i for i, it in enumerate(pres) if it["label"] is not None and it["slot_start"] <= t + 60 * h
    ]
    out["presence"] = (
        bernoulli_logprob(np.array([pres[i]["label"] for i in sel], bool), pr.presence_p[sel])
        if sel
        else np.zeros(0)
    )
    k = np.arange(h)
    arr = od.arrivals[:, :h]
    ok = arr >= 0
    out["arrivals"] = nb_logpmf(arr[ok].astype(float), pr.arr_mu[:, :h][ok], pr.arr_r)
    if len(od.care_ref):
        m = od.care_mask[:, :h]
        vals = od.care[:, :h, :]
        mu = pr.care_mu[:, :h, :]
        lp = care_logprob(
            vals.reshape(-1), mu.reshape(-1), np.tile(pr.care_sigma, vals.shape[0] * h)
        )
        lp = lp.reshape(vals.shape)
        out["care"] = lp[m].reshape(-1)
    else:
        out["care"] = np.zeros(0)
    del k
    return out


def ensemble_logscores(members: list[Prediction], od: OriginData, h: int) -> dict[str, np.ndarray]:
    """Equal-weight mixture of members' predictive distributions, element-wise."""
    per = [member_logscores(m, od, h) for m in members]
    out = {}
    for fam in per[0]:
        stack = np.stack([p[fam] for p in per])
        out[fam] = logsumexp(stack, axis=0) - math.log(len(per))
    return out


def item_set_fingerprint(od: OriginData) -> str:
    """T-PLAN-07: identical scored item set for every system (refs only)."""
    import hashlib

    parts = [f"{fam}:{it['ref']}" for fam in sorted(od.items) for it in od.items[fam]] + [
        f"care:{r}" for r in od.care_ref
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


NB_ = NB  # re-export guard for linters
