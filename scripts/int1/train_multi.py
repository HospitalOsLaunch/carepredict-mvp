#!/usr/bin/env python3
"""Run several W seeds (or runs) in parallel inside ONE ledgered command (process group counted once in wall,
CPU of all descendants summed). Each child is train_w.py with the same --budget; one OpenMP thread each.

    train_multi.py --runs RUN1,RUN2,RUN3 --seeds 0,1,2 -- <common train_w.py args>"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
i = sys.argv.index("--")
opts = dict(zip(sys.argv[1:i:2], sys.argv[2:i:2]))
rest = sys.argv[i + 1:]
runs, seeds = opts["--runs"].split(","), opts["--seeds"].split(",")
procs = [subprocess.Popen([sys.executable, str(ROOT / "scripts/int1/train_w.py"), "--run", r, "--seed", s, *rest]) for r, s in zip(runs, seeds)]
codes = [p.wait() for p in procs]
print({"runs": runs, "exit_codes": codes})
sys.exit(max(codes))
