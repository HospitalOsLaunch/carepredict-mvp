#!/usr/bin/env python3
"""Budgeted runner for HOWM-2 B-FRAG and C1 closure (decision n.6; derived from the C1 runner) (stdlib only). New ledger; no P0-P4 or P5 credit transferred.

Adopted accord: docs/howm1/inputs/accord/ACCORD_HOWM1_v1_1_ADOPTE.txt (decision record
docs/howm1/HOWM1_DECISION_ACCORD.json). Ceiling 21 600 s cumulative WALL time, per-lot caps,
540 s per command, 120 s per test command (--test), 0 EUR. CPU time of the child processes is
recorded separately (getrusage) and is not capped. One command at a time; the whole process
group is killed at the end (no background process survives).

    python3 scripts/howm_budget_run.py --genesis
    python3 scripts/howm_budget_run.py --note <kind> --lot <lot> --label L --json f.json
    python3 scripts/howm_budget_run.py --lot R0.TEST --test --label tests -- <venv>/bin/python -m pytest ...
    python3 scripts/howm_budget_run.py --status
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_budget_run as base  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "evidence" / "howm2_bfrag" / "BUDGET_LEDGER_HOWM2_B.jsonl"
LOGS = ROOT / "evidence" / "howm2_bfrag" / "runlogs"
H1_ANCHOR = ROOT / "evidence" / "howm1" / "BUDGET_LEDGER_HOWM1.anchor.json"
P5_TERMINAL = "561264d5a7e2a6cb952dccfa7aa1b742cb689461a7b0a6ab6a2f6eee7d1cb420"
CEILING_S = 11400.0
PER_COMMAND_S = 540.0
PER_TEST_COMMAND_S = 120.0
LOT_CAPS = {  # decision n.6, fixed before any B-FRAG measurement (pilot included)
    "CLOSE.C1": 300.0,
    "BF.PREP": 600.0,
    "BF.TEST": 400.0,
    "BF.PILOT": 400.0,
    "BF.TUNE": 3000.0,
    "BF.CONF": 3000.0,
    "BF.ANAL": 400.0,
    "BF.REST": 700.0,
    # B-FRAG 2 (decision n.7), caps fixed before any B-FRAG 2 measurement
    "BF2.PREP": 500.0,
    "BF2.DEV": 900.0,
    "BF2.TRAIN": 300.0,
    "BF2.VAL": 1800.0,
    "BF2.CONF": 3800.0,
    "BF2.ANAL": 500.0,
    "BF2.REST": 700.0,
}
TRANCHE_CEILING_S = {"CLOSE": 11400.0, "BF": 11400.0, "BF2": 11400.0}  # one common envelope, see COMMON_CEILING_S
COMMON_CEILING_S = 11400.0


def tranche(lot: str) -> str:
    return lot.split(".", 1)[0]


def tranche_used(records: list[dict[str, object]], tr: str) -> float:
    return sum(
        float(r.get("wall_seconds", 0.0))  # type: ignore[arg-type]
        for r in records
        if tranche(str(r.get("lot", ""))) == tr
    )
AUTHORISED_LOTS = set(LOT_CAPS) - {
    "RESERVE"
}  # RESERVE only after a logged 'reserve_allocation' note
VENV = Path(
    os.environ.get(
        "HOWM_VENV",
        "/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad/venv_howm",
    )
)
BASE_PYTHON = "/usr/bin/python3.11"
APPROVED_PYTHON = "3.11.18"
ALLOWED_TOOLS = {"/root/.local/bin/ruff"}


def interpreters(venv: Path = VENV) -> set[str]:
    return {str(venv / "bin" / n) for n in ("python", "python3", "python3.11")}


def approved_environments(records: list[dict[str, object]]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for r in records:
        if r.get("kind") == "environment_approved":
            p = r.get("payload") or {}
            if p.get("python") and p.get("freeze_sha256"):  # type: ignore[union-attr]
                out.add((str(p["python"]), str(p["freeze_sha256"])))  # type: ignore[index]
    return out


def program_of(command: list[str]) -> str:
    i = 0
    if command and Path(command[0]).name == "env":
        i = 1
        while i < len(command) and "=" in command[i] and not command[i].startswith("-"):
            i += 1
    return command[i] if i < len(command) else ""


def environment(venv: Path = VENV) -> dict[str, object]:
    cfg_path = venv / "pyvenv.cfg"
    if not cfg_path.exists():
        return {"venv": str(venv), "python": None, "freeze_sha256": None, "packages": 0}
    cfg = dict(line.split(" = ", 1) for line in cfg_path.read_text().splitlines() if " = " in line)
    lines = []
    for site in sorted(venv.glob("lib/python*/site-packages")):
        for meta in sorted(site.glob("*.dist-info/METADATA")):
            fields: dict[str, str] = {}
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
    return {
        "venv": str(venv),
        "python": cfg.get("version"),
        "freeze_sha256": hashlib.sha256(freeze.encode()).hexdigest(),
        "packages": len(lines),
    }


def launch_refusal(
    command: list[str], lot: str, records: list[dict[str, object]]
) -> tuple[str | None, dict[str, object]]:
    program = program_of(command)
    env_info = environment()
    if program in ALLOWED_TOOLS:
        return None, env_info
    if (
        lot == "R0.ENV"
    ):  # installation lot: base interpreter (venv creation) or the venv's own interpreter
        if program in interpreters() | {BASE_PYTHON}:
            return None, env_info
        return f"interpreter_not_authorised_for_install:{program}", env_info
    if program not in interpreters():
        return f"interpreter_not_authorised:{program}", env_info
    pair = (str(env_info.get("python")), str(env_info.get("freeze_sha256")))
    if pair not in approved_environments(records):
        return f"environment_not_approved:python={pair[0]}:freeze={pair[1]}", env_info
    return None, env_info


def lot_used(records: list[dict[str, object]], lot: str) -> float:
    return sum(float(r.get("wall_seconds", 0.0)) for r in records if r.get("lot") == lot)  # type: ignore[arg-type]


def reserve_open(records: list[dict[str, object]]) -> bool:
    return any(r.get("kind") == "reserve_allocation" for r in records)


def status() -> dict[str, object]:
    records = base.read_ledger(LEDGER)
    used = base.used_seconds(records)
    cpu = sum(float(r.get("cpu_seconds", 0.0)) for r in records)  # type: ignore[arg-type]
    return {
        "ledger": str(LEDGER.relative_to(ROOT)),
        "records": len(records),
        "commands": sum(r.get("kind") == "command" for r in records),
        "used_wall_seconds": round(used, 3),
        "used_cpu_seconds_reported": round(cpu, 3),
        "ceiling_wall_seconds": CEILING_S,
        "remaining_wall_seconds": round(max(0.0, CEILING_S - used), 3),
        "lots": {
            k: {"used": round(lot_used(records, k), 3), "cap": v} for k, v in LOT_CAPS.items()
        },
        "tranches": {
            tr: {"used": round(tranche_used(records, tr), 3), "ceiling": c}
            for tr, c in TRANCHE_CEILING_S.items()
        },
    }


def genesis() -> dict[str, object]:
    if base.read_ledger(LEDGER):
        raise base.LedgerError("HOWM-2 B ledger already started: genesis refused")
    anchor = json.loads(H1_ANCHOR.read_text())
    return base.append(
        LEDGER,
        {
            "kind": "genesis",
            "at_utc": datetime.now(UTC).isoformat(),
            "lot": "BF.PREP",
            "label": "HOWM-2 B ledger genesis (B-FRAG + C1 closure, decision n.6)",
            "decision": "docs/howm2/HOWM2_DECISION_6.json",
            "howm1_terminal_sha256_cited_not_credited": anchor["last_record_sha256"],
            "ceiling_wall_seconds": CEILING_S,
            "per_command_seconds": PER_COMMAND_S,
            "per_test_command_seconds": PER_TEST_COMMAND_S,
            "spend_eur": 0,
            "lot_caps": LOT_CAPS,
            "wall_seconds": 0.0,
        },
    )


def note(kind: str, label: str, lot: str, payload: dict[str, object]) -> dict[str, object]:
    records = base.read_ledger(LEDGER)
    if not records:
        raise base.LedgerError("no genesis")
    return base.append(
        LEDGER,
        {
            "kind": kind,
            "at_utc": datetime.now(UTC).isoformat(),
            "lot": lot,
            "label": label,
            "payload": payload,
            "wall_seconds": 0.0,
        },
    )


def _refuse(
    kind: str, lot: str, label: str, command: list[str], reason: str, **extra: object
) -> None:
    base.append(
        LEDGER,
        {
            "kind": kind,
            "at_utc": datetime.now(UTC).isoformat(),
            "lot": lot,
            "label": label,
            "refused_command": command,
            "reason": reason,
            "wall_seconds": 0.0,
            **extra,
        },
    )


def run(command: list[str], lot: str, label: str, test: bool) -> int:
    records = base.read_ledger(LEDGER)
    if not records or records[0].get("kind") != "genesis":
        raise base.LedgerError("HOWM-2 ledger has no genesis record")
    if lot not in LOT_CAPS or (
        lot not in AUTHORISED_LOTS and not (lot == "RESERVE" and reserve_open(records))
    ):
        _refuse("refused", lot, label, command, f"lot_not_authorised:{lot}")
        print(f"[howm2-budget] lot {lot} not authorised: refused", file=sys.stderr)
        return 4
    if not any(r.get("kind") == "decision_6" for r in records) or (
        lot.startswith("BF2.") and not any(r.get("kind") == "decision_7" for r in records)
    ):
        _refuse("refused", lot, label, command, "decision_not_recorded")
        return 4
    used = sum(float(r.get("wall_seconds", 0.0)) for r in records)  # common envelope (C1 closure + B-FRAG)
    remaining = COMMON_CEILING_S - used
    lot_remaining = LOT_CAPS[lot] - lot_used(records, lot)
    if remaining <= 0 or lot_remaining <= 0:
        _refuse(
            "stop",
            lot,
            label,
            command,
            "global_ceiling_reached" if remaining <= 0 else "lot_cap_reached",
        )
        print(json.dumps(status()), file=sys.stderr)
        return 3
    refusal, env_info = launch_refusal(command, lot, records)
    if refusal is not None:
        _refuse("refused", lot, label, command, refusal, environment=env_info)
        print(f"[howm2-budget] refused before launch: {refusal}", file=sys.stderr)
        return 5
    timeout = min(PER_TEST_COMMAND_S if test else PER_COMMAND_S, remaining, lot_remaining)
    LOGS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = LOGS / f"{len(records) + 1:04d}_{lot}_{stamp}.log"
    now = datetime.now(UTC).isoformat()
    conc = 1
    for flag in ("--par", "--workers"):
        if flag in command:
            try:
                conc = int(command[command.index(flag) + 1])
            except (ValueError, IndexError):
                pass
    base.append(LEDGER, {"kind": "command_started", "at_utc": now, "lot": lot, "label": label, "command": command,
                         "log": str(log_path.relative_to(ROOT)), "concurrency_declared": conc, "wall_seconds": 0.0})
    ru0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    timed_out = False
    env = dict(
        os.environ, PYTHONPATH=f"{ROOT / 'src'}:{ROOT}", HOWM_LEDGER_SEQUENCE=str(len(records) + 1)
    )
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, start_new_session=True, env=env
        )
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            code = process.wait()
    wall = time.monotonic() - started
    orphans = False
    try:  # T-RUN-03: nothing of the process group may survive
        os.killpg(process.pid, 0)
        orphans = True
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    ru1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (ru1.ru_utime - ru0.ru_utime) + (ru1.ru_stime - ru0.ru_stime)
    record = base.append(
        LEDGER,
        {
            "kind": "command",
            "at_utc": now,
            "lot": lot,
            "label": label,
            "test_command": test,
            "command": command,
            "timeout_seconds": round(timeout, 3),
            "timed_out": timed_out,
            "exit_code": code,
            "wall_seconds": round(wall, 3),
            "cpu_seconds": round(cpu, 3),
            "ended_utc": datetime.now(UTC).isoformat(),
            "children_maxrss_mb": round(ru1.ru_maxrss / 1024, 1),
            "concurrency_declared": conc,
            "orphans_killed": orphans,
            "log": str(log_path.relative_to(ROOT)),
            "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
            "environment": env_info,
        },
    )
    out = log_path.read_text(errors="replace")
    sys.stdout.write(out if len(out) < 20000 else out[:4000] + "\n[...]\n" + out[-12000:])
    st = status()
    print(
        f"\n[howm2-budget] #{record['sequence']} {lot} '{label}': {wall:.2f}s wall, {cpu:.1f}s cpu, exit={code}"
        f"{' TIMEOUT' if timed_out else ''}{' ORPHANS-KILLED' if orphans else ''} | lot {st['lots'][lot]['used']}/{LOT_CAPS[lot]}s"  # type: ignore[index]
        f" | tranche {tranche(lot)} {st['tranches'][tranche(lot)]['used']}/{TRANCHE_CEILING_S[tranche(lot)]}s"  # type: ignore[index]
    )
    return 124 if timed_out else code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lot", default="")
    parser.add_argument("--label", default="")
    parser.add_argument("--test", action="store_true")
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
        print(json.dumps(note(args.note, args.label, args.lot or "BF.PREP", payload), indent=1))
        return 0
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("missing command after --")
    return run(command, args.lot, args.label, args.test)


if __name__ == "__main__":
    raise SystemExit(main())
