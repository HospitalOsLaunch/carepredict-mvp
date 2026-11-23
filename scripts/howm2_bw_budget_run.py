#!/usr/bin/env python3
"""Budget runner for decision n.8 (B-FRAG 2 closure + action-consequence learning pilot).

Derived wrapper: the frozen B-FRAG 2 runner (scripts/howm2_b_budget_run.py, hashed in FREEZE2_BFRAG2)
is imported, never modified. Same ledger, same common ceiling (11 400 s, no reset), same 540-s
per-command limit; adds the BW.* lots (allocation recorded in decision_8 before any new measurement)
and refuses them unless a 'decision_8' record exists."""

import sys
from datetime import UTC, datetime  # noqa: F401
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import howm2_b_budget_run as R  # noqa: E402

BW_CAPS = {  # decision n.8 allocation of the verified balance 2636.728 s (see HOWM2_DECISION_8.json)
    "BW.CLOSE": 40.0,
    "BW.STAB": 200.0,
    "BW.DATA": 330.0,
    "BW.LEARN": 400.0,
    "BW.EVAL": 1250.0,  # 1100 + 150 s from the unallocated margin (note eval_margin, before any comparison)
    "BW.REST": 360.0,
}
R.LOT_CAPS.update(BW_CAPS)
R.AUTHORISED_LOTS |= set(BW_CAPS)
R.TRANCHE_CEILING_S["BW"] = R.COMMON_CEILING_S
_orig_run = R.run


def run(command: list[str], lot: str, label: str, test: bool) -> int:
    if lot.startswith("BW."):
        records = R.base.read_ledger(R.LEDGER)
        if not any(r.get("kind") == "decision_8" for r in records):
            R._refuse("refused", lot, label, command, "decision_8_not_recorded")
            print("[howm2-bw] decision_8 not recorded: refused", file=sys.stderr)
            return 4
    return _orig_run(command, lot, label, test)


R.run = run

if __name__ == "__main__":
    raise SystemExit(R.main())
