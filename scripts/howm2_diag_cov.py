#!/usr/bin/env python3
"""HOWM-2 A5 diagnostic of the H1 90 % coverage (0.72 in R1) on VAL with B0-local.

At the 48 VAL decision origins (12 establishments x 07/11/15/19 h of day 5), M = 16 B0-local
rollouts (same providers and keys as R1) are run (i) from the PUBLIC engine, as in R1, and (ii) from
the TRUE engine at that instant. Reported per start: 90 % and 50 % coverage at h = 1, 6, 24, share of
degenerate 90 % intervals (q05 == q95), and randomized PIT (KS distance to uniform)."""

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


def job(i: int) -> dict:
    from howm_eval import M, freq, providers

    from hospitalos.howm import corpus as C
    from hospitalos.howm import generator as G
    from hospitalos.howm.b0 import B0Params
    from hospitalos.howm.history import PublicStream
    from hospitalos.howm.keys import key
    from hospitalos.howm.predict import b0_predict
    from hospitalos.howm.rollout import rollout, rollout_key, target_vector, truth_vector
    from hospitalos.howm.world import TPH

    p = B0Params.from_json(json.loads((C.EVID / "B0_PARAMS.json").read_text()))
    fr = freq(p)
    est = C.load("VAL", i)["data"]
    ep = G.generate(G.establishment("VAL", i), keep_instants=True)
    assert len(ep.instants) == 4
    rng = np.random.default_rng(int(key("HOWM2", "pit", "VAL", i) % (2**31)))
    out = {s: {str(h): {"c90": [], "c50": [], "deg90": [], "pit": []} for h in HS} for s in ("public", "true")}
    for tau in sorted(ep.instants):
        H = tau // TPH
        od = est.origins[H]
        pr = [b0_predict(p, od, est, True)]
        ps = PublicStream(ep.observations)
        ps.advance(tau * 15)
        starts = {"public": ps.to_engine(tau * 15), "true": ep.instants[tau]}
        for s, eng in starts.items():
            res = [rollout(eng, pv, None) for pv in providers(pr, od, 4 * H, rollout_key("VAL", i, H), M, fr)]
            for h in HS:
                y = truth_vector(ep, H, h)
                if y is None:
                    continue
                y = np.array(y)
                samp = np.array([target_vector(r, h) for r in res])
                q05, q95 = np.quantile(samp, 0.05, 0), np.quantile(samp, 0.95, 0)
                q25, q75 = np.quantile(samp, 0.25, 0), np.quantile(samp, 0.75, 0)
                F_lo = (samp < y[None]).mean(0)
                F_hi = (samp <= y[None]).mean(0)
                pit = F_lo + rng.random(len(y)) * (F_hi - F_lo)
                b = out[s][str(h)]
                b["c90"] += ((y >= q05) & (y <= q95)).tolist()
                b["c50"] += ((y >= q25) & (y <= q75)).tolist()
                b["deg90"] += (q05 == q95).tolist()
                b["pit"] += pit.tolist()
    return out


def ks(u: np.ndarray) -> float:
    u = np.sort(u)
    n = len(u)
    return float(max((np.arange(1, n + 1) / n - u).max(), (u - np.arange(n) / n).max()))


def main() -> int:
    with get_context("fork").Pool(4) as pool:
        parts = pool.map(job, range(12))
    summ = {}
    for s in ("public", "true"):
        summ[s] = {}
        for h in HS:
            c90 = np.concatenate([np.array(pt[s][str(h)]["c90"], float) for pt in parts])
            c50 = np.concatenate([np.array(pt[s][str(h)]["c50"], float) for pt in parts])
            dg = np.concatenate([np.array(pt[s][str(h)]["deg90"], float) for pt in parts])
            pit = np.concatenate([np.array(pt[s][str(h)]["pit"], float) for pt in parts])
            nd = dg == 0
            summ[s][str(h)] = {
                "n": int(len(c90)),
                "coverage90": float(c90.mean()),
                "coverage50": float(c50.mean()),
                "degenerate90_share": float(dg.mean()),
                "coverage90_non_degenerate": float(c90[nd].mean()) if nd.any() else None,
                "coverage90_degenerate": float(c90[~nd].mean()) if (~nd).any() else None,
                "pit_KS_D": ks(pit),
                "pit_hist10": np.histogram(pit, bins=10, range=(0, 1))[0].tolist(),
            }
    out = {"note": "VAL only; DEVTEST/DIAG-DEV not read; R1 results unchanged", "M": 16, "summary": summ}
    (ROOT / "evidence/howm2/DIAG_COVERAGE.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(summ, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
