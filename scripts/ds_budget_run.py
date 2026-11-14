#!/usr/bin/env python3
"""Budgeted runner for the P0-P4 decision-support reprise (stdlib only).

Every test/fixture command of the reprise goes through this runner. It enforces the
accepted ceilings (600 s cumulative wall time, 30 s per command), appends a
hash-chained record to an append-only ledger and never resets it. When the ceiling is
reached it refuses to start, writes a STOP record and exits with code 3. A command that
exceeds its timeout is killed with its whole process group: nothing is left running.

    python scripts/ds_budget_run.py --lot P2 --label "unit tests" -- python -m pytest ...
    python scripts/ds_budget_run.py --status
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "evidence" / "decision_support" / "BUDGET_LEDGER.jsonl"
DEFAULT_LOGS = ROOT / "evidence" / "decision_support" / "runlogs"
CUMULATIVE_LIMIT_S = 600.0
PER_COMMAND_LIMIT_S = 30.0
GENESIS = "0" * 64


class LedgerError(RuntimeError):
    pass


def _digest(record: dict[str, object]) -> str:
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def read_ledger(path: Path) -> list[dict[str, object]]:
    """Read and verify the hash chain. A broken chain is a hard stop, never a reset."""
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    previous = GENESIS
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("previous_sha256") != previous or record.get("record_sha256") != _digest(
            record
        ):
            raise LedgerError(f"Ledger chain broken at line {number}: refusing to run")
        previous = str(record["record_sha256"])
        records.append(record)
    return records


def used_seconds(records: list[dict[str, object]]) -> float:
    return sum(float(r.get("wall_seconds", 0.0)) for r in records)  # type: ignore[arg-type]


def append(path: Path, record: dict[str, object]) -> dict[str, object]:
    records = read_ledger(path)
    record["sequence"] = len(records) + 1
    record["previous_sha256"] = str(records[-1]["record_sha256"]) if records else GENESIS
    record["record_sha256"] = _digest(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def status(path: Path, limit: float = CUMULATIVE_LIMIT_S) -> dict[str, object]:
    records = read_ledger(path)
    used = used_seconds(records)
    return {
        "ledger": str(path),
        "commands": sum(r.get("kind") == "command" for r in records),
        "used_wall_seconds": round(used, 3),
        "limit_wall_seconds": limit,
        "remaining_wall_seconds": round(max(0.0, limit - used), 3),
        "stopped": any(r.get("kind") == "stop" for r in records) or used >= limit,
    }


def run(
    command: list[str],
    *,
    lot: str,
    label: str,
    ledger: Path = DEFAULT_LEDGER,
    logs: Path = DEFAULT_LOGS,
    limit: float = CUMULATIVE_LIMIT_S,
    per_command: float = PER_COMMAND_LIMIT_S,
) -> int:
    records = read_ledger(ledger)
    used = used_seconds(records)
    remaining = limit - used
    now = datetime.now(UTC).isoformat()
    if remaining <= 0 or any(r.get("kind") == "stop" for r in records):
        append(
            ledger,
            {
                "kind": "stop",
                "at_utc": now,
                "lot": lot,
                "label": label,
                "refused_command": command,
                "reason": "cumulative_budget_exhausted",
                "used_wall_seconds": round(used, 3),
                "wall_seconds": 0.0,
            },
        )
        print(json.dumps(status(ledger, limit)), file=sys.stderr)
        return 3
    timeout = min(per_command, remaining)
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = logs / f"{len(records) + 1:03d}_{lot}_{stamp}.log"
    started = time.monotonic()
    timed_out = False
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, start_new_session=True
        )
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            code = process.wait()
    wall = time.monotonic() - started
    record = append(
        ledger,
        {
            "kind": "command",
            "at_utc": now,
            "lot": lot,
            "label": label,
            "command": command,
            "timeout_seconds": round(timeout, 3),
            "timed_out": timed_out,
            "exit_code": code,
            "wall_seconds": round(wall, 3),
            "log": str(log_path.relative_to(ROOT))
            if log_path.is_relative_to(ROOT)
            else str(log_path),
            "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        },
    )
    sys.stdout.write(log_path.read_text(errors="replace"))
    summary = status(ledger, limit)
    print(
        f"\n[budget] #{record['sequence']} {lot} '{label}': {wall:.2f}s exit={code}"
        f"{' TIMEOUT' if timed_out else ''} | used {summary['used_wall_seconds']}s"
        f" / {limit}s, remaining {summary['remaining_wall_seconds']}s"
    )
    return 124 if timed_out else code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lot", default="P?")
    parser.add_argument("--label", default="")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.status:
        print(json.dumps(status(DEFAULT_LEDGER), indent=2))
        return 0
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("missing command after --")
    return run(command, lot=args.lot, label=args.label)


if __name__ == "__main__":
    raise SystemExit(main())
