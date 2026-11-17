#!/usr/bin/env python3
"""B-FRAG freeze before generating BFRAG_CONF (PROTOCOLE_BFRAG s.9): code, design, protocol, analysis,
selection (competitors, alert thresholds); technical version id with an explicit status."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evidence/howm2_bfrag"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main() -> int:
    if (EV / "runs/CONF_D2").exists():
        raise SystemExit("CONF already started: freeze refused")
    tune = json.loads((EV / "TUNE_TUNE_D2.json").read_text())
    if not tune["validity"]["V2_V4_pass"]:
        raise SystemExit("retained design does not pass V2-V4")
    files = sorted([*(ROOT / "src/hospitalos/bfrag").glob("*.py"), *(ROOT / "scripts").glob("bfrag*.py"),
                    ROOT / "src/hospitalos/howm2/nowcast.py", ROOT / "src/hospitalos/howm2/filter.py",
                    ROOT / "src/hospitalos/howm2/ladder.py", ROOT / "scripts/howm2_decision.py", ROOT / "scripts/howm_eval.py",
                    ROOT / "docs/howm2/bfrag/PROTOCOLE_BFRAG.md", ROOT / "docs/howm2/bfrag/DESIGN_D2.json", ROOT / "tests/bfrag/test_bfrag.py"])
    out = {"freeze": "B-FRAG / G0-v2-BFRAG-D2",
           "status": "TECHNICAL FREEZE ONLY (integrity of the benchmark version); scientific results pending CONF; not a scientific pass",
           "retained_design": "D2 (TUNE iteration 1 of at most 3; first to satisfy V1-V4)",
           "tune_validity": tune["validity"], "selection": tune["selection_if_retained"],
           "conf_partition": "BFRAG_CONF", "conf_size": 96, "conf_keys": "key('HOWM1','BFRAG_CONF',i), runtime registration, never generated before this freeze",
           "M": 8, "E": 8, "files_sha256": {str(p.relative_to(ROOT)): sha(p) for p in files}}
    body = json.dumps(out, indent=1, sort_keys=True)
    out["self_sha256"] = hashlib.sha256(body.encode()).hexdigest()
    (EV / "FREEZE_BFRAG.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"self_sha256": out["self_sha256"], "selection": {k: v for k, v in out["selection"].items() if k != "alert_thresholds"}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
