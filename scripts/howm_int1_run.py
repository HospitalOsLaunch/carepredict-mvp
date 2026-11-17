#!/usr/bin/env python3
"""Budgeted runner for HOWM-INT-1 (decision n.9). NEW ledger evidence/howm_int1/LEDGER_INT1.jsonl.

Derived from the frozen B runner (scripts/howm2_b_budget_run.py, not modified): its run() is re-compiled
with the decision check replaced (decision_9 required) and its globals re-pointed to the new ledger.
Envelope: 259 200 s cumulative WALL (sum of main-command durations; a process group launched by one
command counts once in wall, the CPU of all its descendants is summed), 288 CPU-hours (1 036 800 s,
checked before launch), 540 s per command, 0 EUR, local CPU only. The B ledger and its remainder are
neither consumed nor reset.

    python3 scripts/howm_int1_run.py --genesis
    python3 scripts/howm_int1_run.py --note <kind> --lot <lot> --label L --json f.json
    python3 scripts/howm_int1_run.py --lot INT.X --label L -- <venv>/bin/python script.py ...
    python3 scripts/howm_int1_run.py --status
"""

import inspect
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import howm2_b_budget_run as R  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CEILING_WALL_S = 259200.0
CEILING_CPU_S = 288 * 3600.0
H = 3600.0
LOTS = {  # initial allocation (mandate s.2); reallocatable inside the total by a documented note
    "INT.L0": 3 * H,  # resumption, architecture, engine, tests, cost pilot
    "INT.DATA": 18 * H,
    "INT.LEARN": 30 * H,
    "INT.EVAL": 12 * H,
    "INT.REST": 2 * H,
    "INT.RESERVE": 7 * H,
}
R.LEDGER = ROOT / "evidence/howm_int1/LEDGER_INT1.jsonl"
R.LOGS = ROOT / "evidence/howm_int1/runlogs"
R.CEILING_S = R.COMMON_CEILING_S = CEILING_WALL_S
R.LOT_CAPS = dict(LOTS)
R.AUTHORISED_LOTS = set(LOTS)
R.TRANCHE_CEILING_S = {"INT": CEILING_WALL_S}


def _caps_from_ledger() -> None:
    """Apply documented reallocations ('reallocation' notes carry the full new caps)."""
    for r in R.base.read_ledger(R.LEDGER):
        if r.get("kind") == "reallocation":
            caps = (r.get("payload") or {}).get("lot_caps")
            if caps:
                assert abs(sum(caps.values()) - CEILING_WALL_S) < 1e-6, "reallocation must keep the total"
                R.LOT_CAPS.clear()
                R.LOT_CAPS.update({k: float(v) for k, v in caps.items()})
                R.AUTHORISED_LOTS.clear()
                R.AUTHORISED_LOTS.update(caps)


_src = inspect.getsource(R.run)
_old = '''    if not any(r.get("kind") == "decision_6" for r in records) or (
        lot.startswith("BF2.") and not any(r.get("kind") == "decision_7" for r in records)
    ):'''
_new = '''    if not any(r.get("kind") == "decision_9" for r in records) or sum(
        float(r.get("cpu_seconds", 0.0) or 0.0) for r in records
    ) >= INT_CPU_CEILING:'''
assert _src.count(_old) == 1, "runner derivation: decision check not found"
_ns = R.__dict__
_ns["INT_CPU_CEILING"] = CEILING_CPU_S
exec(compile(_src.replace(_old, _new), "<howm_int1 derived run>", "exec"), _ns)  # noqa: S102


def genesis() -> dict:
    if R.base.read_ledger(R.LEDGER):
        raise R.base.LedgerError("INT-1 ledger already started")
    R.LEDGER.parent.mkdir(parents=True, exist_ok=True)
    b = R.base.read_ledger(ROOT / "evidence/howm2_bfrag/BUDGET_LEDGER_HOWM2_B.jsonl")
    return R.base.append(R.LEDGER, {
        "kind": "genesis", "at_utc": datetime.now(UTC).isoformat(), "lot": "INT.L0",
        "label": "HOWM-INT-1 ledger genesis (decision n.9)", "decision": "docs/howm2/HOWM2_DECISION_9.json",
        "ceiling_wall_s": CEILING_WALL_S, "ceiling_cpu_s": CEILING_CPU_S, "lot_caps": LOTS,
        "b_ledger_terminal_sha256_cited_not_credited": b[-1].get("record_sha256"),
        "b_ledger_remaining_not_consumed_s": round(11400.0 - sum(float(r.get("wall_seconds", 0) or 0) for r in b), 3),
        "wall_seconds": 0.0})


R.genesis = genesis

_append_unlocked = R.base.append


def _append_locked(path, record):
    """Concurrent commands are allowed (each counted): every ledger append is serialised by an fcntl lock
    (incident of line 38, see LEDGER_INT1.broken_at_line38.jsonl)."""
    import fcntl

    with open(path.with_name(".ledger.lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            R.base.read_ledger = _read_unlocked  # base.append re-reads the ledger: already under the exclusive lock
            try:
                return _append_unlocked(path, record)
            finally:
                R.base.read_ledger = _read_locked
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


R.base.append = _append_locked
_read_unlocked = R.base.read_ledger


def _read_locked(path):
    """Readers take a shared lock so that they never see a half-written line (incident: JSONDecodeError)."""
    import fcntl

    if not Path(path).exists():
        return _read_unlocked(path)
    with open(Path(path).with_name(".ledger.lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_SH)
        try:
            return _read_unlocked(path)
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


R.base.read_ledger = _read_locked

if __name__ == "__main__":
    if R.LEDGER.exists():
        _caps_from_ledger()
    raise SystemExit(R.main())
