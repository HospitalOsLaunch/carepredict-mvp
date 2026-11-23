#!/usr/bin/env python3
"""HOWM-INT-1 freeze before the single final campaign: systems selected on VAL, models, normalisations, engine,
distribution, actions, planner, panel sizes, futures and analysis (hashes). No test data exists before this."""
import glob, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")
EV = ROOT / "evidence/howm_int1"
assert not (S / "int1_eval").exists() or not any((S / "int1_eval").rglob("*.json")), "final evaluation data already exists"
systems = json.loads((EV / "SYSTEMS_CANDIDATES.json").read_text())
vp = json.loads((EV / "VAL_PANEL.json").read_text())
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()  # noqa: E731
files = sorted(set(glob.glob("src/hospitalos/howmint/*.py") + glob.glob("scripts/int1/*.py") + ["scripts/howm_int1_run.py", "docs/howm_int1/PROTOCOLE_INT1.md"]))
models = {}
for runs in list(systems["W"].values()):
    for r in runs:
        for f in ("best.pt", "norm.npz", "config.json"):
            models[f"int1_runs/{r}/{f}"] = sha(S / "int1_runs" / r / f)
for d in systems["D"].values():
    p = S / "int1_runs" / d["run"] / ("best.pt" if d["kind"] == "dset" else f"{d['name']}.pkl")
    models[f"int1_runs/{d['run']}/{p.name}"] = sha(p)
fr = {"freeze": "HOWM-INT-1 final campaign freeze", "status": "PROTOTYPE_UNVALIDATED; clinical_validation=false; G2=NO-GO",
      "B_star": vp["B_star"], "W_primary": vp["W_primary"], "W_systems": systems["W"], "D_systems": systems["D"],
      "selection": {"VAL_PANEL": "evidence/howm_int1/VAL_PANEL.json", "rule": vp["rule"]},
      "panels": {"MAIN": 200, "SUB32": 32, "EXT": 96, "COMBO": 48, "SIZE12": 48}, "episodes": 3, "futures": 4, "Md": 16,
      "min_structures_main": 150, "planner": {"lookahead_h": {"2": 48, "4": 24, "8": 24, "12": 24}, "candidates": "loop.sequences", "tie": "staff-hours then index"},
      "analysis": "scripts/int1/analyse.py", "files_sha256": {f: sha(ROOT / f) for f in files}, "models_sha256": models}
(EV / "FREEZE_INT1.json").write_text(json.dumps(fr, indent=1))
print(json.dumps({k: fr[k] for k in ("B_star", "W_primary", "W_systems", "D_systems", "panels")}, indent=1))
