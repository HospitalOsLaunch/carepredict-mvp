#!/usr/bin/env python3
"""B-FRAG 2 driver (decision n.7, PROTOCOLE_BFRAG2).

    run --part P --tag T --mode features|val|full --s0 a --s1 b [--Mr 32 --Md 8 --E 8] [--par 4] [--budget s]
        one JSON per episode: evidence/howm2_bfrag2/runs/<T>/<P>/s<sss>_e<e>.json (atomic, resumable)
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
EV = ROOT / "evidence/howm2_bfrag2"
DESIGN = ROOT / "docs/howm2/bfrag/DESIGN_D2.json"  # B-FRAG 1 structural design reused (structure strata)


def job(arg):
    part, s, e, tag, mode, Mr, Md, E = arg
    from hospitalos.bfrag2 import core2 as C
    from hospitalos.howm.b0 import B0Params
    from hospitalos.howm.world import TPH

    out_p = EV / "runs" / tag / part / f"s{s:03d}_e{e}.json"
    if out_p.exists():
        return 0
    t_all = time.time()
    tm = {}
    w = C.structure(part, s, json.loads(DESIGN.read_text()))
    spec_e = C.episode_spec(w, e)
    t = time.time()
    origin_ticks = [h * TPH for h in C.ORIGIN_HOURS]
    ep, trace = C.generate2(spec_e, origin_ticks, w.drop)
    runs = C.rupture_runs(trace)
    tm["generate"] = time.time() - t
    t = time.time()
    snaps = {}
    for h in C.SNAP_HOURS:
        _pub, _ps, pe = C.public_state(ep, h * TPH)
        snaps[h] = C.s1_features(pe)
    p = B0Params.from_json(json.loads((ROOT / "evidence/howm1/B0_PARAMS.json").read_text()))
    origins = []
    for h in C.ORIGIN_HOURS:
        t0 = h * TPH
        pub, ps, pe = C.public_state(ep, t0)
        f1 = snaps[h]
        rec = {"hour": h, "labels": C.labels_at(runs, t0, len(trace)), "manifest": C.manifest_pressure(f1),
               "S0": C.s0_features(w, t0), "S1": f1, "S2": C.s2_history(pub, t0, snaps)}
        if mode in ("full", "val"):
            ts = time.time()
            rec["score"] = {"R0": C.score_R0(w, pe, t0),
                            "R1": C.risk72(C.r1_pairs(w, pub, ps, pe, t0, p, Mr), w.drop),
                            "F": C.risk72(C.f_pairs(w, pub, ps, pe, t0, Mr), w.drop),
                            "O": C.risk72(C.o_pairs(w, spec_e, ep, t0, Mr), w.drop)}
            rec["score_seconds"] = time.time() - ts
        origins.append(rec)
    tm["origins"] = time.time() - t
    dec = None
    if mode in ("full", "val"):
        t = time.time()
        hd = C.DECISION_HOURS[e % 3]
        t0 = hd * TPH
        pub, ps, pe = C.public_state(ep, t0)
        acts = C.catalogue(t0)
        plans = {}
        ts = time.time()  # R1 planner (public statistical planner) in "val" and "full" modes
        plans["R1_planner"] = C.planner(C.r1_pairs(w, pub, ps, pe, t0, p, Md), w.drop, acts)
        tm["plan_R1"] = time.time() - ts
        if mode == "full":  # F and O planners only in the single CONF campaign (and DEV cost checks)
            ts = time.time()
            plans["F_planner"] = C.planner(C.f_pairs(w, pub, ps, pe, t0, Md), w.drop, acts)
            tm["plan_F"] = time.time() - ts
            ts = time.time()
            plans["O_planner"] = C.planner(C.o_pairs(w, spec_e, ep, t0, Md), w.drop, acts)
            tm["plan_O"] = time.time() - ts
        ts = time.time()
        ev = C.evaluate_actions(w, spec_e, ep, t0, acts, E)
        tm["evaluate"] = time.time() - ts
        dec = {"hour": hd, "actions": [{k: a[k] for k in ("id", "staff_hours")} | {"extra": {r: list(v) for r, v in a["extra"].items()}} for a in acts],
               "plans": plans, "eval": ev}
        tm["decision"] = time.time() - t
    trace_sum = {"block_ticks": {un: {k: sum(r[un][k] for r in trace) for k in ("block_compat", "block_clean", "block_transport")} for un in trace[0]},
                 "n24_ticks": {un: sum(1 for r in trace if r[un]["n24"] > 0) for un in trace[0]},
                 "attribution_at_n24": {un: {k: sum(r[un][k] for r in trace if r[un]["n24"] > 0) for k in ("block_compat", "block_clean", "block_transport")} for un in trace[0]},
                 "rupture_runs": {un: [list(x) for x in v] for un, v in runs.items()}}
    tm["total"] = time.time() - t_all
    rec = {"part": part, "structure": s, "episode": e, "family": w.family, "mode": mode, "Mr": Mr, "Md": Md, "E": E,
           "origins": origins, "decision": dec, "trace": trace_sum, "timing_s": tm,
           "maxrss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}
    out_p.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec) + "\n")
    tmp.replace(out_p)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--part")
    ap.add_argument("--tag")
    ap.add_argument("--mode", default="full")
    ap.add_argument("--s0", type=int, default=0)
    ap.add_argument("--s1", type=int, default=1)
    ap.add_argument("--episodes", type=int, default=3)
    ap.add_argument("--Mr", type=int, default=32)
    ap.add_argument("--Md", type=int, default=8)
    ap.add_argument("--E", type=int, default=8)
    ap.add_argument("--par", type=int, default=4)
    ap.add_argument("--budget", type=float, default=420.0)
    a = ap.parse_args()
    t0 = time.time()
    todo = [(a.part, s, e, a.tag, a.mode, a.Mr, a.Md, a.E) for s in range(a.s0, a.s1) for e in range(a.episodes)
            if not (EV / "runs" / a.tag / a.part / f"s{s:03d}_e{e}.json").exists()]
    n = 0
    with get_context("fork").Pool(a.par, maxtasksperchild=1) as pool:
        for _ in pool.imap_unordered(job, todo):
            n += 1
            if time.time() - t0 > a.budget:
                pool.terminate()
                break
    d = EV / "runs" / a.tag / a.part
    print(json.dumps({"tag": a.tag, "part": a.part, "done_now": n, "files": len(list(d.glob("*.json"))) if d.exists() else 0,
                      "seconds": round(time.time() - t0, 1)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
