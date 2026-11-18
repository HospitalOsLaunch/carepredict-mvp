#!/usr/bin/env python3
"""HOWM-INT-1 candidate systems for the VAL closed-loop panel (rule fixed before use).

D families (Ridge, HGB, DSet): the configuration AND tier with the lowest VAL relative decision regret on 2-unit
situations (offline VAL corpus), tie -> lower effect RMSE. W: tier-2 ensembles of the 3 seeds for each size
(protocol s.6), each seed at its VAL-selected checkpoint. Writes evidence/howm_int1/SYSTEMS_CANDIDATES.json."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")
cands = {}
for fam in ("ridge", "hgb"):
    for tier in (1, 2):
        p = S / "int1_runs" / f"D_t{tier}_{fam}" / "result.json"
        for name, v in json.loads(p.read_text()).items():
            if "val" in v:
                cands.setdefault(fam, []).append(((v["val"]["2"]["rel_regret"], v["val"]["2"]["effect_rmse"]), {"kind": fam, "run": f"D_t{tier}_{fam}", "name": name}))
for tier in (1, 2):
    v = json.loads((S / "int1_runs" / f"D_t{tier}_dset" / "result.json").read_text())["dset"]["best"]["val"]["2"]
    cands.setdefault("dset", []).append(((v["rel_regret"], v["effect_rmse"]), {"kind": "dset", "run": f"D_t{tier}_dset", "norm_run": "W_t1_S_s0"}))
D = {f"D_{fam}": min(c, key=lambda x: x[0])[1] for fam, c in cands.items()}
out = {"W": {"W_S": [f"W_t2_S_s{s}" for s in range(3)], "W_M": [f"W_t2_M_s{s}" for s in range(3)]}, "D": D, "Md": 16,
       "D_candidates_val": {fam: [{"key": list(k), **spec} for k, spec in c] for fam, c in cands.items()},
       "rule": "per D family: min VAL 2-unit relative regret over configurations and tiers, tie -> effect RMSE; W: tier-2 ensembles"}
(ROOT / "evidence/howm_int1/SYSTEMS_CANDIDATES.json").write_text(json.dumps(out, indent=1))
print(json.dumps({k: out[k] for k in ("W", "D")}, indent=1))
