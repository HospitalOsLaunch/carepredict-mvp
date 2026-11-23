#!/usr/bin/env python3
"""HOWM-2 tranche A: information ladder runs (resumable, one file per establishment).

run --partition P --start a --stop b --workers 4
"""

from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"  # one BLAS thread per worker process (4 workers on 4 cores)

import argparse
import json
import sys
import time
from multiprocessing import get_context
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "evidence" / "howm2" / "ladder"


def _job(args: tuple[str, int]) -> tuple[int, float]:
    part, idx = args
    from hospitalos.howm import g0check
    from hospitalos.howm.b0 import B0Params
    from hospitalos.howm2 import space
    from hospitalos.howm2.ladder import run_establishment

    space.register()
    g0check.check()
    p = B0Params.from_json(json.loads((ROOT / "evidence/howm1/B0_PARAMS.json").read_text()))
    f = OUT / part / f"{idx:03d}.json"
    if f.exists():
        return idx, 0.0
    t0 = time.time()
    res = run_establishment(part, idx, p)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(res) + "\n")
    tmp.replace(f)
    return idx, time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--partition", default="HOWM2_REF")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--stop", type=int, default=10**6)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--budget", type=float, default=480.0)
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT / "src"))
    from hospitalos.howm.generator import PARTITION_SIZES
    from hospitalos.howm2 import space

    space.register()
    n = PARTITION_SIZES[a.partition]
    (OUT / a.partition).mkdir(parents=True, exist_ok=True)
    todo = [
        (a.partition, i)
        for i in range(a.start, min(a.stop, n))
        if not (OUT / a.partition / f"{i:03d}.json").exists()
    ]
    t0 = time.time()
    done = 0
    with get_context("fork").Pool(a.workers, maxtasksperchild=20) as pool:
        for idx, sec in pool.imap_unordered(_job, todo):
            done += 1
            print(idx, round(sec, 1), flush=True)
            if time.time() - t0 > a.budget:
                print("budget reached; stopping (resumable)", flush=True)
                pool.terminate()
                break
    print(
        json.dumps(
            {
                "partition": a.partition,
                "done_now": done,
                "todo_was": len(todo),
                "seconds": round(time.time() - t0, 1),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
