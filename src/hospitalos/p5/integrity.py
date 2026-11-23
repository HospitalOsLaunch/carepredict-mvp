"""Effective commitment checks before any generation or resume (review P5L-02/P5L-03).

The effective commitment is the LAST ``commitment`` record of the P5 ledger (E0, then E1, ...).
Before generating committed-partition episodes or resuming a pilot, the caller verifies that
every committed source, the sealed seeds file and the v6 engine are byte-identical to that
commitment. A mismatch raises ``IntegrityError``: nothing is generated, nothing is overwritten.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "evidence" / "decision_support" / "p5" / "BUDGET_LEDGER_P5.jsonl"
V6_COMMIT = "856a57c65fb0d55190addf6c39a45c57913eac07"


class IntegrityError(RuntimeError):
    pass


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def effective_commitment(ledger: Path = LEDGER) -> dict[str, Any]:
    if not ledger.exists():
        raise IntegrityError("P5 ledger missing")
    last = None
    for line in ledger.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            if record.get("kind") == "commitment":
                last = record
    if last is None:
        raise IntegrityError("no commitment recorded in the P5 ledger")
    payload = dict(last["payload"])
    payload["ledger_record_sha256"] = last["record_sha256"]
    return payload


def verify(commitment: Mapping[str, Any], root: Path = ROOT, check_v6: bool = True) -> dict[str, Any]:
    """Raise IntegrityError on any difference; return the verified identity otherwise."""
    problems = []
    for rel, expected in sorted(commitment["code_sha256"].items()):
        path = root / rel
        if not path.exists():
            problems.append(f"missing:{rel}")
        elif sha_file(path) != expected:
            problems.append(f"code_differs_from_commitment:{rel}")
    seeds = root / "evidence" / "decision_support" / "p5" / "SEEDS_SEALED.json"
    if commitment.get("seeds_file_sha256") and (not seeds.exists() or sha_file(seeds) != commitment["seeds_file_sha256"]):
        problems.append("sealed_seeds_differ_from_commitment")
    if check_v6:
        diff = subprocess.run(
            ["git", "diff", "--quiet", V6_COMMIT, "--", "src/hospitalos/decision_support", "configs/decision_support"],
            cwd=root,
        )
        if diff.returncode != 0:
            problems.append("v6_engine_modified")
    if problems:
        raise IntegrityError("; ".join(problems))
    return {
        "stage": commitment.get("stage"),
        "commitment_id": commitment["seeds"]["commitment_id"],
        "code_sha256": dict(commitment["code_sha256"]),
        "feature_schema_sha256": commitment.get("feature_schema_sha256"),
        "ledger_record_sha256": commitment.get("ledger_record_sha256"),
    }
