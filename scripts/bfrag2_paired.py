#!/usr/bin/env python3
"""B-FRAG 2 propagation controls (PROTOCOLE_BFRAG2 s.9): for each structure/episode, the same episode
(same keys, same arrivals) with ONE dependency relaxed; generation only (no method). Atomic per structure."""

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "evidence/howm2_bfrag2/runs/PAIRED"


def summ(trace, runs):
    return {"rupture_minutes": 15 * sum(b - a for v in runs.values() for a, b, _s in v),
            "onsets": sum(len(v) for v in runs.values()),
            "n24_ticks": sum(1 for r in trace if any(r[u]["n24"] > 0 for u in r)),
            "block_ticks": {k: sum(r[u][k] for r in trace for u in r) for k in ("block_compat", "block_clean", "block_transport")}}


def job(arg):
    part, s = arg
    from hospitalos.bfrag2 import core2 as C

    p = OUT / part / f"s{s:03d}.json"
    if p.exists():
        return 0
    w = C.structure(part, s, json.loads((ROOT / "docs/howm2/bfrag/DESIGN_D2.json").read_text()))
    rec = {"part": part, "structure": s, "family": w.family, "has_calendar": bool(w.drop), "episodes": []}
    for e in range(3):
        ep, tr = C.generate2(C.episode_spec(w, e), [], w.drop)
        row = {"base": summ(tr, C.rupture_runs(tr))}
        for dep in C.PAIRED_DEPS:
            sp, cal = C.paired_spec(w, e, dep)
            _ep, trd = C.generate2(sp, [], cal)
            row[dep] = summ(trd, C.rupture_runs(trd))
        rec["episodes"].append(row)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec) + "\n")
    tmp.replace(p)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="BF2_CONF")
    ap.add_argument("--s0", type=int, default=0)
    ap.add_argument("--s1", type=int, default=60)
    ap.add_argument("--par", type=int, default=4)
    a = ap.parse_args()
    t = time.time()
    with get_context("fork").Pool(a.par, maxtasksperchild=4) as pool:
        n = sum(pool.imap_unordered(job, [(a.part, s) for s in range(a.s0, a.s1)]))
    print(json.dumps({"done_now": n, "files": len(list((OUT / a.part).glob("*.json"))), "seconds": round(time.time() - t, 1)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
