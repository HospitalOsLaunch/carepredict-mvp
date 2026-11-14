"""Discrete predictive distributions shared by every model (numpy for scoring/rollouts, torch for
training; the two must agree, T-DIST-02). All supports are discrete (NORM N1): every NLL >= 0.

Hazard: 192 bins of 15 min from the item start + tail bin 192 ("T >= 48 h").
  logit h_b = base[b] + tod[(q_start + b) mod 96] + delta
  log P(T=b | T>=e) = logsig(l_b) + sum_{e<=j<b} logsig(-l_j)
  log P(T>=c | T>=e) = sum_{e<=j<c} logsig(-l_j)          (c may be 192 = tail)
Arrivals: negative binomial (mean mu, dispersion r). Presence: Bernoulli.
Care minutes: log-normal (mu, sigma) evaluated on 5-minute bins [0,5),...,[595,600),[600,inf).
"""

from __future__ import annotations

import math

import numpy as np
import torch
from scipy.special import gammaln, log_ndtr

NB = 192


# ------------------------------------------------------------------------------- numpy
def logsig(x: np.ndarray) -> np.ndarray:
    return -np.logaddexp(0.0, -x)


BIN_MIN = {
    "auth": 60,
    "ready": 15,
    "transport": 15,
    "cleaning": 15,
    "confirmation": 15,
}  # auth: unscored family, 8-day support


def hazard_logits(
    base: np.ndarray, tod: np.ndarray, delta: np.ndarray, q_start: np.ndarray, step: int = 1
) -> np.ndarray:
    """step = bin width in quarters (1 for 15-min bins, 4 for hourly auth bins)."""
    b = np.arange(NB)
    return base[None, :] + tod[(q_start[:, None] + step * b[None, :]) % 96] + delta[:, None]


def hazard_logprob(
    logits: np.ndarray, e: np.ndarray, b: np.ndarray, event: np.ndarray
) -> np.ndarray:
    """Per item: event -> log P(T=b|T>=e); not event -> log P(T>=b|T>=e) (b may be NB = tail)."""
    ls_neg = logsig(-logits)  # log(1-h)
    cum = np.concatenate(
        [np.zeros((logits.shape[0], 1)), np.cumsum(ls_neg, axis=1)], axis=1
    )  # cum[:,k] = log S(k)
    rows = np.arange(logits.shape[0])
    log_s_b = cum[rows, b]
    log_s_e = cum[rows, e]
    lp_event = logsig(logits[rows, np.minimum(b, NB - 1)]) + log_s_b - log_s_e
    lp_surv = log_s_b - log_s_e
    return np.where(event & (b < NB), lp_event, lp_surv)


def hazard_sample(logits: np.ndarray, e: np.ndarray, uu: np.ndarray) -> np.ndarray:
    """Inverse-CDF sample of T >= e (bins); returns NB for the tail."""
    ls_neg = logsig(-logits)
    cum = np.concatenate([np.zeros((logits.shape[0], 1)), np.cumsum(ls_neg, axis=1)], axis=1)
    rows = np.arange(logits.shape[0])
    rel = cum - cum[rows, e][:, None]  # log S(k)/S(e)
    surv = np.exp(rel)  # P(T >= k | T >= e)
    k = np.arange(NB + 1)[None, :]
    surv = np.where(k <= e[:, None], 1.0, surv)
    # T = first k with P(T >= k+1 | T>=e) < 1-u  -> count of k in [e, NB) with S(k+1) >= 1-u
    thr = (1.0 - uu)[:, None]
    ge = (surv[:, 1:] > thr) & (np.arange(NB)[None, :] >= e[:, None])  # S(b+1) > 1-u  <=>  T > b
    return e + np.sum(ge, axis=1)


def nb_logpmf(n: np.ndarray, mu: np.ndarray, r: float | np.ndarray) -> np.ndarray:
    r = np.asarray(r, float)
    return (
        gammaln(n + r)
        - gammaln(r)
        - gammaln(n + 1)
        + r * np.log(r / (r + mu))
        + n * np.log(mu / (r + mu))
    )


def _logdiffexp(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """log(exp(a) - exp(b)) for a > b."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return a + np.log1p(-np.exp(np.minimum(b - a, 0.0)))


def care_bin(minutes: np.ndarray) -> np.ndarray:
    return np.minimum((np.asarray(minutes) // 5).astype(np.int64), 120)


def care_logprob(minutes: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    k = care_bin(minutes)
    lo = 5.0 * k
    hi = 5.0 * (k + 1)
    z_hi = (np.log(np.where(k < 120, hi, 1.0)) - mu) / sigma
    z_lo = (np.log(np.maximum(lo, 1e-300)) - mu) / sigma
    log_f_hi = log_ndtr(z_hi)
    log_f_lo = np.where(k > 0, log_ndtr(z_lo), -np.inf)
    log_s_lo = log_ndtr(-z_lo)
    first = log_f_hi  # bin 0: F(5)
    last = log_s_lo  # bin 120: 1 - F(600)
    # middle bins: choose the numerically stable side
    mid_left = _logdiffexp(log_f_hi, np.where(np.isfinite(log_f_lo), log_f_lo, -1e300))
    mid_right = _logdiffexp(log_s_lo, log_ndtr(-z_hi))
    mid = np.where(z_lo > 0, mid_right, mid_left)
    return np.where(k == 0, first, np.where(k == 120, last, mid))


def bernoulli_logprob(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    return np.where(y, np.log(p), np.log1p(-p))


# ------------------------------------------------------------------------------- torch
def t_hazard_logprob(
    logits: torch.Tensor, e: torch.Tensor, b: torch.Tensor, event: torch.Tensor
) -> torch.Tensor:
    ls_neg = torch.nn.functional.logsigmoid(-logits)
    cum = torch.cat([torch.zeros_like(logits[:, :1]), torch.cumsum(ls_neg, dim=1)], dim=1)
    rows = torch.arange(logits.shape[0])
    log_s_b = cum[rows, b]
    log_s_e = cum[rows, e]
    lp_event = (
        torch.nn.functional.logsigmoid(logits[rows, torch.clamp(b, max=NB - 1)]) + log_s_b - log_s_e
    )
    lp_surv = log_s_b - log_s_e
    return torch.where(event & (b < NB), lp_event, lp_surv)


def t_nb_logpmf(n: torch.Tensor, mu: torch.Tensor, r: torch.Tensor) -> torch.Tensor:
    return (
        torch.lgamma(n + r)
        - torch.lgamma(r)
        - torch.lgamma(n + 1)
        + r * (torch.log(r) - torch.log(r + mu))
        + n * (torch.log(mu) - torch.log(r + mu))
    )


def t_care_logprob(minutes: torch.Tensor, mu: torch.Tensor, sigma: torch.Tensor) -> torch.Tensor:
    k = torch.clamp(torch.div(minutes, 5, rounding_mode="floor"), max=120).long()
    lo = 5.0 * k
    hi = 5.0 * (k + 1)
    z_hi = (
        torch.log(
            torch.where(k < 120, hi.double(), torch.ones_like(hi, dtype=torch.float64)).to(mu.dtype)
        )
        - mu
    ) / sigma
    z_lo = (torch.log(torch.clamp(lo, min=1e-30).to(mu.dtype)) - mu) / sigma
    log_f_hi = torch.special.log_ndtr(z_hi)
    log_f_lo = torch.special.log_ndtr(z_lo)
    log_s_lo = torch.special.log_ndtr(-z_lo)
    log_s_hi = torch.special.log_ndtr(-z_hi)

    def ldiff(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
        return a + torch.log1p(-torch.exp(torch.clamp(b - a, max=-1e-12)))

    mid = torch.where(z_lo > 0, ldiff(log_s_lo, log_s_hi), ldiff(log_f_hi, log_f_lo))
    return torch.where(k == 0, log_f_hi, torch.where(k == 120, log_s_lo, mid))


def t_bernoulli_logprob(y: torch.Tensor, logit: torch.Tensor) -> torch.Tensor:
    return torch.where(
        y, torch.nn.functional.logsigmoid(logit), torch.nn.functional.logsigmoid(-logit)
    )


# ------------------------------------------------------------------------------- loss scales
class ScaleError(ValueError):
    pass


def check_scales(scales: dict[str, float]) -> dict[str, float]:
    """NORM N1.3: s_f must be finite and >= 1e-6 (strictly positive); never patched."""
    for f, s in scales.items():
        if not isinstance(s, (int, float)) or not math.isfinite(s) or s <= 0 or s < 1e-6:
            raise ScaleError(f"invalid loss scale for {f}: {s!r}")
    return dict(scales)


def normalised_loss(nll_means: dict[str, float], scales: dict[str, float]) -> float:
    check_scales(scales)
    return float(sum(v / scales[f] for f, v in nll_means.items()))
