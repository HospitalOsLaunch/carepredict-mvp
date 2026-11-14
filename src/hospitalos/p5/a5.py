"""A5 timing benchmark (P5-PROTO-3 A5, P5-PROTO-3.1 R4; authorised by D15 only).

Six timing fits: M_agg and M_ent x random_state {0, 1, 2}, max_depth 5, learning_rate 0.1,
max_iter 400, protocol fixed parameters, OMP_NUM_THREADS=1, on 1440 TILED development rows.
Rows come from the historical E0 pilot parents (P5a_dev structures 0-1): their public snapshots
are regenerated deterministically (no truth simulation) and their labels are the R1 mean
realised U already recorded by that pilot, so nothing of the pilot is recounted or re-run.
Models are discarded after measurement; no prediction is kept for any evaluation.

Limits (declared): repeated rows do not demonstrate the cost on a diverse corpus; the fit may
stop before max_iter if trees can no longer split (``n_iter_`` is recorded); timings are for
this machine and this benchmark only.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .features import SnapshotFeatures
from .generator import generate_structure

FAMILIES = ("M_agg", "M_ent")
SEEDS = (0, 1, 2)
N_ROWS = 1440
CONFIG = {"max_depth": 5, "learning_rate": 0.1, "max_iter": 400}
# Protocol fixed parameters (P5-PROTO-2 § 6.4 / params P5b_design.models.fixed). Parameters
# described as "default, no effect" with early_stopping=False are left at their defaults.
FIXED = {
    "early_stopping": False,
    "loss": "squared_error",
    "max_leaf_nodes": 31,
    "min_samples_leaf": 20,
    "l2_regularization": 0.0,
    "max_bins": 255,
    "max_features": 1.0,
    "categorical_features": None,
    "monotonic_cst": None,
    "interaction_cst": None,
    "warm_start": False,
    "verbose": 0,
}
IDENTITY_TOL = 1e-12


class A5Error(RuntimeError):
    """Preparation inconsistency or forbidden condition: nothing is fitted."""


def hgb_params(seed: int) -> dict[str, Any]:
    if seed not in SEEDS:
        raise A5Error(f"seed {seed} not in the A5 plan")
    return {**FIXED, **CONFIG, "random_state": seed}


def check_threads(environ: Mapping[str, str] = os.environ) -> None:
    if environ.get("OMP_NUM_THREADS") != "1":
        raise A5Error("OMP_NUM_THREADS must be 1 for A5")


def development_rows(
    records: Sequence[Mapping[str, Any]],
    seeds: Sequence[int],
    profile: Mapping[str, Any],
    partition: str = "P5a_dev",
    n_parents: int = 10,
) -> dict[str, Any]:
    """Distinct (X, y) per family from the historical pilot parents; refuses any mismatch."""
    by_key = {(int(r["structure"]), int(r["parent_index"])): r for r in records}
    rows: dict[str, list[list[float]]] = {f: [] for f in FAMILIES}
    names: dict[str, list[str]] = {}
    y: list[float] = []
    used = 0
    for s_idx, seed in enumerate(seeds):
        valid, _ = generate_structure(partition, seed, n_parents, profile, twins=False)
        for cand in valid:
            rec = by_key.get((s_idx, cand.parent_index))
            if rec is None:
                raise A5Error(f"no pilot record for structure {s_idx} parent {cand.parent_index}")
            ep = cand.episodes["A"]
            if int(rec["n_plans"]) != len(ep.plans):
                raise A5Error(f"plan count differs from the pilot record at ({s_idx},{cand.parent_index})")
            u = rec["U_dev_only"]["R1"]
            labels = [sum(rep[i] for rep in u) / len(u) for i in range(len(ep.plans))]
            feats = SnapshotFeatures(ep.snapshot, ep.sidecar, profile)
            for plan in ep.plans:
                for fam in FAMILIES:
                    n, v = feats.row(plan, fam)
                    names.setdefault(fam, n)
                    rows[fam].append(v)
            y.extend(labels)
            used += 1
    if used != len(records):
        raise A5Error(f"{used} parents regenerated but {len(records)} pilot records")
    out = {"y": np.asarray(y, dtype=np.float64), "parents": used}
    for fam in FAMILIES:
        out[fam] = np.asarray(rows[fam], dtype=np.float64)
        out[f"{fam}_names"] = names[fam]
    return out


def tile(X: np.ndarray, y: np.ndarray, n: int = N_ROWS) -> tuple[np.ndarray, np.ndarray]:
    idx = np.arange(n) % len(y)
    return np.ascontiguousarray(X[idx]), np.ascontiguousarray(y[idx])


def fingerprint(*arrays: np.ndarray) -> str:
    h = hashlib.sha256()
    for a in arrays:
        h.update(str(a.shape).encode())
        h.update(np.ascontiguousarray(a, dtype=np.float64).tobytes())
    return h.hexdigest()


def run_family(
    family: str,
    X: np.ndarray,
    y: np.ndarray,
    estimator_factory: Callable[[dict[str, Any]], Any],
    budget_s: float,
    progress: Callable[[dict[str, Any]], None] = lambda _: None,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Fits seeds 0, 1, 2 on identical data; before seed k >= 1, refuses to start if the time
    already used in this family plus the seed-0 fit duration exceeds ``budget_s``."""
    if family not in FAMILIES:
        raise A5Error(family)
    start = clock()
    results: list[dict[str, Any]] = []
    reference = None
    stop = None
    for seed in SEEDS:
        if seed > 0 and (clock() - start) + results[0]["fit_s"] > budget_s:
            stop = {"reason": "budget_rule_before_seed", "seed": seed,
                    "elapsed_s": clock() - start, "seed0_fit_s": results[0]["fit_s"], "budget_s": budget_s}
            break
        est = estimator_factory(hgb_params(seed))
        t = clock()
        est.fit(X, y)
        fit_s = clock() - t
        t = clock()
        pred = np.asarray(est.predict(X), dtype=np.float64)
        predict_s = clock() - t
        if reference is None:
            reference = pred
        diff = float(np.max(np.abs(pred - reference)))
        row = {"seed": seed, "fit_s": fit_s, "predict_s": predict_s,
               "n_iter": int(getattr(est, "n_iter_", -1)), "max_abs_diff_vs_seed0": diff}
        results.append(row)
        progress(row)
        del est  # model discarded
    complete = len(results) == len(SEEDS)
    identical = complete and all(r["max_abs_diff_vs_seed0"] <= IDENTITY_TOL for r in results)
    return {"family": family, "results": results, "complete": complete,
            "seed_identity_within_tolerance": identical, "tolerance": IDENTITY_TOL, "stop": stop}


def output_guard(path: Path) -> None:
    """A family already measured (or started) is never re-fitted implicitly."""
    if path.exists():
        raise A5Error(f"{path.name} exists: A5 fits of this family are not re-run")


def write_json(path: Path, body: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(dict(body), indent=1, sort_keys=True, default=float) + "\n")
