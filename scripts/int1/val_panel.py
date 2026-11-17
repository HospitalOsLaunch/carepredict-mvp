#!/usr/bin/env python3
"""HOWM-INT-1 VAL closed-loop panel (selection only): chooses B* among the cheap references (rules and D variants)
and the primary W size (S or M ensemble), by mean 7-day wait on 40 two-unit INT_VAL structures x episode 0 x
futures 1-2. Rule fixed before use: minimal mean wait; tie -> simpler (rules < Ridge < HGB < DSet; S < M).

    val_panel.py --systems JSON [--par 4]
JSON: {"W": {"W_S": [runs], "W_M": [runs]}, "D": {"D_ridge": {...}, ...}} (same format as FREEZE_INT1 entries)."""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts/int1"))
EV = ROOT / "evidence/howm_int1"
ORDER = ["historical", "robust", "D_ridge", "D_hgb", "D_dset", "W_S", "W_M"]


def job(arg):
    s, systems = arg
    import corpus as CO
    import eval_campaign as EC

    from hospitalos.howmint import loop as L
    from hospitalos.howmint import world as W

    sp = W.episode(W.structure("INT_VAL", s, 2), 0)
    pre = L.prefix(sp, CO.h0_of("INT_VAL", s, 0, 2))
    fr = {"W_systems": systems["W"], "D_systems": systems["D"], "Md": 16}
    out = {}
    for r in (1, 2):
        timing, antic = {}, []
        pols = EC.build_policies(fr, "MAIN", 2, 24, timing, antic)
        for name, pol in pols.items():
            out.setdefault(name, []).append(L.closed_loop(sp, pre, r, pol, 7, 24, 168)["wait_patient_min"])
    return s, {k: float(np.mean(v)) for k, v in out.items()}


def main() -> int:
    import corpus as CO

    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", required=True)
    ap.add_argument("--par", type=int, default=4)
    a = ap.parse_args()
    systems = json.loads(Path(a.systems).read_text())
    two = [s for s in range(300) if CO.size_of("INT_VAL", s) == 2][:40]
    t0 = time.time()
    with get_context("fork").Pool(a.par) as pool:
        rows = dict(pool.map(job, [(s, systems) for s in two]))
    names = sorted({k for v in rows.values() for k in v}, key=lambda k: ORDER.index(k) if k in ORDER else 99)
    mean = {k: float(np.mean([rows[s][k] for s in rows])) for k in names}
    cheap = [k for k in names if not k.startswith("W_")]
    bstar = min(cheap, key=lambda k: (round(mean[k], 3), ORDER.index(k) if k in ORDER else 99))
    wsys = [k for k in names if k.startswith("W_")]
    wprim = min(wsys, key=lambda k: (round(mean[k], 3), ORDER.index(k) if k in ORDER else 99)) if wsys else None
    diffs = {k: float(np.std([rows[s][bstar] - rows[s][k] for s in rows]) / np.sqrt(len(rows))) for k in wsys}
    out = {"structures": two, "mean_wait": mean, "B_star": bstar, "W_primary": wprim, "se_Bstar_minus_W": diffs, "per_structure": rows,
           "seconds": time.time() - t0, "rule": "minimal mean wait; tie -> simpler"}
    (EV / "VAL_PANEL.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("mean_wait", "B_star", "W_primary", "se_Bstar_minus_W")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
