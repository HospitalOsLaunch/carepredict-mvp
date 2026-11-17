#!/usr/bin/env python3
"""Decision n.8 receipt diagnosis: rerun the frozen analysis, diff with the recorded RESULTS_PILOT_W.json field
by field, then restore the recorded file (no result is replaced)."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
f = ROOT / "evidence/howm2_bfrag2w/RESULTS_PILOT_W.json"
rec = f.read_bytes()
subprocess.run([sys.executable, str(ROOT / "scripts/bf2w_analyse.py")], capture_output=True)
a, b = json.loads(rec), json.loads(f.read_text())
f.write_bytes(rec)


def diff(x, y, p=""):
    if isinstance(x, dict):
        for k in sorted(set(x) | set(y)):
            if k not in x or k not in y:
                print("key", p + "/" + k)
            else:
                diff(x[k], y[k], p + "/" + k)
    elif isinstance(x, list):
        if len(x) != len(y):
            print("len", p)
        else:
            for i, (u, v) in enumerate(zip(x, y)):
                diff(u, v, f"{p}[{i}]")
    elif x != y:
        print(p, x, y)


diff(a, b)
print("restored:", f.read_bytes() == rec)
