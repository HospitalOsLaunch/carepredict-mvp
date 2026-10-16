"""Lot 08: annual change diagnostics and unchanged-prefix checks; development only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from hospitalos.synthetic.changes import bounds
from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.engine import simulate
from hospitalos.synthetic.generate import export_result, source_hashes
from hospitalos.synthetic.policy import ObservedRulePolicy
from hospitalos.synthetic.policy_loop import run_policy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    raw = json.loads((root / "configs/synthetic/hospital_dated_changes_v1.json").read_text())
    records: list[dict[str, Any]] = []
    for family in ("v041", "local_v1", "hybrid_v1"):
        changed_config = HospitalConfig.model_validate({**raw, "mechanism_family": family})
        base_config = HospitalConfig.model_validate(
            {**raw, "mechanism_family": family, "changes": []}
        )
        first = min(bounds(changed_config, c)[0] for c in changed_config.changes)
        base = simulate(base_config)
        changed = simulate(changed_config)
        boundary = base_config.warmup_days * 24 + first
        for field in ("etats", "events", "actions"):
            assert [r for r in getattr(base.journal, field) if r["h"] < boundary] == [
                r for r in getattr(changed.journal, field) if r["h"] < boundary
            ], (family, field)
        assert base.journal.etats != changed.journal.etats
        for case, config, result in (
            ("reference", base_config, base),
            ("changes", changed_config, changed),
        ):
            destination = args.output / family / case
            manifest = export_result(config, result, destination)
            for name, expected in manifest["files_sha256"].items():
                assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == expected
            audit = [r for r in result.journal.events if r["type"] == "ORGANISATION_CHANGE"]
            record = {
                "family": family,
                "case": case,
                "config_sha256": config.fingerprint,
                "checks": manifest["checks"],
                "files_verified": len(manifest["files_sha256"]),
                "boundary_events": len(audit),
                "prefix_checked_until_h_exclusive": first,
                "prefix_includes_warmup_hours": config.warmup_days * 24,
                "events": audit,
                "manifest_sha256": hashlib.sha256(
                    (destination / "manifest.json").read_bytes()
                ).hexdigest(),
            }
            records.append(record)
            print(json.dumps({k: v for k, v in record.items() if k != "events"}), flush=True)
        del base, changed, result
    policy_dir = args.output / "observed_policy"
    policy_config = HospitalConfig.model_validate(raw)
    policy = run_policy(policy_config, ObservedRulePolicy(), policy_dir)
    for name, expected in policy["files_sha256"].items():
        assert hashlib.sha256((policy_dir / name).read_bytes()).hexdigest() == expected
    report = {
        "status": "complete",
        "synthetic_only": True,
        "test_opened": False,
        "purpose": "generator diagnostics, not adaptation or performance evaluation",
        "days": raw["days"],
        "warmup_days": raw["warmup_days"],
        "source_sha256": source_hashes(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cases": records,
        "observed_policy": policy,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
