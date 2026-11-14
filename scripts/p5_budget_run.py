#!/usr/bin/env python3
"""Budgeted runner for P5 (P5-PROTO-2 § 10), separate from the P0-P4 ledger (stdlib only).

Ceiling 1200 s cumulative wall time, 30 s per command, per-lot caps, 0 EUR. Hash-chained,
anchored, append-only ledger evidence/decision_support/p5/BUDGET_LEDGER_P5.jsonl whose genesis
record cites the P0-P4 terminal. Never reset. Only lots explicitly authorised by the user can
run (currently P5.0-P5.2: implementation and pilot). Every command record carries the Python
version and the dependency-freeze fingerprint of the interpreter environment used.

    python3 scripts/p5_budget_run.py --genesis
    python3 scripts/p5_budget_run.py --note commitment --label E0 --json file.json
    python3 scripts/p5_budget_run.py --lot P5.1 --label "tests" -- <venv>/bin/python -m pytest ...
    python3 scripts/p5_budget_run.py --status
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_budget_run as base  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "evidence" / "decision_support" / "p5" / "BUDGET_LEDGER_P5.jsonl"
LOGS = ROOT / "evidence" / "decision_support" / "p5" / "runlogs"
P04_LEDGER = ROOT / "evidence" / "decision_support" / "BUDGET_LEDGER.jsonl"
P04_TERMINAL = "9056a4a1052d0ab1deb6be7a6befa37704b61d05a43c1088187c071811c8b973"
CEILING_S = 1200.0
PER_COMMAND_S = 30.0
LOT_CAPS = {
    "P5.0": 30.0,
    "P5.I": 60.0,
    "P5.1": 130.0,
    "P5.2": 40.0,
    "P5.3": 330.0,
    "P5.4": 470.0,
    "P5.5": 90.0,
    "RESERVE": 50.0,
}
AUTHORISED_LOTS = {"P5.0", "P5.1", "P5.2"}  # user authorisation of 2026-11-14 (D11-i)
DEFAULT_VENV = Path(
    os.environ.get(
        "P5_VENV",
        "/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad/venv311",
    )
)
D3_FREEZE_SHA256 = "bf54098158fbda95e3ce8e9db9ec68097f73b5390d4639fa39c240538880b6da"


def environment(venv: Path = DEFAULT_VENV) -> dict[str, object]:
    cfg = dict(
        line.split(" = ", 1) for line in (venv / "pyvenv.cfg").read_text().splitlines() if " = " in line
    )
    lines = []
    for site in sorted(venv.glob("lib/python*/site-packages")):
        for meta in sorted(site.glob("*.dist-info/METADATA")):
            fields = {}
            for line in meta.read_text(errors="replace").splitlines():
                if not line.strip():
                    break
                if ": " in line:
                    k, v = line.split(": ", 1)
                    fields.setdefault(k, v)
            if fields.get("Name", "").lower() in {"pip", "setuptools"}:
                continue
            lines.append(f"{fields['Name']}=={fields['Version']}")
    freeze = "\n".join(sorted(lines, key=lambda x: x.split("==")[0].lower())) + "\n"
    digest = hashlib.sha256(freeze.encode()).hexdigest()
    return {
        "venv": str(venv),
        "python": cfg.get("version"),
        "freeze_sha256": digest,
        "matches_D3_freeze": digest == D3_FREEZE_SHA256,
        "packages": len(lines),
    }


def lot_used(records: list[dict[str, object]], lot: str) -> float:
    return sum(float(r.get("wall_seconds", 0.0)) for r in records if r.get("lot") == lot)  # type: ignore[arg-type]


def status() -> dict[str, object]:
    records = base.read_ledger(LEDGER)
    used = base.used_seconds(records)
    return {
        "ledger": str(LEDGER.relative_to(ROOT)),
        "records": len(records),
        "commands": sum(r.get("kind") == "command" for r in records),
        "used_wall_seconds": round(used, 3),
        "ceiling_wall_seconds": CEILING_S,
        "remaining_wall_seconds": round(max(0.0, CEILING_S - used), 3),
        "lots": {k: {"used": round(lot_used(records, k), 3), "cap": v} for k, v in LOT_CAPS.items()},
        "authorised_lots": sorted(AUTHORISED_LOTS),
    }


def genesis() -> dict[str, object]:
    if base.read_ledger(LEDGER):
        raise base.LedgerError("P5 ledger already started: genesis refused")
    p04 = base.read_ledger(P04_LEDGER)
    terminal = str(p04[-1]["record_sha256"])
    if terminal != P04_TERMINAL:
        raise base.LedgerError(f"P0-P4 terminal mismatch: {terminal}")
    return base.append(
        LEDGER,
        {
            "kind": "genesis",
            "at_utc": datetime.now(UTC).isoformat(),
            "lot": "P5.0",
            "label": "P5 ledger genesis",
            "protocol": "P5-PROTO-2",
            "decisions": "docs/decision_support/P5_DECISIONS_v2.json",
            "p0_p4_terminal_sha256": terminal,
            "p0_p4_records": len(p04),
            "p0_p4_used_wall_seconds": round(base.used_seconds(p04), 3),
            "ceiling_wall_seconds": CEILING_S,
            "per_command_seconds": PER_COMMAND_S,
            "spend_eur": 0,
            "lot_caps": LOT_CAPS,
            "authorised_lots": sorted(AUTHORISED_LOTS),
            "wall_seconds": 0.0,
        },
    )


def note(kind: str, label: str, lot: str, payload: dict[str, object]) -> dict[str, object]:
    base.read_ledger(LEDGER)
    return base.append(
        LEDGER,
        {"kind": kind, "at_utc": datetime.now(UTC).isoformat(), "lot": lot, "label": label, "payload": payload, "wall_seconds": 0.0},
    )


def run(command: list[str], lot: str, label: str) -> int:
    if lot not in AUTHORISED_LOTS:
        print(f"[p5-budget] lot {lot} is not authorised: refused", file=sys.stderr)
        return 4
    records = base.read_ledger(LEDGER)
    if not records or records[0].get("kind") != "genesis":
        raise base.LedgerError("P5 ledger has no genesis record")
    used = base.used_seconds(records)
    remaining = CEILING_S - used
    lot_remaining = LOT_CAPS[lot] - lot_used(records, lot)
    if remaining <= 0 or lot_remaining <= 0:
        base.append(
            LEDGER,
            {
                "kind": "stop",
                "at_utc": datetime.now(UTC).isoformat(),
                "lot": lot,
                "label": label,
                "refused_command": command,
                "reason": "global_ceiling_reached" if remaining <= 0 else "lot_cap_reached",
                "wall_seconds": 0.0,
            },
        )
        print(json.dumps(status()), file=sys.stderr)
        return 3
    env_info = environment()
    timeout = min(PER_COMMAND_S, remaining, lot_remaining)
    LOGS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = LOGS / f"{len(records) + 1:03d}_{lot}_{stamp}.log"
    now = datetime.now(UTC).isoformat()
    started = time.monotonic()
    timed_out = False
    with log_path.open("wb") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            code = process.wait()
    wall = time.monotonic() - started
    record = base.append(
        LEDGER,
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
            "log": str(log_path.relative_to(ROOT)),
            "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
            "environment": env_info,
        },
    )
    sys.stdout.write(log_path.read_text(errors="replace"))
    st = status()
    print(
        f"\n[p5-budget] #{record['sequence']} {lot} '{label}': {wall:.2f}s exit={code}"
        f"{' TIMEOUT' if timed_out else ''} | lot {lot} {st['lots'][lot]['used']}/{LOT_CAPS[lot]}s"  # type: ignore[index]
        f" | total {st['used_wall_seconds']}/{CEILING_S}s, remaining {st['remaining_wall_seconds']}s"
    )
    return 124 if timed_out else code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lot", default="")
    parser.add_argument("--label", default="")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--genesis", action="store_true")
    parser.add_argument("--note", default="")
    parser.add_argument("--json", default="")
    parser.add_argument("--env", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.status:
        print(json.dumps(status(), indent=1))
        return 0
    if args.env:
        print(json.dumps(environment(), indent=1))
        return 0
    if args.genesis:
        print(json.dumps(genesis(), indent=1))
        return 0
    if args.note:
        payload = json.loads(Path(args.json).read_text()) if args.json else {}
        print(json.dumps(note(args.note, args.label, args.lot or "P5.0", payload), indent=1))
        return 0
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("missing command after --")
    return run(command, args.lot, args.label)


if __name__ == "__main__":
    raise SystemExit(main())
