"""Lot 09: three annual observation profiles on fixed physics; development only."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from hospitalos.synthetic.config import HospitalConfig, load_config
from hospitalos.synthetic.engine import simulate
from hospitalos.synthetic.generate import export_result, source_hashes
from hospitalos.synthetic.learning import prepare_learning_run
from hospitalos.synthetic.policy import ObservedRulePolicy
from hospitalos.synthetic.policy_loop import run_policy


def verify_files(directory: Path, manifest: dict[str, Any]) -> int:
    for name, digest in manifest["files_sha256"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
    return len(manifest["files_sha256"])


def check_transmission(path: Path, config: HospitalConfig) -> dict[str, int]:
    start = dt.datetime.combine(config.start, dt.time(), dt.timezone(dt.timedelta(hours=1)))
    windows = [
        (
            (o.starts_at - start).total_seconds() / 3600,
            (o.ends_at - start).total_seconds() / 3600,
            o.unit_ids,
        )
        for o in config.observation.outages
    ]
    receipts = 0
    deferred = 0
    with gzip.open(path, "rt") as stream:
        for line in stream:
            row = json.loads(line)
            receipts += 1
            assert row["available_h"] <= config.days * 24
            assert row["event_h"] <= row["recorded_h"] <= row["ingested_h"] <= row["available_h"]
            for low, high, units in windows:
                if units and row["unit_id"] not in units:
                    continue
                assert not low <= row["ingested_h"] < high
                assert not low <= row["available_h"] < high
                deferred += int(low <= row["event_h"] < high and row["available_h"] >= high)
    return {"receipts_checked": receipts, "receipts_from_outage_hours_delivered_later": deferred}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    cases = []
    reference: dict[str, str] | None = None
    for name in ("fast", "delayed", "intermittent"):
        config = load_config(root / f"configs/synthetic/hospital_observation_{name}_v1.json")
        truth_dir, observed_dir = args.output / name / "truth", args.output / name / "learning"
        result = simulate(config)  # Recompute independently to test physical invariance.
        truth = export_result(config, result, truth_dir)
        digests = {k: v for k, v in truth["files_sha256"].items() if k.startswith("truth/")}
        if reference is None:
            reference = digests
        assert digests == reference, "Observation profile changed physical truth"
        del result
        report = prepare_learning_run(truth_dir, observed_dir)
        observed = json.loads((observed_dir / "manifest.json").read_text())
        case = {
            "profile": name,
            "config_sha256": config.fingerprint,
            "checks": truth["checks"],
            "truth_sha256": digests,
            "observation_quality": report["observation_quality"],
            "files_verified": verify_files(truth_dir, truth) + verify_files(observed_dir, observed),
            "transmission": check_transmission(
                observed_dir / "observed/unit_states.jsonl.gz", config
            ),
            "learning_manifest_sha256": hashlib.sha256(
                (observed_dir / "manifest.json").read_bytes()
            ).hexdigest(),
        }
        cases.append(case)
        print(json.dumps(case), flush=True)
    policy_config = load_config(
        root / "configs/synthetic/hospital_observation_intermittent_v1.json"
    )
    policy_dir = args.output / "observed_policy"
    policy = run_policy(policy_config, ObservedRulePolicy(), policy_dir)
    policy_files = verify_files(policy_dir, policy)
    transmission = check_transmission(policy_dir / "observed/unit_states.jsonl.gz", policy_config)
    report = {
        "status": "complete",
        "synthetic_only": True,
        "test_opened": False,
        "purpose": "observation diagnostics on common physics; no learned generalization claim",
        "days": policy_config.days,
        "warmup_days": policy_config.warmup_days,
        "source_sha256": source_hashes(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixed_policy_truth_equal": True,
        "cases": cases,
        "observed_policy": policy,
        "policy_files_verified": policy_files,
        "policy_transmission": transmission,
        "closed_loop_note": "Observation changes may change recommendations and subsequent physics",
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"policy_checks": policy["checks"], "transmission": transmission}), flush=True)


if __name__ == "__main__":
    main()
