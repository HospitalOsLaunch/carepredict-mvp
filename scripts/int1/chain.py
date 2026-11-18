#!/usr/bin/env python3
"""Chain <= 540-s ledgered commands until a run stops (resumable runs) or a corpus target is reached.

    chain.py train --lot INT.LEARN --run NAME -- <train_w.py args>      (loops until curve.json state.stopped)
    chain.py corpus --part P --s1 N --lot INT.DATA -- <corpus.py args>  (loops until N files)
"""
import json
import subprocess
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")
PY = str(S / "venv_howm/bin/python")


def main() -> int:
    mode = sys.argv[1]
    i = sys.argv.index("--")
    opts = dict(zip(sys.argv[2:i:2], sys.argv[3:i:2]))
    rest = sys.argv[i + 1:]
    import os

    t0 = float(os.environ.get("CHAIN_T0", time.time()))  # start of the background slot (set by the launcher)
    deadline = float(opts.get("--deadline", "6600"))  # never start a command that could outlive the background slot
    for k in range(400):
        if time.time() - t0 > deadline:
            print("DEADLINE: chain paused cleanly (resumable)", flush=True)
            break
        if mode == "train":
            cp = S / "int1_runs" / opts["--run"] / "curve.json"
            if cp.exists() and json.loads(cp.read_text())["state"].get("stopped"):
                break
            script, label = "scripts/int1/train_w.py", f"train {opts['--run']} (cmd {k + 1})"
            args = ["--run", opts["--run"], *rest]
        elif mode == "multi":  # several runs inside one command; stop when all have stopped
            runs = opts["--runs"].split(",")
            done = []
            for r in runs:
                cp = S / "int1_runs" / r / "curve.json"
                done.append(cp.exists() and bool(json.loads(cp.read_text())["state"].get("stopped")))
            if all(done):
                break
            script, label = "scripts/int1/train_multi.py", f"train {opts['--runs']} (cmd {k + 1})"
            args = ["--runs", opts["--runs"], "--seeds", opts["--seeds"], *(["--ablates", opts["--ablates"]] if "--ablates" in opts else []),
                    *(["--inits", opts["--inits"]] if "--inits" in opts else []), "--", *rest]
        elif mode == "dset":
            cp = S / "int1_runs" / f"D_t{opts['--tier']}_dset" / "last.pt"
            script, label = "scripts/int1/train_d.py", f"train D dset tier {opts['--tier']} (cmd {k + 1})"
            args = ["--tier", opts["--tier"], "--which", "dset", *rest]
            rp = cp.with_name("result.json")  # progress written by train_d.py (no torch needed here)
            if rp.exists() and "dset" in json.loads(rp.read_text()):
                st = json.loads(rp.read_text())["dset"]
                if st.get("stopped") or st["upd"] >= int(opts.get("--max", "30000")):
                    break
        else:
            d = S / "int1_corpus" / opts["--part"]
            if d.exists() and len(list(d.glob("*.npz"))) >= int(opts["--target"]):
                break
            script, label = "scripts/int1/corpus.py", f"corpus {opts['--part']} -> {opts['--target']} (cmd {k + 1})"
            args = rest
        r = subprocess.run(["python3", "scripts/howm_int1_run.py", "--lot", opts["--lot"], "--label", label, "--", PY, script, *args],
                           cwd=ROOT, capture_output=True, text=True)
        line = [x for x in r.stdout.splitlines() if "howm2-budget]" in x]
        print(line[-1] if line else r.stdout[-500:] + r.stderr[-500:], flush=True)
        if r.returncode not in (0,):
            print("STOP: non-zero exit", r.returncode, flush=True)
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
