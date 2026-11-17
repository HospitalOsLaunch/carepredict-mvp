#!/usr/bin/env python3
"""Decision n.8: smoke test of the frozen evaluation + analysis path on DEV structures (2 x 3 episodes, E=1, Md=2),
written to a temporary directory. No BF2W_CONF data is generated; frozen code is used unmodified (monkeypatched paths)."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import bf2w_analyse as A  # noqa: E402
import bf2w_data as D  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="bf2w_smoke_", dir="/tmp"))
(tmp / "runs/eval").mkdir(parents=True)
orig = D.origin
D.origin = lambda part, s, e: orig("BF2_DEV", s, e)
D.EV = tmp
for s in (0, 1):
    for e in range(3):
        D.job_eval((s, e, 1, 2))
fr = json.loads((ROOT / "evidence/howm2_bfrag2w/FREEZE_PILOT.json").read_text())
fr["eval_structures"] = 2
(tmp / "FREEZE_PILOT.json").write_text(json.dumps(fr))
for f in ("LEARN_D.json", "LEARN_W.json"):
    shutil.copy(ROOT / "evidence/howm2_bfrag2w" / f, tmp / f)
A.EV = tmp
A.MIN_STRUCT = 1
A.main()
r = json.loads((tmp / "RESULTS_PILOT_W.json").read_text())
print("SMOKE_OK", r["status"], sorted(r), {k: round(v, 3) for k, v in r["costs"]["response_seconds_per_decision"].items()})
shutil.rmtree(tmp)
