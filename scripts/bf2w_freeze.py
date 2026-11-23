#!/usr/bin/env python3
"""Decision n.8: freeze of the pilot before the single final evaluation campaign (VAL descriptive of the
W ensemble computed here; no evaluation data exists yet)."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import bf2w_models as M  # noqa: E402

EV = ROOT / "evidence/howm2_bfrag2w"
assert not list((EV / "runs/eval").glob("*.json")) if (EV / "runs/eval").exists() else True, "evaluation data already exists"
ld = json.loads((EV / "LEARN_D.json").read_text())
lw = json.loads((EV / "LEARN_W.json").read_text())
val = M.load_val()
nets = [M.load_w(s) for s in (0, 1, 2)]
P = np.mean([M.w_predict_costs(n, nm, val) for n, nm in nets], 0)
idx = {id(v): i for i, v in enumerate(val)}
fn = lambda v: P[idx[id(v)]]  # noqa: E731
files = ["docs/howm2/bfrag/PROTOCOLE_PILOTE_W.md", "src/hospitalos/bfrag2w/core_w.py", "src/hospitalos/bfrag2w/__init__.py", "scripts/bf2w_data.py",
         "scripts/bf2w_models.py", "scripts/bf2w_analyse.py", "scripts/bfrag2_lib.py", "tests/bfrag2w/test_pilot.py", "scripts/howm2_bw_budget_run.py",
         "evidence/howm2_bfrag2w/LEARN_D.json", "evidence/howm2_bfrag2w/LEARN_W.json"] + sorted(str(p.relative_to(ROOT)) for p in (EV / "models").glob("*"))
d = {"freeze": "PILOT W freeze before the single final evaluation campaign", "status": "PROTOTYPE_UNVALIDATED; clinical_validation=false; G2=NO-GO",
     "D_selected": ld["selected"], "W_seeds": [0, 1, 2], "W_main_system": "ensemble (mean predicted plan cost) of the 3 seeds at their VAL-selected checkpoints",
     "W_val_ensemble": {"val_decision_loss": M.decision_loss(val, fn), "val_effect_rmse": M.effect_rmse(val, fn)},
     "D_val": {k: ld["configs"][ld["selected"]][k] for k in ("val_decision_loss", "val_effect_rmse")},
     "W_val_seeds": [{"seed": x["seed"], "selected_epoch": x["selected_epoch"], "val": x["selected_val"], "stop": x["stop"]} for x in lw],
     "eval_partition": "BF2W_CONF", "eval_structures": 16, "episodes": 3, "E": 12, "Md": 32, "eval_futures": "r = 1..12 (truth provider of each new episode)",
     "primary": "W - D decision gain, paired 95 % CI, cluster bootstrap over structures (B=2000, seed 20261117)", "min_structures": 10,
     "files_sha256": {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in files}}
(EV / "FREEZE_PILOT.json").write_text(json.dumps(d, indent=1) + "\n")
print(json.dumps({k: v for k, v in d.items() if k != "files_sha256"}, indent=1))
