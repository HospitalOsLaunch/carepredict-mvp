"""B0 — explicit mechanisms recalibrated on TRAIN (numpy/scipy only; no network).

B0-pool: hazards (base[b] + tod[quarter] per family), arrivals NB (log mu = a + log n_beds +
tod_h[hour]), care log-normal (mu per skill x acuity x day/night, sigma per skill), pool presence.
B0-local: same mechanisms + one intercept per family estimated by penalised MLE (prior N(0, tau_f^2))
from the SAME public window W = 24 h as the networks; tau_f chosen on TRAIN only by the
predictive log-likelihood of the following 24 h (grid).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import minimize

from .dataset import DATA_END_MIN, HAZARD_FAMILIES, NB, _end_index
from .generator import Episode
from .heads import BIN_MIN, care_bin, care_logprob, logsig, nb_logpmf

TAU_GRID = (0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.5)
SKILL_IDX = {"IDE": 0, "AS": 1}


def day_period(hour: int) -> int:
    return 1 if 7 <= hour % 24 < 21 else 0


# ------------------------------------------------------------------------------ item records
def hazard_records(ep: Episode) -> dict[str, list[tuple[int, int, int | None]]]:
    """(start_min, entry_min, end_avail_min|None) for every item of the episode, per family."""
    obs = ep.observations
    idx = _end_index(obs)
    first = idx["first"]
    rec: dict[str, list[tuple[int, int, int | None]]] = {f: [] for f in HAZARD_FAMILIES}
    for ev, _av, kind, subj, _u, v in obs:
        if kind == "placed":
            start = v.get("placed_min", ev)
            end = first.get(("authorised", subj))
            rec["auth"].append((start, max(start, 0), end[1] if end else None))
        elif kind == "authorised":
            end = first.get(("ready", subj))
            rec["ready"].append((ev, ev, end[1] if end else None))
        elif kind == "transport_start":
            end = first.get(("transport_done", subj))
            rec["transport"].append((ev, ev, end[1] if end else None))
        elif kind == "transport_requested":
            end = first.get(("transport_accepted", subj))
            rec["confirmation"].append((ev, ev, end[1] if end else None))
        elif kind == "offer_requested" and v.get("source") == "pool":
            end = first.get(("offer_confirmed", subj))
            rec["confirmation"].append((ev, ev, end[1] if end else None))
        elif kind == "cleaning_start":
            end = next(((e2, a2) for e2, a2 in idx["clean_done"].get(subj, []) if e2 >= ev), None)
            rec["cleaning"].append((ev, ev, end[1] if end else None))
    return rec


def to_bins(
    start: int, entry: int, end: int | None, cutoff: int, width: int = 15
) -> tuple[int, int, bool, int]:
    """-> (q_start, e_bin, event, b_bin) with censoring at ``cutoff`` (minutes, absolute).
    Event iff end < cutoff (outcomes {T=b, e<=b<c} and {T>=c} partition the space)."""
    q = (start // 15) % 96
    e = min(NB, max(0, (entry - start) // width))
    if end is not None and end < cutoff:
        b = min(NB, max(e, (end - start) // width))
        return q, e, b < NB, b
    c = (cutoff - start) // width
    return q, e, False, min(NB, max(e, c))


def _rows(
    items: list[tuple[int, int, bool, int]], step: int = 1
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    ks, qs, ys, ids = [], [], [], []
    for i, (q, e, ev, b) in enumerate(items):
        last = min(b, NB - 1) if ev else min(b, NB) - 1
        if last < e:
            continue
        k = np.arange(e, last + 1)
        ks.append(k)
        qs.append((q + step * k) % 96)
        y = np.zeros(len(k))
        if ev:
            y[-1] = 1.0
        ys.append(y)
        ids.append(np.full(len(k), i))
    if not ks:
        z = np.zeros(0, np.int64)
        return z, z, np.zeros(0), z
    return np.concatenate(ks), np.concatenate(qs), np.concatenate(ys), np.concatenate(ids)


def fit_hazard(
    items: list[tuple[int, int, bool, int]], step: int = 1
) -> tuple[np.ndarray, np.ndarray]:
    k, q, y, _ = _rows(items, step)

    def f(theta: np.ndarray) -> tuple[float, np.ndarray]:
        base, tod = theta[:NB], theta[NB:]
        logit = base[k] + tod[q]
        p = 1.0 / (1.0 + np.exp(-logit))
        nll = -np.sum(y * logsig(logit) + (1 - y) * logsig(-logit))
        r = p - y
        g = np.concatenate([np.bincount(k, r, NB), np.bincount(q, r, 96)])
        reg = 1e-3 * np.sum(base**2) + 1e-2 * np.sum(tod**2)
        g += np.concatenate([2e-3 * base, 2e-2 * tod])
        return nll + reg, g

    x0 = np.concatenate([np.full(NB, -3.0), np.zeros(96)])
    res = minimize(f, x0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
    return res.x[:NB].copy(), res.x[NB:].copy()


@dataclass
class B0Params:
    base: dict[str, np.ndarray]
    tod: dict[str, np.ndarray]
    arr_a: float
    arr_tod: np.ndarray  # [24]
    arr_r: float
    care_mu: np.ndarray  # [2 skills, 3 acuity, 2 period]
    care_sigma: np.ndarray  # [2]
    presence_p: float
    tau: dict[str, float] = field(default_factory=dict)
    new_profile_freq: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            k: (
                v.tolist()
                if isinstance(v, np.ndarray)
                else (
                    {
                        kk: (vv.tolist() if isinstance(vv, np.ndarray) else vv)
                        for kk, vv in v.items()
                    }
                    if isinstance(v, dict)
                    else v
                )
            )
            for k, v in self.__dict__.items()
        }

    @staticmethod
    def from_json(d: dict[str, Any]) -> B0Params:
        return B0Params(
            {k: np.asarray(v) for k, v in d["base"].items()},
            {k: np.asarray(v) for k, v in d["tod"].items()},
            float(d["arr_a"]),
            np.asarray(d["arr_tod"]),
            float(d["arr_r"]),
            np.asarray(d["care_mu"]),
            np.asarray(d["care_sigma"]),
            float(d["presence_p"]),
            dict(d.get("tau", {})),
            dict(d.get("new_profile_freq", {})),
        )


def fit_pool(episodes: list[Episode]) -> B0Params:
    base, tod = {}, {}
    for fam in HAZARD_FAMILIES:
        items = []
        for ep in episodes:
            for s, e, end in hazard_records(ep)[fam]:
                items.append(to_bins(s, e, end, DATA_END_MIN, BIN_MIN[fam]))
        base[fam], tod[fam] = fit_hazard(items, BIN_MIN[fam] // 15)
    # arrivals: sufficient statistics (log n_beds, hour of day, count)
    rows = []
    for ep in episodes:
        cnt = np.zeros((2, DATA_END_MIN // 60), np.int64)
        for ev, _a, kind, _s, un, _v in ep.observations:
            if kind == "request_arrival":
                cnt["AB".index(un), ev // 60] += 1
        for ui, un in enumerate("AB"):
            for h in range(cnt.shape[1]):
                rows.append((math.log(ep.spec.beds[un]), h % 24, cnt[ui, h]))
    lb = np.array([r[0] for r in rows])
    hh = np.array([r[1] for r in rows], np.int64)
    nn = np.array([r[2] for r in rows], float)

    def f_arr(th: np.ndarray) -> float:
        mu = np.exp(th[0] + lb + np.concatenate([[0.0], th[1:24]])[hh])
        return -float(np.sum(nb_logpmf(nn, mu, math.exp(th[24]))))

    ra = minimize(f_arr, np.concatenate([[-4.0], np.zeros(23), [1.0]]), method="L-BFGS-B")
    arr_tod = np.concatenate([[0.0], ra.x[1:24]])
    # care: sufficient statistics per (skill, acuity, period, bin)
    counts = np.zeros((2, 3, 2, 121))
    for ep in episodes:
        acu = {}
        for ev, _a, kind, subj, _u, v in ep.observations:
            if kind == "placed":
                acu[subj] = v["acuity"]
        for ev, _a, kind, subj, _u, v in ep.observations:
            if kind == "care_due" and subj in acu:
                per = day_period(v["hour"])
                counts[0, acu[subj] - 1, per, care_bin(np.array([v["ide"]]))[0]] += 1
                counts[1, acu[subj] - 1, per, care_bin(np.array([v["as_"]]))[0]] += 1
    mids = np.array([2.5 + 5 * k for k in range(121)])
    care_mu = np.zeros((2, 3, 2))
    care_sigma = np.zeros(2)
    for s in range(2):

        def f_care(th: np.ndarray) -> float:
            mu = th[:6].reshape(3, 2)
            sig = math.exp(th[6])
            tot = 0.0
            for a in range(3):
                for p in range(2):
                    c = counts[s, a, p]
                    if c.sum() == 0:
                        continue
                    lp = care_logprob(mids, np.full(121, mu[a, p]), np.full(121, sig))
                    tot -= float(np.sum(c * lp))
            return tot

        rc = minimize(f_care, np.concatenate([np.full(6, 2.3), [math.log(0.5)]]), method="L-BFGS-B")
        care_mu[s] = rc.x[:6].reshape(3, 2)
        care_sigma[s] = math.exp(rc.x[6])
    pres = [
        kind == "offer_present"
        for ep in episodes
        for _e, _a, kind, subj, _u, _v in ep.observations
        if kind in ("offer_present", "offer_absent") and "pool" in subj
    ]
    p = (sum(pres) + 0.5) / (
        len(pres) + 1.0
    )  # Jeffreys-type estimate, declared (avoids p=1 on finite data)
    return B0Params(
        base, tod, float(ra.x[0]), arr_tod, float(math.exp(ra.x[24])), care_mu, care_sigma, float(p)
    )


# ------------------------------------------------------------------------------ B0-local
def _newton_1d(grad_hess, tau: float, x0: float = 0.0, iters: int = 25) -> float:
    x = x0
    for _ in range(iters):
        g, h = grad_hess(x)
        g -= x / tau**2
        h -= 1.0 / tau**2
        step = g / h
        x -= float(np.clip(step, -2.0, 2.0))
        if abs(step) < 1e-8:
            break
    return x


def local_hazard_delta(
    p: B0Params, fam: str, window_items: list[tuple[int, int, bool, int]], tau: float
) -> float:
    k, q, y, _ = _rows(window_items, BIN_MIN[fam] // 15)
    if len(k) == 0:
        return 0.0
    base = p.base[fam][k] + p.tod[fam][q]

    def gh(d: float) -> tuple[float, float]:
        pr = 1.0 / (1.0 + np.exp(-(base + d)))
        return float(np.sum(y - pr)), float(-np.sum(pr * (1 - pr)))

    return _newton_1d(gh, tau)


def local_arrivals_delta(
    p: B0Params, counts: np.ndarray, n_beds: dict[str, int], t_hour: int, tau: float
) -> float:
    mu0 = np.array(
        [
            [
                math.exp(p.arr_a + math.log(n_beds[un]) + p.arr_tod[(t_hour - 24 + j) % 24])
                for j in range(24)
            ]
            for un in "AB"
        ]
    )
    n = counts.astype(float)
    r = p.arr_r

    def gh(d: float) -> tuple[float, float]:
        mu = mu0 * math.exp(d)
        g = np.sum(n - (n + r) * mu / (r + mu))
        h = -np.sum((n + r) * mu * r / (r + mu) ** 2)
        return float(g), float(h)

    return _newton_1d(gh, tau)


def local_care_delta(p: B0Params, care: list[tuple[float, float]], tau: float) -> float:
    if not care:
        return 0.0
    vals = np.array(care, float)
    # pooled shift on log-minutes, approximate Gaussian likelihood around the B0 mean (declared)
    ref = np.array([p.care_mu[s].mean() for s in range(2)])
    logv = np.log(np.maximum(vals, 2.5))
    resid = (logv - ref[None, :]) / (p.care_sigma[None, :] ** 2)
    prec = len(vals) * float(np.sum(1.0 / p.care_sigma**2))
    return float(np.sum(resid) / (prec + 1.0 / tau**2))


def local_presence_delta(p: B0Params, pres: list[bool], tau: float) -> float:
    if not pres:
        return 0.0
    y = np.array(pres, float)
    l0 = math.log(p.presence_p / (1 - p.presence_p))

    def gh(d: float) -> tuple[float, float]:
        pr = 1 / (1 + math.exp(-(l0 + d)))
        return float(np.sum(y - pr)), float(-len(y) * pr * (1 - pr))

    return _newton_1d(gh, tau)


def window_hazard_items(window: dict[str, Any], fam: str) -> list[tuple[int, int, bool, int]]:
    t = window["t"]
    return [to_bins(s, s, end, t, BIN_MIN[fam]) for s, end, _ in window["hazard"][fam]]


def local_deltas(p: B0Params, window: dict[str, Any], n_beds: dict[str, int]) -> dict[str, float]:
    t_hour = window["t"] // 60
    out = {
        fam: local_hazard_delta(p, fam, window_hazard_items(window, fam), p.tau.get(fam, 0.35))
        for fam in HAZARD_FAMILIES
    }
    out["arrivals"] = local_arrivals_delta(
        p, window["arrivals"], n_beds, t_hour, p.tau.get("arrivals", 0.35)
    )
    out["care"] = local_care_delta(p, window["care"], p.tau.get("care", 0.35))
    out["presence"] = local_presence_delta(p, window["presence"], p.tau.get("presence", 0.35))
    return out
