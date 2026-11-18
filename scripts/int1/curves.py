"""HOWM-INT-1 data / capacity / compute curves from the recorded runs (no new training)."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")
sys.path.insert(0, str(ROOT / "src"))
out = {"W": {}, "D": {}}
for tier in (1, 2):
    for size, params in (("S", 317460), ("M", 1899540)):
        rows = []
        for s in range(3):
            d = json.loads((S / "int1_runs" / f"W_t{tier}_{size}_s{s}" / "curve.json").read_text())
            st = d["state"]
            rows.append({"seed": s, "updates": st["upd"], "samples": st["samples"], "train_seconds": round(st["train_seconds"], 1), "stopped": st["stopped"],
                         "best_upd": st["best"]["upd"], "val": st["best"]["val"],
                         "val_curve_2unit": [(x["upd"], round(x["val"]["2"]["rel_regret"], 4), round(x["val"]["2"]["effect_rmse"])) for x in d["curve"] if "val" in x]})
        out["W"][f"t{tier}_{size}"] = {"params": params, "structures": 1000 if tier == 1 else 10000, "seeds": rows}
for name in ("W_t1_S_s0_nohist", "W_t1_S_s0_nomsg"):
    st = json.loads((S / "int1_runs" / name / "curve.json").read_text())["state"]
    out["W"][name] = {"updates": st["upd"], "stopped": st["stopped"], "best_upd": st["best"]["upd"], "val": st["best"]["val"]}
for tier in (1, 2):
    for fam in ("ridge", "hgb"):
        out["D"][f"t{tier}_{fam}"] = {k: {"val": v["val"], "fit_seconds": v.get("fit_seconds"), "train_rows": v.get("train_rows")}
                                      for k, v in json.loads((S / "int1_runs" / f"D_t{tier}_{fam}" / "result.json").read_text()).items()}
    out["D"][f"t{tier}_dset"] = json.loads((S / "int1_runs" / f"D_t{tier}_dset" / "result.json").read_text())["dset"]
(ROOT / "evidence/howm_int1/CURVES.json").write_text(json.dumps(out, indent=1, default=float))
for k, v in out["W"].items():
    if "seeds" in v:
        print(k, v["params"], v["structures"], [(r["best_upd"], round(r["val"]["2"]["rel_regret"], 4), round(r["val"]["2"]["effect_rmse"]), r["train_seconds"]) for r in v["seeds"]])
