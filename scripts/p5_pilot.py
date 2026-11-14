#!/usr/bin/env python3
"""P5.2 — timed pilot on DEVELOPMENT parents (P5-PROTO-2 § 10), with identity and stop rules.

Before anything is generated: the effective commitment (last ``commitment`` record of the P5
ledger) is verified against the sources, the sealed seeds and the v6 engine, and the running
interpreter's dependency freeze must be an approved one. Each run writes into
evidence/decision_support/p5/pilot/runs/<run_id>/; the initial E0 pilot (pilot_parents.jsonl)
is kept untouched. Fits are NOT part of this script (scikit-learn: D4 + explicit authorisation).

    python -I scripts/p5_pilot.py --partition P5a_dev --structures 2 --parents 10 --k 3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import p5_budget_run as runner  # noqa: E402

from hospitalos.decision_support.planner import Settings  # noqa: E402
from hospitalos.decision_support.snapshot import load_profile  # noqa: E402
from hospitalos.p5 import integrity  # noqa: E402
from hospitalos.p5.pilot import PilotStop, ResumeRefused, run_identity, run_pilot, running_environment  # noqa: E402

P5 = ROOT / "evidence" / "decision_support" / "p5"
DEV_PARTITIONS = {"P5a_dev", "P5b_train", "P5b_val"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--partition", default="P5a_dev")
    ap.add_argument("--structures", type=int, default=2)
    ap.add_argument("--parents", type=int, default=10)
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args()
    if args.partition not in DEV_PARTITIONS:
        print(f"refused: {args.partition} is not a development partition", file=sys.stderr)
        return 2
    try:
        commitment = integrity.verify(integrity.effective_commitment())
    except integrity.IntegrityError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 3
    env = running_environment()
    records = runner.base.read_ledger(runner.LEDGER)
    if env["freeze_sha256"] not in runner.approved_freezes(records):
        print(f"refused: environment not approved ({env['freeze_sha256']})", file=sys.stderr)
        return 4
    seeds = json.loads((P5 / "SEEDS_SEALED.json").read_text())["partitions"][args.partition][: args.structures]
    pilot_sha = hashlib.sha256((ROOT / "src/hospitalos/p5/pilot.py").read_bytes()
                               + (ROOT / "scripts/p5_pilot.py").read_bytes()).hexdigest()
    identity = run_identity(commitment, args.partition, seeds, args.parents, args.k, ("R1", "R2"), env, pilot_sha)
    try:
        summary = run_pilot(out_dir=P5 / "pilot", identity=identity, seeds=seeds,
                            profile=load_profile(), settings=Settings.default())
    except (PilotStop, ResumeRefused) as error:
        print(f"STOP: {error}", file=sys.stderr)
        return 6
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
