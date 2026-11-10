"""S0d public evidence inventory: never promotes a historical metadata document.

Reads only repository evidence JSON. Never fetches truth, observations, actions,
reserved test runs, tensors, or archived patient records. A historical evidence
manifest is NOT the three independently verified source artifacts of S0d.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, cast

SCHEMA = "hospitalos.s0d_legacy_evidence_inventory_v1"
ALLOWED_ROLES = frozenset((
    "cohort_registry_no_trajectories",
    "partitioned_cohort_runs",
    "simulation_truth_not_training_inputs",
))
MAX_EVIDENCE_BYTES = 2_000_000


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize_evidence(path: Path) -> dict[str, Any]:
    """Extract aggregate metadata ONLY, omit all reserved world identities."""
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise ValueError("Evidence document missing, symlinked or too large")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("Evidence document must be a JSON object")
    if doc.get("synthetic_only") is not True or doc.get("data_role") not in ALLOWED_ROLES:
        raise ValueError("Not recognized as synthetic-only historical evidence")
    role = doc["data_role"]
    if role == "cohort_registry_no_trajectories":
        partitions = doc.get("partitions")
        status = "REGISTRY_AGGREGATES_ONLY"
    elif role == "partitioned_cohort_runs":
        partitions = doc.get("summary", {}).get("partitions")
        status = "COHORT_MANIFEST_NO_ACTION_ARCHIVE_EVIDENCE"
        if doc.get("test_access", {}).get("opened") is not False:
            raise ValueError("Cohort document lacks an explicit sealed test claim")
    else:
        partitions = {doc.get("partition"): {"worlds": 1}}
        status = "SINGLE_TRUTH_MANIFEST_NO_OBS_ACTION_PAIR"
    if not isinstance(partitions, dict):
        raise ValueError("Manifest lacks partition summary")
    aggregate: dict[str, int] = {}
    for name, values in partitions.items():
        if name not in ("train", "development", "validation", "test"):
            raise ValueError("Unknown legacy partition")
        if not isinstance(values, dict):
            raise ValueError("Malformed partition aggregate")
        count = values.get("worlds")
        if type(count) is not int or count < 0 or count > 1_000_000:
            raise ValueError("Malformed world count")
        aggregate[name] = count
    # Reserved IDs, seeds, paths, run-level metrics and source code hashes are
    # intentionally not returned to the research agent or logger.
    return {
        "schema": SCHEMA,
        "status": status,
        "source_evidence_sha256": digest(path),
        "role": role,
        "synthetic_only": True,
        "aggregate_world_counts": aggregate,
        "actual_archive_triplets_verified": 0,
        "asof_windows_audited": 0,
        "model_training_authorized": False,
        "reserved_data_opened": False,
        "note": "Evidence JSON only; no source, observation or action archive opened",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S0d historical evidence inventory, no archives")
    parser.add_argument("evidence", nargs="+", type=Path)
    args = parser.parse_args(argv)
    if len(args.evidence) > 24:
        parser.error("At most 24 evidence files per call")
    summaries = [summarize_evidence(path) for path in args.evidence]
    print(json.dumps({"status": "EVIDENCE_ONLY_NO_TRAINING",
                      "evidence": summaries}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
