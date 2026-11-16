#!/usr/bin/env python3
"""Descriptive diagnostic of A3(a): PIT of L4 and L5 (true laws) on 40 HOWM2_REF establishments,
all appearances vs first appearance of each item (one PIT per item)."""

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import json, math, sys
from multiprocessing import get_context
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def job(i):
    from hospitalos.howm.b0 import B0Params
    from hospitalos.howm2 import space
    from hospitalos.howm2.ladder import run_establishment

    space.register()
    p = B0Params.from_json(json.loads((ROOT / "evidence/howm1/B0_PARAMS.json").read_text()))
    return run_establishment("HOWM2_REF", i, p, pit_levels=("L4", "L5"), keep_items=True)["pits"]


def ks(u):
    u = np.sort(np.asarray(u))
    n = len(u)
    i = np.arange(1, n + 1)
    return float(max(np.max(i / n - u), np.max(u - (i - 1) / n))), n


with get_context("fork").Pool(4) as pool:
    res = pool.map(job, range(40))
out = {}
for lv in ("L4", "L5"):
    for fam in ("ready", "transport", "cleaning", "confirmation"):
        rows = [r for pits in res for r in pits[lv].get(fam, []) if isinstance(r, list)]
        allv = [r[3] for r in rows]
        first = {}
        for i, (ref, start, H, v) in enumerate(rows):
            first.setdefault(
                (i // 10**9, ref, start), v
            )  # first origin at which the item is scored
        fv = list(first.values())
        D, n = ks(allv)
        D1, n1 = ks(fv)
        out[f"{lv}:{fam}"] = {
            "all": {
                "n": n,
                "D": round(D, 4),
                "thr_indep": round(max(0.02, 1.63 / math.sqrt(n)), 4),
            },
            "first_appearance": {
                "n": n1,
                "D": round(D1, 4),
                "thr_indep": round(max(0.02, 1.63 / math.sqrt(n1)), 4),
            },
            "hist10_first": np.histogram(fv, bins=10, range=(0, 1))[0].tolist(),
        }
(ROOT / "evidence/howm2/DIAG_PIT.json").write_text(json.dumps(out, indent=1) + "\n")
print(json.dumps(out, indent=1))
