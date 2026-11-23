"""P5b analysis (primary: Delta_rep = U(choice M_agg) - U(choice M_ent), paired).

Per parent and regime: means over the K realisations, then over the two twins. Estimands are
structure-weighted; two-stage bootstrap (structures, then parents carrying both twins, all
replicates and plans) with the committed seed. Harm (M_ent vs HABITUAL-1): a twin is harmed iff
mean_k(U_ent - U_hab) > 15; a parent iff at least one twin; a structure iff at least one parent;
one-sided Clopper-Pearson bound over reserved structures. R2 is robustness only.
Precision projection (before F_b): z * SD(structure means of Delta_rep on VALIDATION, R1) / sqrt(30),
estimated on P5b's own paired difference (P5a's SD is not reused).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from .analysis import clopper_pearson_upper
from .p5a_analysis import Z, bootstrap, ci, weighted_means

DELTA = 15.0
HARM_MAX = 0.10
EXCLUSION_MAX = 0.05
HALF_WIDTH_MAX = DELTA / 2

STATS = ("delta_rep", "U_hab", "U_agg", "U_ent", "U_plan", "U_star", "gain_ent", "gain_agg", "gain_plan",
         "regret_ent", "regret_agg", "ent_res_only", "ent_coord_at_equal_res", "ent_interaction",
         "planned_hours_ent", "planned_hours_agg", "harm_ent", "harm_agg", "same_choice")


def _find(plans: Sequence[Mapping[str, Any]], coord: Sequence[str], reinf: Sequence[str]) -> int:
    for i, p in enumerate(plans):
        if list(p["coord"]) == list(coord) and list(p["reinf"]) == list(reinf):
            return i
    raise ValueError("sub-plan missing from the complete universe")


def parent_stats(rec: Mapping[str, Any], choice_agg: Mapping[tuple, int], choice_ent: Mapping[tuple, int], regime: str) -> dict[str, float]:
    per_twin = []
    for t in ("A", "B"):
        tw = rec["twins"][t]
        key = (rec["structure_id"], rec["parent_index"], t)
        U = np.asarray(tw["outcomes"][regime]["U"], float)
        a, e = choice_agg[key], choice_ent[key]
        pl = tw.get("planner", {"chosen_index": 0})["chosen_index"]
        m = U.mean(axis=0)
        plans = tw["plans"]
        c_idx = _find(plans, plans[e]["coord"], [])
        r_idx = _find(plans, [], plans[e]["reinf"])
        per_twin.append({
            "delta_rep": m[a] - m[e], "U_hab": m[0], "U_agg": m[a], "U_ent": m[e], "U_plan": m[pl],
            "U_star": float(U.min(axis=1).mean()), "gain_ent": m[0] - m[e], "gain_agg": m[0] - m[a],
            "gain_plan": m[0] - m[pl], "regret_ent": m[e] - float(U.min(axis=1).mean()),
            "regret_agg": m[a] - float(U.min(axis=1).mean()),
            "ent_res_only": m[0] - m[r_idx], "ent_coord_at_equal_res": m[r_idx] - m[e],
            "ent_interaction": m[c_idx] + m[r_idx] - m[e] - m[0],
            "planned_hours_ent": plans[e]["planned_hours"], "planned_hours_agg": plans[a]["planned_hours"],
            "harm_ent": float(m[e] - m[0] > DELTA), "harm_agg": float(m[a] - m[0] > DELTA),
            "same_choice": float(plans[a]["key"] == plans[e]["key"]),
        })
    out = {k: float(np.mean([pt[k] for pt in per_twin])) for k in STATS}
    out["harm_ent"] = float(any(pt["harm_ent"] for pt in per_twin))
    out["harm_agg"] = float(any(pt["harm_agg"] for pt in per_twin))
    return out


def group(records: Sequence[Mapping[str, Any]], ca: Mapping[tuple, int], ce: Mapping[tuple, int], regime: str) -> list[np.ndarray]:
    by_s: dict[str, list[list[float]]] = {}
    for r in sorted(records, key=lambda r: (r["structure_index"], r["parent_index"])):
        st = parent_stats(r, ca, ce, regime)
        by_s.setdefault(r["structure_id"], []).append([st[k] for k in STATS])
    return [np.asarray(v, float) for v in by_s.values()]


def precision_projection(structs: Sequence[np.ndarray], n_eval_structures: int = 30) -> dict[str, Any]:
    i = STATS.index("delta_rep")
    means = np.asarray([float(np.mean(s[:, i])) for s in structs])
    sd = float(np.std(means, ddof=1))
    hw = Z * sd / math.sqrt(n_eval_structures)
    return {"partition": "P5b_val", "structures": len(means), "sd_between_structure_means_delta_rep": sd,
            "projected_half_width": hw, "threshold": HALF_WIDTH_MAX, "precision_sufficient": hw <= HALF_WIDTH_MAX,
            "declared_reading": "confirmatory" if hw <= HALF_WIDTH_MAX else "exploratory"}


def analyse(records: Sequence[Mapping[str, Any]], meta: Sequence[Mapping[str, Any]], ca: Mapping[tuple, int],
            ce: Mapping[tuple, int], regime: str, seed: int, resamples: int, precision_sufficient: bool,
            isolation_ok: bool, primary: bool) -> dict[str, Any]:
    structs = group(records, ca, ce, regime)
    est = weighted_means(structs)
    boot = bootstrap(structs, resamples, seed)
    idx = {k: i for i, k in enumerate(STATS)}
    point = {k: float(est[i]) for k, i in idx.items()}
    intervals = {k: ci(boot[:, i]) for k, i in idx.items()}
    harmed = [bool(np.any(s[:, idx["harm_ent"]] > 0)) for s in structs]
    harmed_agg = [bool(np.any(s[:, idx["harm_agg"]] > 0)) for s in structs]
    cand = sum(int(m["candidates"]) for m in meta)
    excl = sum(sum(m["exclusions"].values()) for m in meta)
    rate = excl / cand if cand else 0.0
    harm_upper = clopper_pearson_upper(sum(harmed), len(harmed))
    guard = {"exclusion_rate": rate, "exclusion_ok": rate <= EXCLUSION_MAX,
             "harm_M_ent": {"harmed_structures": sum(harmed), "structures": len(harmed), "cp_upper_one_sided_95": harm_upper,
                            "ok": harm_upper <= HARM_MAX,
                            "event": "twin harmed iff mean over K=3 of (U_ent - U_hab) > 15; parent iff >= 1 twin; structure iff >= 1 parent"},
             "harm_M_agg_descriptive": {"harmed_structures": sum(harmed_agg), "cp_upper_one_sided_95": clopper_pearson_upper(sum(harmed_agg), len(harmed_agg))},
             "isolation_50_no_true_failure": isolation_ok}
    lo, hi = intervals["delta_rep"]
    ok = guard["exclusion_ok"] and guard["harm_M_ent"]["ok"] and isolation_ok
    if hi < DELTA:
        verdict = "insufficient"
    elif lo > DELTA and ok and precision_sufficient:
        verdict = "demonstrated_in_this_synthetic_protocol"
    else:
        verdict = "inconclusive" if precision_sufficient else "exploratory"
    return {"regime": regime, "role": "primary" if primary else "robustness_only_cannot_upgrade_R1",
            "structures": len(structs), "parents": int(sum(len(s) for s in structs)), "point": point, "ci95": intervals,
            "guardrails": guard, "delta": DELTA, "verdict": verdict if primary else f"{verdict} (robustness reading only)"}
