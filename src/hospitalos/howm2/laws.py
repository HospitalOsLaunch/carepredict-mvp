"""Exact generator laws of the scored quantities (NORM A1), vectorised over parameter grids.

Scored hazard quantity = public duration D = 15*K + L minutes (K service ticks, L publication lag of
the end event, floor of an exponential with mean theta_lag); its 15-minute bin is K + floor(L/15).
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from scipy.special import gammaln, ndtr

from hospitalos.howm import generator as G

KM = 192  # bins 0..191; index KM = tail (T >= 48 h)
SIGMA = {"transport": 0.4, "cleaning": 0.35, "ready": 0.6, "conf_tr": 0.6, "conf_off": 0.5}
P01, P10 = 1.0 / 24.0, 1.0 / 6.0


def k_pmf(med: np.ndarray, sigma: float) -> tuple[np.ndarray, np.ndarray]:
    """P(K = k), k = 0..KM-1 (K = max(1, ceil(X/15)), X ~ LN(med, sigma)), and P(K >= KM)."""
    med = np.asarray(med, float)
    edges = 15.0 * np.arange(0, KM + 1)
    with np.errstate(divide="ignore"):
        z = (np.log(np.maximum(edges, 1e-300))[None, :] - np.log(med.reshape(-1, 1))) / sigma
    F = ndtr(z)
    F[:, 0] = 0.0
    p = np.zeros((med.size, KM))
    p[:, 1:] = np.diff(F[:, :KM], axis=1)
    p[:, 1] = F[:, 1]
    tail = 1.0 - F[:, KM - 1]
    return p.reshape(med.shape + (KM,)), tail.reshape(med.shape)


def lag_q(theta: np.ndarray) -> np.ndarray:
    theta = np.asarray(theta, float)
    with np.errstate(divide="ignore"):
        return np.where(theta > 0, np.exp(-15.0 / np.maximum(theta, 1e-300)), 0.0)


def add_lag(p: np.ndarray, tail: float, qs: np.ndarray, ws: np.ndarray) -> tuple[np.ndarray, float]:
    """pmf of K + J, J ~ mixture over the lag grid of geometric(q) bin offsets, truncated at KM."""
    from scipy.signal import lfilter

    keep = ws >= 1e-9
    out = np.zeros(KM)
    for q, w in zip(qs[keep], ws[keep], strict=True):
        out += w * (p if q == 0 else lfilter([1 - q], [1, -q], p))
    out /= float(ws[keep].sum())
    return out, max(0.0, 1.0 - float(out.sum()))


@lru_cache(maxsize=96)
def snap_matrix(a_mod: int, kind: str) -> np.ndarray:
    """Night snapping as a (KM+1)x(KM+1) map on Delta ticks (last row/col = tail)."""
    lo, hi, base, width = (7, 21, 28, 8) if kind == "ready" else (8, 18, 32, 12)
    M = np.zeros((KM + 1, KM + 1))
    M[KM, KM] = 1.0
    for k in range(KM):
        t = a_mod + k
        h = (t % 96) // 4
        if lo <= h < hi:
            M[k, k] = 1.0
            continue
        day = t // 96 + (1 if h >= hi else 0)
        for j in range(width):
            d = day * 96 + base + j - a_mod
            M[k, min(max(d, 0), KM)] += 1.0 / width
    return M


def snap(p: np.ndarray, tail: np.ndarray, a: int, kind: str = "ready") -> tuple[np.ndarray, np.ndarray]:
    full = np.concatenate([p, np.asarray(tail)[..., None]], axis=-1)
    out = full @ snap_matrix(a % 96, kind)
    return out[..., :KM], out[..., KM]


def chain_prior(hours: int) -> np.ndarray:
    p = np.zeros(hours)
    for h in range(1, hours):
        p[h] = p[h - 1] * (1 - P10) + (1 - p[h - 1]) * P01
    return p


def care_bin_probs(med: np.ndarray, sigma: float = 0.5) -> np.ndarray:
    """P(bin j) of round(X), X ~ LN(med, sigma), bins of 5 minutes, last bin [600, inf)."""
    j = np.arange(121)
    lo = np.where(j > 0, 5.0 * j - 0.5, 0.0)
    hi = np.where(j < 120, 5.0 * j + 4.5, np.inf)
    lm = np.log(np.asarray(med, float))[..., None]
    with np.errstate(divide="ignore"):
        Fhi = np.where(np.isinf(hi), 1.0, ndtr((np.log(np.where(np.isinf(hi), 1.0, hi)) - lm) / sigma))
        Flo = np.where(lo > 0, ndtr((np.log(np.maximum(lo, 1e-300)) - lm) / sigma), 0.0)
    return np.maximum(Fhi - Flo, 0.0)


def care_median(skill: str, acuity: int, hour: int, care_mult: np.ndarray) -> np.ndarray:
    day = 7 <= hour % 24 < 21
    return G.CARE_MEAN[skill][acuity] * (1.25 if day else 0.6) * np.asarray(care_mult) / math.exp(0.125)


def nb_logpmf(n: np.ndarray, mu: np.ndarray, r: float = 3.0) -> np.ndarray:
    n = np.asarray(n, float)
    return gammaln(n + r) - gammaln(r) - gammaln(n + 1) + r * np.log(r / (r + mu)) + n * np.log(mu / (r + mu))


def arrivals_mean(n_beds: int, hour: int, los: np.ndarray, arr: np.ndarray) -> np.ndarray:
    return n_beds * 0.93 / (np.asarray(los) * 24) * G.HOUR_PROFILE[hour % 24] * np.asarray(arr)


def hazard_score(p: np.ndarray, tail: float, e: int, b: int, event: bool) -> float:
    S = np.concatenate([np.cumsum(p[::-1])[::-1], [0.0]]) + tail  # S[k] = P(B >= k)
    se = S[min(e, KM)]
    if event and b < KM:
        return math.log(max(p[b], 1e-300)) - math.log(se)
    return math.log(max(S[min(b, KM)], 1e-300)) - math.log(se)


def randomized_pit(p: np.ndarray, tail: float, e: int, b: int, event: bool, u: float) -> float:
    """Randomised PIT on the outcome partition {T=b, e<=b<c} U {T>=c} conditional on T >= e."""
    S = np.concatenate([np.cumsum(p[::-1])[::-1], [0.0]]) + tail
    se = S[min(e, KM)]
    if event and b < KM:
        lo = (se - S[b]) / se
        hi = (se - S[b + 1]) / se if b + 1 <= KM else 1.0
        return lo + u * (hi - lo)
    lo = (se - S[min(b, KM)]) / se
    return lo + u * (1.0 - lo)
