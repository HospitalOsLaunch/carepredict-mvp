#!/usr/bin/env python3
"""HOWM-INT-1 evaluation cost pilot on DEV (no test data): CPU per closed-loop run and per decision for every
policy class, with tier-1 trained models (W-S / W-M ensembles, D variants) and F / R1 at Md = 16. Used only to fix
the feasible evaluation plan before the freeze."""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts/int1"))
SYS = {"W": {"W_S": ["W_t1_S_s0", "W_t1_S_s1", "W_t1_S_s2"], "W_M": ["W_t1_M_s0", "W_t1_M_s1", "W_t1_M_s2"]},
       "D": {"D_ridge": {"kind": "ridge", "run": "D_t1_ridge", "name": "ridge_100.0"}, "D_hgb": {"kind": "hgb", "run": "D_t1_hgb", "name": "hgb_8"},
             "D_dset": {"kind": "dset", "run": "D_t1_dset", "norm_run": "W_t1_S_s0"}}, "Md": 16}


def job(arg):
    task, n, s = arg
    import eval_campaign as EC

    from hospitalos.howmint import loop as L
    from hospitalos.howmint import world as W

    sp = W.episode(W.structure("INT_DEV", 500 + s, n), 0)
    pre = L.prefix(sp, 48)
    week = n == 2
    nd, iv, hz = (7, 24, 168) if week else (4, 6, 24)
    fr = {"W_systems": SYS["W"], "D_systems": SYS["D"], "Md": SYS["Md"]}
    timing, antic = {}, []
    pols = EC.build_policies(fr, "SUB32" if task == "sim" else "MAIN", n, iv, timing, antic)
    out = {}
    for name, pol in pols.items():
        t0 = time.process_time()
        L.closed_loop(sp, pre, 1, pol, nd, iv, hz)
        out[name] = {"run_cpu_s": time.process_time() - t0, "decision_cpu_s": timing.get(name, [])[-nd:]}
    return task, n, s, out


def main() -> int:
    todo = [("main", 2, 0), ("main", 2, 1), ("main", 4, 2), ("main", 8, 3), ("main", 12, 4), ("sim", 2, 5)]
    t = time.time()
    with get_context("fork").Pool(4) as pool:
        rows = pool.map(job, todo)
    res = {f"{task}|n{n}|s{s}": {k: {"run_cpu_s": round(v["run_cpu_s"], 2), "decision_mean_s": round(sum(v["decision_cpu_s"]) / max(1, len(v["decision_cpu_s"])), 3)}
                                 for k, v in out.items()} for task, n, s, out in rows}
    (ROOT / "evidence/howm_int1/EVAL_COSTPILOT_DEV.json").write_text(json.dumps({"rows": res, "wall_s": time.time() - t}, indent=1))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
