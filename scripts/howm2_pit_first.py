#!/usr/bin/env python3
"""HOWM-2 A3(a') (addendum 2): one PIT per item (first scored appearance) for L4 and L5 (control),
on HOWM2_REF. Resumable, one file per establishment."""
import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import json, sys, time
from multiprocessing import get_context
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "evidence" / "howm2" / "pit_first" / "HOWM2_REF"


def job(i):
    f = OUT / f"{i:03d}.json"
    if f.exists():
        return i
    from hospitalos.howm.b0 import B0Params
    from hospitalos.howm2 import space
    from hospitalos.howm2.ladder import run_establishment
    space.register()
    p = B0Params.from_json(json.loads((ROOT / "evidence/howm1/B0_PARAMS.json").read_text()))
    pits = run_establishment("HOWM2_REF", i, p, pit_levels=("L4", "L5"), keep_items=True)["pits"]
    first = {}
    for lv in ("L4", "L5"):
        first[lv] = {}
        for fam, rows in pits[lv].items():
            if fam == "arrivals":
                continue
            seen = {}
            for ref, start, H, v in sorted(rows, key=lambda r: r[2]):
                seen.setdefault((ref, start), v)
            first[lv][fam] = list(seen.values())
    f.write_text(json.dumps(first) + "\n")
    return i


OUT.mkdir(parents=True, exist_ok=True)
t0 = time.time()
with get_context("fork").Pool(4) as pool:
    for i in pool.imap_unordered(job, range(200)):
        if time.time() - t0 > 480:
            print("budget reached (resumable)"); pool.terminate(); break
print(json.dumps({"files": len(list(OUT.glob("*.json"))), "seconds": round(time.time() - t0, 1)}))
