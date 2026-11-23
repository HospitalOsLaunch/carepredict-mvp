#!/usr/bin/env python3
"""HOWM-INT-1 propagation "selon W" (protocol s.7), descriptive, on the VAL corpus (4- and 8-unit situations).

The DEV propagation study (propagation.py) measures channels in the TRUE world with single-channel controls; those
controls change the world (no bed hold, unlimited downstream) and are not actions, so W cannot be asked about them.
Here the question asked of W is the one it can answer: for every candidate sequence of a VAL situation, the
PER-UNIT lookahead effect (wait of the unit under the sequence minus under (none, none)), true (mean over the K = 4
common futures of the corpus, engine-generated) versus predicted by the frozen primary W (W-M ensemble).
Units are split into: 'direct' (unit targeted by a staff action) and 'indirect' (every other unit, and every unit
for shared-resource actions: coordination, cleaning, transport, downstream slots), and upstream / downstream by
the topology of the generator (first half of the units feeds the second half).
D predicts only the cumulative cost (no per-unit output) and is not part of this diagnostic.
Writes evidence/howm_int1/PROPAGATION_W_VAL.json."""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import torch  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from hospitalos.howmint import data as DA  # noqa: E402
from hospitalos.howmint import models as MO  # noqa: E402

S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")
THR = 60.0  # |true effect| (patient-minutes over 24 h) above which a sign is counted


def load_w(run):
    rd = S / "int1_runs" / run
    cfg = json.loads((rd / "config.json").read_text())
    m = MO.GraphWM(cfg["d"], use_messages=cfg.get("ablate") != "no_msg", use_history=cfg.get("ablate") != "no_hist")
    m.load_state_dict(torch.load(rd / "best.pt", weights_only=False)["model"])
    m.eval()
    return m, {k: (v.item() if v.ndim == 0 else v) for k, v in np.load(rd / "norm.npz").items()}


def per_unit_pred(models, st, s, Ls):
    m = len(s["desc"])
    x = {"unit": s["unit"], "res": s["res"], "glob": s["glob"], "uu": s["uu"], "U": s["U"][:, :Ls], "R": s["R"][:, :Ls], "C": s["C"][:, :Ls],
         "desc": s["desc"], "n": s["n"], "states": np.zeros((m, 1, Ls, s["n"], 9), np.float32), "costs": np.zeros((m, 1, Ls, s["n"]), np.float32),
         "n24": np.zeros((m, 1, Ls, s["n"]))}
    t = DA.tensors(x, st)
    out = []
    with torch.no_grad():
        for mod in models:
            _sh, ch, _rh = mod(t["unit"], t["res"], t["glob"], t["ur_mask"], t["uu"], t["U"], t["R"], t["C"], t["beds"], steps=Ls)
            out.append((ch.sum(1) * st["cost_s"]).numpy())
    return np.mean(out, 0)  # [m, n]


def kind_of(sid):
    return "staff" if sid.startswith("staff_") else sid.split("_")[0]


def summarise(rows):
    if not rows:
        return {"pairs": 0}
    t = np.array([r[0] for r in rows])
    w = np.array([r[1] for r in rows])
    big = np.abs(t) >= THR
    return {"pairs": int(len(t)), "true_mean": float(t.mean()), "W_mean": float(w.mean()),
            "pearson": float(np.corrcoef(t, w)[0, 1]) if t.std() > 0 and w.std() > 0 else None,
            "pairs_true_ge_thr": int(big.sum()), "sign_agreement_true_ge_thr": float((np.sign(t[big]) == np.sign(w[big])).mean()) if big.any() else None}


def main() -> int:
    fr = json.loads((ROOT / "evidence/howm_int1/FREEZE_INT1.json").read_text())
    torch.set_num_threads(1)
    ms = [load_w(r) for r in fr["W_systems"][fr["W_primary"]]]
    models, st = [m for m, _ in ms], ms[0][1]
    sits = [s for s in DA.situations(DA.load(S / "int1_corpus", "INT_VAL", list(range(300)))) if s["n"] in (4, 8)]
    groups = {}
    for s in sits:
        n, Ls = s["n"], DA.LOOKAHEAD_STEPS[s["n"]]
        tru = s["costs"][:, :, :Ls].sum(2).mean(1)  # [m, n]
        prd = per_unit_pred(models, st, s, Ls)
        up = set(range(max(1, n // 2)))
        for i in range(1, len(s["seqs"])):
            sid = s["seqs"][i][0]
            k = kind_of(sid)
            tgt = int(sid.split("_")[1][1:]) if k == "staff" else None
            for u in range(n):
                rel = "direct" if u == tgt else "indirect"
                pos = "upstream" if u in up else "downstream"
                d = (float(tru[i, u] - tru[0, u]), float(prd[i, u] - prd[0, u]))
                for key in (f"n{n}|{k}|{rel}|{pos}", f"all|{rel}", f"all|{k}|{rel}", f"n{n}|{rel}"):
                    groups.setdefault(key, []).append(d)
    out = {"what": "per-unit lookahead effects (24 h), true vs W (frozen primary W ensemble), VAL 4/8-unit situations",
           "situations": len(sits), "threshold_sign_pmin": THR, "W": fr["W_primary"],
           "groups": {k: summarise(v) for k, v in sorted(groups.items())}}
    (ROOT / "evidence/howm_int1/PROPAGATION_W_VAL.json").write_text(json.dumps(out, indent=1))
    for k in sorted(groups):
        if k.startswith("all|") or k.count("|") == 1:
            print(k, json.dumps(out["groups"][k]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
