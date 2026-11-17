#!/usr/bin/env python3
"""B-FRAG driver (decision n.6, PROTOCOLE_BFRAG).

    run --part P --design D --tag T [--start a --stop b] [--controls] [--M 8 --E 8] [--par 4] [--budget s]
        -> evidence/howm2_bfrag/runs/<T>/<P>/<idx>.json (atomic, resumable)
"""

from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import resource  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
EV = ROOT / "evidence/howm2_bfrag"


def design(name: str) -> dict:
    return json.loads((ROOT / "docs/howm2/bfrag" / f"DESIGN_{name}.json").read_text())


def job(arg):
    part, idx, dname, tag, M, E, controls = arg
    from hospitalos.bfrag import core as K
    from hospitalos.howm.b0 import B0Params

    out_p = EV / "runs" / tag / part / f"{idx:03d}.json"
    if out_p.exists():
        return idx
    d = design(dname)
    t_all = time.time()
    w = K.make_world(part, idx, d)
    timing = {}
    t = time.time()
    inst = K.build_instant(w)
    timing["build_instant"] = time.time() - t
    p = B0Params.from_json(json.loads((ROOT / "evidence/howm1/B0_PARAMS.json").read_text()))
    t = time.time()
    r0 = {"choice": K.plan_index_R0(inst.peng), "score": K.score_R0(inst)}
    timing["R0"] = time.time() - t
    t = time.time()
    r2 = K.plan_and_scores([(inst.peng, prov) for prov in K.r1_providers(inst, p, M)], w.drop)
    timing["R1_R2"] = time.time() - t
    t = time.time()
    f = K.plan_and_scores(K.f_samples(inst, M), w.drop)
    timing["F"] = time.time() - t
    t = time.time()
    o = K.plan_and_scores(K.o_samples(inst, M), w.drop)
    timing["O"] = time.time() - t
    plans = {"ref": 0, "R0": r0["choice"], "R2": r2["choice"], "F": f["choice"], "O": o["choice"]}
    t = time.time()
    ev = K.evaluate(inst, plans, E)
    timing["evaluate"] = time.time() - t
    ctrl = None
    if controls and w.family in K.FRAGILE:
        t = time.time()
        wr = K.make_world(part, idx, d, variant="relaxed")
        ir = K.build_instant(wr)
        ctrl = K.evaluate(ir, {"ref": 0}, E)["0"]
        timing["controls"] = time.time() - t
    timing["total"] = time.time() - t_all
    rec = {"part": part, "index": idx, "family": w.family, "design": dname, "M": M, "E": E,
           "public_inputs": {"spec_public": {"beds": w.spec.beds, "c_tr": w.spec.c_tr, "c_cl": w.spec.c_cl},
                             "calendar_drop": w.drop, "n_public_obs": len(inst.public_obs),
                             "max_avail_min": max(o[1] for o in inst.public_obs), "cut_min": 15 * K.T0},
           "methods": {"R0": r0, "R2": {k: r2[k] for k in ("choice", "mean_loss")}, "R1": {"risk": r2["risk"]},
                       "F": f, "O": o},
           "plans": plans, "eval": ev, "controls_relaxed_ref": ctrl, "timing_s": timing,
           "maxrss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}
    out_p.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec) + "\n")
    tmp.replace(out_p)  # atomic
    return idx


def run(a) -> int:
    t0 = time.time()
    todo = [(a.part, i, a.design, a.tag, a.M, a.E, a.controls) for i in range(a.start, a.stop)
            if not (EV / "runs" / a.tag / a.part / f"{i:03d}.json").exists()]
    n = 0
    with get_context("fork").Pool(a.par, maxtasksperchild=1) as pool:
        for _ in pool.imap_unordered(job, todo):
            n += 1
            if time.time() - t0 > a.budget:
                pool.terminate()
                break
    done = len(list((EV / "runs" / a.tag / a.part).glob("*.json"))) if (EV / "runs" / a.tag / a.part).exists() else 0
    print(json.dumps({"tag": a.tag, "part": a.part, "done_now": n, "files": done, "seconds": round(time.time() - t0, 1)}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--part")
    ap.add_argument("--design")
    ap.add_argument("--tag")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--stop", type=int, default=10**6)
    ap.add_argument("--M", type=int, default=8)
    ap.add_argument("--E", type=int, default=8)
    ap.add_argument("--par", type=int, default=4)
    ap.add_argument("--budget", type=float, default=420.0)
    ap.add_argument("--controls", action="store_true")
    a = ap.parse_args()
    if a.cmd == "run":
        return run(a)
    raise SystemExit(a.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
