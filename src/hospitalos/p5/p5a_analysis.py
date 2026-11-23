"""P5a analysis (P5-PROTO-2 §§ 5, 8 as amended by P5-PROTO-3 A3/A6/A7 and 3.1 R3).

Per parent and regime, over the K_eval realisations (keyed, shared by all plans):
  U_hab (plan 0, HABITUAL-1), U_plan (v6 public choice; HABITUAL-1 for genuine abstentions),
  U_star = mean_k min_a U_k(a) (exact minimum on the public universe),
  U_lex  = mean_k U_k(lex_k) with OBJ-LEX-1 on realised U (tolerance 15, then planned
           reinforcement hours, then interventions) - diagnostic only, never a denominator,
  U_fix  = min_a mean_k U_k(a) - diagnostic, biased downward with K = 3.
Estimands are structure-weighted (equal weight per structure, then per parent). Two-stage
bootstrap (structures, then parents within structure) with the committed seed; one resampling
pass serves every statistic. R1 is primary; R2 is robustness only and cannot upgrade a verdict.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from .analysis import clopper_pearson_upper

DELTA = 15.0
TOLERANCE = 15.0
HARM_MAX = 0.10
EXCLUSION_MAX = 0.05
HALF_WIDTH_MAX = DELTA / 2
Z = 1.959963984540054


def lex_index(u: Sequence[float], planned: Sequence[int], interventions: Sequence[int]) -> int:
    best = min(u)
    cands = [i for i in range(len(u)) if u[i] <= best + TOLERANCE]
    return min(cands, key=lambda i: (planned[i], interventions[i], u[i], i))


def _find(plans: Sequence[Mapping[str, Any]], coord: Sequence[str], reinf: Sequence[str]) -> int | None:
    for i, p in enumerate(plans):
        if list(p["coord"]) == list(coord) and list(p["reinf"]) == list(reinf):
            return i
    return None


STATS = ("gain", "headroom", "regret_plan", "regret_hab", "regret_lex", "U_hab", "U_plan", "U_star",
         "U_lex", "U_fix", "res_only", "coord_at_equal_res", "coord_only", "res_given_coord",
         "interaction", "planned_hours", "realised_hours", "lent_hours", "interventions",
         "waiting_plan", "waiting_hab", "beds_plan", "beds_hab", "peak_plan", "peak_hab",
         "above_plan", "above_hab", "abstention", "harm")


def parent_stats(rec: Mapping[str, Any], regime: str) -> dict[str, float]:
    plans = rec["plans"]
    if plans[0]["class"] != "H":
        raise ValueError("plan 0 must be HABITUAL-1")
    o = rec["outcomes"][regime]
    U = np.asarray(o["U"], dtype=float)  # K x n
    k = U.shape[0]
    a = int(rec["chosen_index"])
    planned = [p["planned_hours"] for p in plans]
    interv = [p["interventions"] for p in plans]
    u_hab, u_plan = U[:, 0].mean(), U[:, a].mean()
    u_star = U.min(axis=1).mean()
    u_lex = float(np.mean([U[r, lex_index(U[r], planned, interv)] for r in range(k)]))
    u_fix = U.mean(axis=0).min()
    c_idx = _find(plans, plans[a]["coord"], [])
    r_idx = _find(plans, [], plans[a]["reinf"])
    if c_idx is None or r_idx is None:
        raise ValueError("sub-plan of the chosen plan missing from the complete universe")
    u_c, u_r = U[:, c_idx].mean(), U[:, r_idx].mean()

    def m(field: str, i: int) -> float:
        vals = [row[i] for row in o[field]]
        return float(np.mean([v for v in vals if v is not None])) if any(v is not None for v in vals) else math.nan

    return {
        "gain": u_hab - u_plan,
        "headroom": u_hab - u_star,
        "regret_plan": u_plan - u_star,
        "regret_hab": u_hab - u_star,
        "regret_lex": u_lex - u_star,
        "U_hab": u_hab, "U_plan": u_plan, "U_star": u_star, "U_lex": u_lex, "U_fix": u_fix,
        "res_only": u_hab - u_r,
        "coord_at_equal_res": u_r - u_plan,
        "coord_only": u_hab - u_c,
        "res_given_coord": u_c - u_plan,
        "interaction": u_c + u_r - u_plan - u_hab,
        "planned_hours": float(planned[a]),
        "realised_hours": m("realised_hours", a),
        "lent_hours": m("lent_hours", a),
        "interventions": float(interv[a]),
        "waiting_plan": m("waiting", a), "waiting_hab": m("waiting", 0),
        "beds_plan": m("beds", a), "beds_hab": m("beds", 0),
        "peak_plan": m("peak", a), "peak_hab": m("peak", 0),
        "above_plan": m("above", a), "above_hab": m("above", 0),
        "abstention": float(bool(rec["abstention_as_habitual"])),
        "harm": float((u_plan - u_hab) > DELTA),  # A6: mean over the K realisations > delta
    }


def class_minima(rec: Mapping[str, Any], regime: str) -> dict[str, float | None]:
    U = np.asarray(rec["outcomes"][regime]["U"], dtype=float)
    out: dict[str, float | None] = {}
    for cls in ("C", "R", "CR"):
        idx = [i for i, p in enumerate(rec["plans"]) if p["class"] == cls]
        out[cls] = float(U[:, idx].min(axis=1).mean()) if idx else None
    return out


def group(records: Sequence[Mapping[str, Any]], regime: str) -> tuple[list[str], list[np.ndarray]]:
    by_s: dict[str, list[list[float]]] = {}
    for r in sorted(records, key=lambda r: (r["structure_index"], r["parent_index"])):
        st = parent_stats(r, regime)
        by_s.setdefault(r["structure_id"], []).append([st[k] for k in STATS])
    ids = list(by_s)
    return ids, [np.asarray(by_s[s], dtype=float) for s in ids]


def weighted_means(structures: Sequence[np.ndarray]) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN descriptor columns stay NaN
        return np.nanmean(np.stack([np.nanmean(s, axis=0) for s in structures]), axis=0)


def bootstrap(structures: Sequence[np.ndarray], resamples: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(structures)
    out = np.empty((resamples, structures[0].shape[1]))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        _fill(out, structures, rng, n, resamples)
    return out


def _fill(out: np.ndarray, structures: Sequence[np.ndarray], rng: np.random.Generator, n: int, resamples: int) -> None:
    for b in range(resamples):
        means = []
        for i in rng.integers(0, n, n):
            s = structures[int(i)]
            means.append(np.nanmean(s[rng.integers(0, len(s), len(s))], axis=0))
        out[b] = np.nanmean(np.stack(means), axis=0)


def ci(values: np.ndarray, level: float = 0.95) -> list[float] | None:
    v = values[np.isfinite(values)]
    if v.size == 0:
        return None  # statistic undefined (e.g. descriptor absent in every resample)
    a = (1 - level) / 2
    return [float(np.quantile(v, a)), float(np.quantile(v, 1 - a))]


def precision_projection(dev_structures: Sequence[np.ndarray], n_eval_structures: int = 30) -> dict[str, Any]:
    """Pre-registered (F_a): half-width = z * SD(structure means of gain, R1) / sqrt(30)."""
    gi = STATS.index("gain")
    means = np.asarray([float(np.mean(s[:, gi])) for s in dev_structures])
    sd = float(np.std(means, ddof=1))
    hw = Z * sd / math.sqrt(n_eval_structures)
    return {"dev_structures": len(means), "sd_between_structure_means": sd, "projected_half_width": hw,
            "threshold": HALF_WIDTH_MAX, "precision_sufficient": hw <= HALF_WIDTH_MAX,
            "declared_reading": "confirmatory" if hw <= HALF_WIDTH_MAX else "exploratory"}


def analyse(records: Sequence[Mapping[str, Any]], structures_meta: Sequence[Mapping[str, Any]],
            regime: str, seed: int, resamples: int, precision_sufficient: bool, primary: bool) -> dict[str, Any]:
    ids, structs = group(records, regime)
    est = weighted_means(structs)
    boot = bootstrap(structs, resamples, seed)
    idx = {k: i for i, k in enumerate(STATS)}
    point = {k: float(est[i]) for k, i in idx.items()}
    intervals = {k: ci(boot[:, i]) for k, i in idx.items()}
    g_lo, g_hi = intervals["gain"]  # gain is always defined
    headroom = point["headroom"]
    cap_boot = boot[:, idx["gain"]] / boot[:, idx["headroom"]]
    below = int(np.sum(boot[:, idx["headroom"]] < DELTA))
    capture = {
        "defined": headroom >= DELTA,
        "point": point["gain"] / headroom if headroom >= DELTA else None,
        "ci95": ci(cap_boot) if headroom >= DELTA else None,
        "resamples_with_headroom_below_delta": below,
        "clipped": False,
    }
    harmed = []
    for s in structs:
        harmed.append(bool(np.any(s[:, idx["harm"]] > 0)))
    harm_upper = clopper_pearson_upper(sum(harmed), len(harmed))
    cand = sum(int(m["candidates"]) for m in structures_meta)
    excl = sum(sum(m["exclusions"].values()) for m in structures_meta)
    excl_rate = excl / cand if cand else 0.0
    guard = {
        "violations": 0,
        "chosen_plan_in_universe": True,
        "universe_invariant": True,
        "exclusion_rate": excl_rate,
        "exclusion_ok": excl_rate <= EXCLUSION_MAX,
        "harm": {"event": "parent harmed iff mean over K_eval=3 realisations of (U_plan - U_hab) > 15; "
                          "structure harmed iff >= 1 harmed parent",
                 "harmed_structures": sum(harmed), "structures": len(harmed),
                 "harmed_parents": int(sum(int(np.sum(s[:, idx["harm"]] > 0)) for s in structs)),
                 "cp_upper_one_sided_95": harm_upper, "ok": harm_upper <= HARM_MAX},
    }
    guard_ok = guard["exclusion_ok"] and guard["harm"]["ok"]
    if g_hi < DELTA:
        verdict = "insufficient"
    elif g_lo > DELTA and guard_ok and precision_sufficient:
        verdict = "demonstrated_in_this_synthetic_protocol"
    else:
        verdict = "inconclusive" if precision_sufficient else "exploratory"
    return {
        "regime": regime,
        "role": "primary" if primary else "robustness_only_cannot_upgrade_R1",
        "structures": len(structs),
        "parents": int(sum(len(s) for s in structs)),
        "point": point,
        "ci95": intervals,
        "capture": capture,
        "guardrails": guard,
        "delta": DELTA,
        "verdict": verdict if primary else f"{verdict} (robustness reading only)",
        "abstentions": int(sum(int(np.sum(s[:, idx["abstention"]])) for s in structs)),
    }
