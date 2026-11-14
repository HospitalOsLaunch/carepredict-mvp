"""Provenance, archive integrity and displayed-number traceability (T01, T31, T32).

The historical AJ-H archives are registered with their documented status only; nothing here
re-evaluates them. A_detached is authenticated at 2000 updates; its final 6000 result is NOT
attested, which is not a scientific failure.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ARCHIVES: dict[str, dict[str, Any]] = {
    "a7bf5dcc63fcc2391636b20ed3ac1726c7bcf796b8293beb6dc25003c71f9475": {
        "name": "HospitalOS_Lot_A_PRIMARY_20261112.zip",
        "mode": "primary",
        "attested_updates": 6000,
        "status": "COMPLETED_CRITERIA_FAILED",
        "source_commit": "c1a236e8c872b368198dd3791ff7a62fbbe6a6ff",
    },
    "db72732e55d237bea7a0e6fa3714e7d3627e0469add996ead25bb5e8254b387b": {
        "name": "HospitalOS_Checkpoint_A_DETACHED_2000_20261112.zip",
        "mode": "A_detached",
        "attested_updates": 2000,
        "status": "AUTHENTICATED_AT_2000_FINAL_6000_NOT_ATTESTED",
        "source_commit": "4b230b193a2b3bf3f4432f492fa75c828d558c8b",
    },
}


class ArchiveIntegrityError(RuntimeError):
    pass


class ProvenanceError(ValueError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_archive(path: Path | str, expected_sha256: str) -> None:
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ArchiveIntegrityError(f"{path}: sha256 {actual} != expected {expected_sha256}")


def verify_manifest(root: Path, manifest: Path) -> list[str]:
    """Return mismatches of a 'sha256  relative/path' manifest; empty list means intact."""
    problems = []
    for line in manifest.read_text().splitlines():
        if not line.strip():
            continue
        expected, rel = line.split(maxsplit=1)
        target = root / rel.strip()
        if not target.exists():
            problems.append(f"missing:{rel}")
        elif sha256_file(target) != expected:
            problems.append(f"altered:{rel}")
    return problems


def check_result_claim(claim: Mapping[str, Any]) -> dict[str, Any]:
    """Reject results attributed to the wrong archive/mode/update count (T31)."""
    record = ARCHIVES.get(str(claim.get("archive_sha256")))
    if record is None:
        raise ProvenanceError("unknown archive: no result can be attributed")
    if claim.get("mode") != record["mode"]:
        raise ProvenanceError(
            f"mode mismatch: claim {claim.get('mode')} but archive is {record['mode']}"
        )
    updates = int(claim.get("updates", -1))
    if updates > record["attested_updates"]:
        raise ProvenanceError(
            f"{record['mode']}: {updates} updates not attested (attested {record['attested_updates']})"
        )
    if record["mode"] == "A_detached" and claim.get("status") in {"FAIL", "SCIENTIFIC_FAILURE"}:
        raise ProvenanceError("A_detached final status is not attested: not a scientific failure")
    return record


def resolve_pointer(document: Any, pointer: str) -> Any:
    """RFC 6901 JSON pointer resolution used by the cockpit cards (T32)."""
    if pointer in ("", "/"):
        return document
    current = document
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current
