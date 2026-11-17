"""Smoke: W planner path (untrained S model) in closed loop on 2 and 8 units."""
import sys, time, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import numpy as np, torch
from hospitalos.howmint import world as W, loop as L, data as DA, models as MO, planners as PL
S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")
sits = DA.situations(DA.load(S / "int1_corpus", "INT_TRAIN", list(range(40))))
st = DA.norm_stats(sits)
for d in (128, 320):
    m = MO.GraphWM(d); print("params d=%d" % d, MO.n_params(m))
m = MO.GraphWM(128).eval()
for n in (2, 8):
    sp = W.episode(W.structure("INT_PILOT", 3 if n == 8 else 0, n), 1)
    pre = L.prefix(sp, 48)
    tim = []
    pol = PL.model_policy(PL.w_scorer([m], st), 24 if n == 2 else 6, tim)
    t = time.time()
    r = L.closed_loop(sp, pre, 1, pol, 7 if n == 2 else 4, 24 if n == 2 else 6, 168 if n == 2 else 24)
    print(n, "wall", round(time.time() - t, 2), "decision cpu s", [round(x, 3) for x in tim], r["choices"], r["wait_patient_min"])
