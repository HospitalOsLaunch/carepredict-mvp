"""Smoke on DEV: adapted R1 (and F) with decisions beyond 192 h (H0 = 72 h, 7 daily decisions, Md = 2)."""
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))
from hospitalos.howmint import world as W, loop as L, planners as PL
sp = W.episode(W.structure("INT_DEV", 777, 2), 0)
pre = L.prefix(sp, 72)
for kind in ("R1", "F"):
    t = time.time()
    r = L.closed_loop(sp, pre, 1, PL.sim_policy(kind, 2, 24), 7, 24, 168)
    print(kind, "ok", r["choices"], round(time.time() - t, 1), flush=True)
