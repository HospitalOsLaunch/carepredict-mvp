"""Smoke + cost: F and R1 adapted planners in closed loop (2 units, 2 decisions, Md=4)."""
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))
from hospitalos.howmint import world as W, loop as L, planners as PL
sp = W.episode(W.structure("INT_PILOT", 0, 2), 1)
pre = L.prefix(sp, 48)
for kind in ("R1", "F"):
    tim = []
    t = time.time()
    r = L.closed_loop(sp, pre, 1, PL.sim_policy(kind, 4, 24, tim), 2, 24, 48)
    print(kind, "wall", round(time.time() - t, 1), "decision cpu", [round(x, 1) for x in tim], r["choices"], r["wait_patient_min"], flush=True)
