#!/usr/bin/env python3
"""HOWM-2 A' validation of L4-N (NORM A2 N2, addendum A2-1 s.3): (N-o) literal, (N-o') Brier
companion, (N-a) calibration per pending type, with L5-N as positive control. 96 decision instants
(VAL 0-11, HOWM2_REF 0-11; day 5; 07/11/15/19 h), S = 64 draws per instant and system."""

from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
S = 64
JOBS = [("VAL", i) for i in range(12)] + [("HOWM2_REF", i) for i in range(12)]


def score(truth: dict, draws: list[dict]) -> dict:
    nll = br = 0.0
    nll_pub_inf = False
    br_pub = 0.0
    for key_, y in truth["elements"].items():
        k = sum(key_ in d["elements"] for d in draws)
        p = (k + 0.5) / (S + 1)
        nll -= math.log(p if y else 1 - p)
        br += (p - y) ** 2
        br_pub += y
        nll_pub_inf |= bool(y)
    for cell, y in truth["arrivals"].items():
        cs = [d["arrivals"].get(cell, 0) for d in draws]
        C = max(max(cs), y)
        cnt = np.bincount(cs, minlength=C + 1)
        pm = (cnt + 0.5) / (S + 0.5 * (C + 1))
        nll -= math.log(pm[y])
        onehot = np.zeros(C + 1)
        onehot[y] = 1
        br += float(np.sum((pm - onehot) ** 2))
        if y:
            br_pub += 2.0
            nll_pub_inf = True
    return {"nll": nll, "nll_pub": math.inf if nll_pub_inf else 0.0, "brier": br, "brier_pub": br_pub}


def pits(truth: dict, draws: list[dict], rng: np.random.Generator) -> dict:
    from hospitalos.howm2.a2 import TYPES

    out = {}
    for typ in TYPES:
        y = truth["totals"][typ]
        c = np.array([d["totals"][typ] for d in draws])
        lo, hi = float(np.mean(c < y)), float(np.mean(c <= y))
        out[typ] = lo + rng.random() * (hi - lo)
    return out


def job(arg):
    part, i = arg
    from hospitalos.howm.keys import key
    from hospitalos.howm2 import a2, space

    space.register()
    rows = []
    for ins in a2.setup(part, i):
        truth = a2.truth_state(ins)
        rng = np.random.default_rng(int(key("HOWM2", "A2", "valid", part, i, ins.tau) % (2**31)))
        d4, d5, fb4, rej4 = [], [], 0, 0
        for s in range(S):
            *_x, prov, eng, applied = a2.l4n_draw(ins, rng, 1001 + s)
            d4.append(a2.draw_summary(applied, ins))
            fb4 += prov.fallbacks
            rej4 += eng.rejected - ins.peng.rejected
            prov5, eng5, ap5 = a2.l5n_draw(ins, 1001 + s)
            d5.append(a2.draw_summary(ap5, ins))
        prng = np.random.default_rng(int(key("HOWM2", "A2", "pit", part, i, ins.tau) % (2**31)))
        rows.append({
            "part": part, "index": i, "tau": ins.tau,
            "n_elements": len(truth["elements"]), "truth_totals": truth["totals"],
            "L4N": score(truth, d4), "L5N": score(truth, d5),
            "pit_L4N": pits(truth, d4, prng), "pit_L5N": pits(truth, d5, prng),
            "mean_totals_L4N": {k: float(np.mean([d["totals"][k] for d in d4])) for k in truth["totals"]},
            "mean_totals_L5N": {k: float(np.mean([d["totals"][k] for d in d5])) for k in truth["totals"]},
            "fallbacks_L4N": fb4, "rejected_L4N": rej4,
        })
    return rows


def ks(u):
    u = np.sort(np.asarray(u))
    n = len(u)
    return float(max((np.arange(1, n + 1) / n - u).max(), (u - np.arange(n) / n).max()))


def boot(rows, f, seed, B=2000):
    by = {}
    for r in rows:
        by.setdefault((r["part"], r["index"]), []).append(f(r))
    groups = list(by.values())
    rng = np.random.default_rng(seed)
    reps = []
    for _ in range(B):
        idx = rng.integers(0, len(groups), len(groups))
        vals = [v for j in idx for v in groups[j]]
        reps.append(float(np.mean(vals)))
    est = float(np.mean([v for g in groups for v in g]))
    reps = np.array(reps)
    return {"mean": est, "ci95": [float(np.quantile(reps, 0.025)), float(np.quantile(reps, 0.975))]}


def main() -> int:
    from hospitalos.howm.keys import key
    from hospitalos.howm2.a2 import TYPES

    with get_context("fork").Pool(4) as pool:
        rows = [r for rs in pool.map(job, JOBS) for r in rs]
    seed = int(key("HOWM2", "A2", "bootstrap") % (2**31))
    out = {"n_instants": len(rows), "S": S}
    for sysn in ("L4N", "L5N"):
        no = boot(rows, lambda r, s=sysn: r[s]["nll_pub"] - r[s]["nll"], seed)
        nob = boot(rows, lambda r, s=sysn: r[s]["brier_pub"] - r[s]["brier"], seed)
        out[f"N_o_{sysn}"] = {**no, "pass": bool(no["ci95"][0] > 0),
                              "instants_with_pending": int(sum(math.isinf(r[sysn]["nll_pub"]) for r in rows)),
                              "note": "literal rule: point mass on S_pub has infinite NLL whenever a pending event exists (degenerate, addendum A2-1 s.3)"}
        out[f"N_o_prime_{sysn}"] = {**nob, "pass": bool(nob["ci95"][0] > 0)}
    n = len(rows)
    thr = max(0.02, 1.63 / math.sqrt(n))
    out["N_a"] = {}
    for typ in TYPES:
        row = {"n": n, "threshold": thr, "truth_total": int(sum(r["truth_totals"][typ] for r in rows)),
               "mean_pred_L4N": float(np.sum([r["mean_totals_L4N"][typ] for r in rows])),
               "mean_pred_L5N": float(np.sum([r["mean_totals_L5N"][typ] for r in rows]))}
        for sysn in ("L4N", "L5N"):
            D = ks([r[f"pit_{sysn}"][typ] for r in rows])
            row[sysn] = {"KS_D": D, "pass": bool(D <= thr)}
        row["status"] = ("pass" if row["L4N"]["pass"] else
                         ("fail (L5-N fails too: test limitation)" if not row["L5N"]["pass"] else "fail"))
        out["N_a"][typ] = row
    out["fallbacks_L4N"] = int(sum(r["fallbacks_L4N"] for r in rows))
    out["rejected_L4N"] = int(sum(r["rejected_L4N"] for r in rows))
    out["stop"] = not (out["N_o_L4N"]["pass"] and out["N_o_prime_L4N"]["pass"])
    out["rows"] = rows
    (ROOT / "evidence/howm2/VALIDATION_L4N.json").write_text(json.dumps(out, indent=1, default=float) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
