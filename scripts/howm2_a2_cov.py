#!/usr/bin/env python3
"""HOWM-2 A2.COV (NORM A2 N3, addendum A2-1 s.5): B0-local rollouts from three starts (public,
L4-N, true) at the 48 VAL decision origins; same targets, M = 16 and keys as DIAG_COVERAGE.json.
Descriptive only. L4-N start of rollout j = nowcast of world draw j (keys r = 301 + j)."""

from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

import json  # noqa: E402
import sys  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
HS = (1, 6, 24)
STARTS = ("public", "L4N", "true")


def job(i: int) -> dict:
    from howm_eval import M, freq, providers

    from hospitalos.howm import corpus as C
    from hospitalos.howm.b0 import B0Params
    from hospitalos.howm.keys import key
    from hospitalos.howm.predict import b0_predict
    from hospitalos.howm.rollout import rollout, rollout_key, target_vector, truth_vector
    from hospitalos.howm.world import TPH
    from hospitalos.howm2 import a2

    p = B0Params.from_json(json.loads((C.EVID / "B0_PARAMS.json").read_text()))
    fr = freq(p)
    est = C.load("VAL", i)["data"]
    rng = np.random.default_rng(int(key("HOWM2", "pit", "VAL", i) % (2**31)))  # same PIT stream as DIAG_COVERAGE
    out = {s: {str(h): {"c90": [], "c50": [], "deg90": [], "pit": []} for h in HS} for s in STARTS}
    pend = []
    for ins in a2.setup("VAL", i):
        tau = ins.tau
        H = tau // TPH
        od = est.origins[H]
        pr = [b0_predict(p, od, est, True)]
        provs = providers(pr, od, 4 * H, rollout_key("VAL", i, H), M, fr)
        wr = np.random.default_rng(int(key("HOWM2", "A2", "cov", i, tau) % (2**31)))
        nengs = []
        for j in range(M):
            *_x, eng, applied = a2.l4n_draw(ins, wr, 301 + j)
            nengs.append(eng)
            pend.append(len(applied))
        res = {
            "public": [rollout(ins.peng, pv, None) for pv in provs],
            "L4N": [rollout(nengs[j], pv, None) for j, pv in enumerate(provs)],
            "true": [rollout(ins.ep.instants[tau], pv, None) for pv in provs],
        }
        for s in ("public", "true", "L4N"):  # public and true first: same PIT draws as DIAG_COVERAGE
            for h in HS:
                y = truth_vector(ins.ep, H, h)
                if y is None:
                    continue
                y = np.array(y)
                samp = np.array([target_vector(r, h) for r in res[s]])
                q05, q95 = np.quantile(samp, 0.05, 0), np.quantile(samp, 0.95, 0)
                q25, q75 = np.quantile(samp, 0.25, 0), np.quantile(samp, 0.75, 0)
                F_lo, F_hi = (samp < y[None]).mean(0), (samp <= y[None]).mean(0)
                b = out[s][str(h)]
                b["c90"] += ((y >= q05) & (y <= q95)).tolist()
                b["c50"] += ((y >= q25) & (y <= q75)).tolist()
                b["deg90"] += (q05 == q95).tolist()
                b["pit"] += (F_lo + rng.random(len(y)) * (F_hi - F_lo)).tolist()
    out["_pending"] = pend
    return out


def ks(u):
    u = np.sort(u)
    n = len(u)
    return float(max((np.arange(1, n + 1) / n - u).max(), (u - np.arange(n) / n).max()))


def main() -> int:
    with get_context("fork").Pool(4) as pool:
        parts = pool.map(job, range(12))
    summ = {}
    for s in STARTS:
        summ[s] = {}
        for h in HS:
            g = lambda k: np.concatenate([np.array(pt[s][str(h)][k], float) for pt in parts])  # noqa: E731
            c90, c50, dg, pit = g("c90"), g("c50"), g("deg90"), g("pit")
            nd = dg == 0
            summ[s][str(h)] = {"n": int(len(c90)), "coverage90": float(c90.mean()), "coverage50": float(c50.mean()),
                               "degenerate90_share": float(dg.mean()),
                               "coverage90_non_degenerate": float(c90[nd].mean()) if nd.any() else None,
                               "pit_KS_D": ks(pit)}
    rec = {}
    for h in HS:
        rec[str(h)] = {}
        for k in ("coverage90", "coverage50", "coverage90_non_degenerate", "pit_KS_D"):
            a, n, b = summ["public"][str(h)][k], summ["L4N"][str(h)][k], summ["true"][str(h)][k]
            rec[str(h)][k] = float((n - a) / (b - a)) if b != a else None
    ref = json.loads((ROOT / "evidence/howm2/DIAG_COVERAGE.json").read_text())["summary"]
    repro = all(abs(summ[s][h]["coverage90"] - ref[s][h]["coverage90"]) < 1e-12 for s in ("public", "true") for h in ("1", "6", "24"))
    out = {"descriptive_only": True, "flag": "L4-N validation: N-o' not passed (test limitation; addendum A2-2)",
           "M": 16, "summary": summ, "share_of_public_to_true_gap_recovered_by_L4N": rec,
           "public_and_true_reproduce_DIAG_COVERAGE": bool(repro),
           "pending_events_applied_mean_per_draw": float(np.mean([x for pt in parts for x in pt["_pending"]]))}
    (ROOT / "evidence/howm2/COVERAGE_A2.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
