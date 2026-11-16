#!/usr/bin/env python3
"""HOWM-2 C1 palier 1: training summary (real counts consumed, timings, train/CVAL losses per
family) and the N9' palier-2 condition evaluated on CVAL only (descriptive: palier 2 NOT authorised)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
EV = ROOT / "evidence/howm2_c1"


def main() -> int:
    from hospitalos.howm2 import c1

    runs = {}
    for s in c1.SYSTEMS:
        for N in c1.SIZES:
            for seed in c1.SEEDS:
                d = c1.run_dir(s, N, seed)
                if not (d / "state.json").exists():
                    runs[f"{s}:{N}:{seed}"] = {"status": "not_executed (C.2a N=1000: budget)"}
                    continue
                m = json.loads((d / "state.json").read_text())
                st = m["state"]
                cc = c1.consumed_check(st, N)
                runs[f"{s}:{N}:{seed}"] = {
                    "done": m["done"], "updates": st["step"], "planned_updates": cc["planned"],
                    "exact_one_pass_no_replay": cc["exact_no_replay"],
                    "establishments_consumed": cc["establishments_consumed"], "examples_origins_consumed": cc["origins_consumed"],
                    "train_seconds_logged_in_state": round(st["seconds"], 1), "best_step": st["best_step"],
                    "best_cval_total": st["best_total"],
                    "evals": [{"step": e["step"], "cval_total": e["cval_total"], "cval_means": e["cval_means"],
                               "train_means_since_last_eval": e["train_means_since_last_eval"]} for e in m["log"]]}
    n9 = {}
    for s in ("C.1", "C.2b", "C.2a"):
        v100 = [runs[f"{s}:100:{k}"].get("best_cval_total") for k in c1.SEEDS]
        v1000 = [runs[f"{s}:1000:{k}"].get("best_cval_total") for k in c1.SEEDS]
        if None in v100 or None in v1000:
            n9[s] = {"evaluable": False}
            continue
        diff = float(np.mean(v100) - np.mean(v1000))
        sd = float(np.std(v1000, ddof=1))
        n9[s] = {"cval_100_mean": float(np.mean(v100)), "cval_1000_mean": float(np.mean(v1000)), "difference": diff,
                 "seed_sd_at_1000": sd, "threshold_2sd": 2 * sd, "condition_met": bool(diff > 2 * sd)}
    man = json.loads((EV / "DATA_MANIFEST.json").read_text())
    out = {"runs": runs,
           "N9_prime_rule_verbatim": "Palier 2 : N = 10 000, 1 graine par systeme, puis 2 graines du meilleur selon CVAL. Il est lance si et seulement si, pour au moins un systeme, CVAL(100) - CVAL(1 000) > 2 x l'ecart-type entre graines a N = 1 000.",
           "N9_prime_on_CVAL_descriptive": n9, "palier_2_authorised": False,
           "data": {"shards": len(man["shards"]), "bytes": sum(e["bytes"] for e in man["shards"].values()),
                    "CTRAIN_establishments_generated": sum(e["n"] for k, e in man["shards"].items() if k.startswith("HOWM2_CTRAIN")),
                    "CVAL_establishments": sum(e["n"] for k, e in man["shards"].items() if k.startswith("HOWM2_CVAL")),
                    "episodes": "one episode per establishment"}}
    (EV / "TRAINING_SUMMARY.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"N9": n9, "data": out["data"], "runs": {k: {kk: v.get(kk) for kk in ("updates", "exact_one_pass_no_replay", "establishments_consumed", "best_step", "best_cval_total", "train_seconds_logged_in_state")} for k, v in runs.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
