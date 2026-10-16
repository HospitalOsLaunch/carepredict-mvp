"""Lot 10: annual patient pipeline, online equality, target joins and frozen follow-up."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from hospitalos.synthetic.config import load_config
from hospitalos.synthetic.generate import generate, source_hashes
from hospitalos.synthetic.learning import _events
from hospitalos.synthetic.patient_asof import PatientAsOfCursor, PatientRow
from hospitalos.synthetic.patient_learning import TruthStay, patient_target, prepare_patient_run
from hospitalos.synthetic.patient_observations import OnlinePatients, PatientDelivery


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    config = load_config(Path("configs/synthetic/hospital_observation_intermittent_v1.json"))
    truth_dir, patient_dir = args.output / "truth", args.output / "patients"
    simulation = generate(config, truth_dir)
    print(json.dumps({"stage": "physical_year", "checks": simulation["checks"]}), flush=True)
    patient = prepare_patient_run(truth_dir, patient_dir)
    print(json.dumps({"stage": "patient_exports", "counts": patient["counts"]}), flush=True)
    verified = 0
    for root, manifest in ((truth_dir, simulation), (patient_dir, patient)):
        for name, digest in manifest["files_sha256"].items():
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
            verified += 1
    with gzip.open(patient_dir / "targets/stays.jsonl.gz", "rt") as stream:
        truth = {s.stay_id: s for line in stream if (s := TruthStay.model_validate_json(line))}
    batches: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in _events(truth_dir):
        batches[event["h"]].append(event)
    online = OnlinePatients(config)
    cursor = PatientAsOfCursor(config, run_id=patient["run_id"])
    row_count, receipt_count = 0, 0
    with (
        gzip.open(patient_dir / "observed/movements.jsonl.gz", "rt") as receipt_file,
        gzip.open(patient_dir / "features/patients_asof.jsonl.gz", "rt") as feature_file,
        gzip.open(patient_dir / "targets/departures.jsonl.gz", "rt") as label_file,
    ):
        receipts = iter(receipt_file)
        features = iter(feature_file)
        labels = iter(label_file)
        for hour in range(-config.warmup_days * 24, config.days * 24):
            online.push(hour, batches.pop(hour, []))
            if hour < 0:
                continue
            arrived = online.receive(hour)
            for row in arrived:
                assert row == PatientDelivery.model_validate_json(next(receipts))
                receipt_count += 1
            for feature in cursor.advance(hour, arrived):
                assert feature == PatientRow.model_validate_json(next(features))
                assert patient_target(feature, truth) == json.loads(next(labels))
                row_count += 1
        for row in online.receive(config.days * 24):
            assert row == PatientDelivery.model_validate_json(next(receipts))
            receipt_count += 1
        assert next(receipts, None) is next(features, None) is next(labels, None) is None
    assert row_count == patient["counts"]["features"] == patient["counts"]["targets"]
    assert receipt_count == patient["counts"]["deliveries"]
    report = {
        "status": "complete",
        "synthetic_only": True,
        "test_opened": False,
        "purpose": "movement contracts, not prediction, clinical realism or adaptation",
        "days": config.days,
        "warmup_days": config.warmup_days,
        "config_sha256": config.fingerprint,
        "source_sha256": source_hashes(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "simulation_manifest": simulation,
        "patient_manifest": patient,
        "files_verified": verified,
        "online_offline_features_equal": True,
        "online_offline_receipts_equal": True,
        "target_joins_checked": row_count,
        "receipts_checked": receipt_count,
        "late_receipts_retained_not_exported": len(online.pending),
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {"stage": "verified", "rows": row_count, "receipts": receipt_count, "files": verified}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
