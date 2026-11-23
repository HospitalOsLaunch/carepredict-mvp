#!/usr/bin/env python3
"""HOWM-2 A5 instrumentation: per-family TRAIN and VAL losses (forward pass only, torch.no_grad)
for best.pt and last.pt of the six R1 runs. TRAIN = training origins of TRAIN 0-31; VAL = all VAL
origins. Read-only on HOWM-1 checkpoints and results."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hospitalos.howm import ckpt  # noqa: E402
from hospitalos.howm import corpus as C  # noqa: E402
from hospitalos.howm.b0 import B0Params  # noqa: E402
from hospitalos.howm.train import RUNS, evaluate_loss, new_model  # noqa: E402

torch.set_num_threads(4)
EV = C.EVID


def main() -> int:
    t0 = time.time()
    b0 = B0Params.from_json(json.loads((EV / "B0_PARAMS.json").read_text()))
    sc = json.loads((EV / "LOSS_SCALES.json").read_text())["s_f"]
    tr = [C.load("TRAIN", i) for i in range(32)]
    va = [C.load("VAL", i) for i in range(12)]
    trp = [(d["data"], H) for d in tr for H in sorted(d["data"].origins)]
    vap = [(d["data"], H) for d in va for H in sorted(d["data"].origins)]
    out = {"n_train_origins": len(trp), "n_val_origins": len(vap), "scales": sc, "runs": {}}
    for d in sorted(RUNS.iterdir()):
        st = json.loads((d / "state.json").read_text())
        kind, lr, seed = st["config"]["kind"], st["config"]["lr"], st["config"]["seed"]
        row = {}
        for name in ("best", "last"):
            obj = ckpt.load_verified(d / f"{name}.pt", st[f"{name}_sha256"])
            m = new_model(kind, b0, seed)
            m.load_state_dict(obj["model"])
            m.eval()
            row[name] = {"TRAIN": evaluate_loss(m, kind, trp, sc), "VAL": evaluate_loss(m, kind, vap, sc),
                         "state": json.loads(obj["state_json"])}
        out["runs"][d.name] = row
        print(d.name, round(time.time() - t0, 1), flush=True)
    out["seconds"] = time.time() - t0
    (ROOT / "evidence/howm2/INSTR_LOSSES.json").write_text(json.dumps(out, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
