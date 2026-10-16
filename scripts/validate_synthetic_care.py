"""Annual care-document receipts, online joins and noninterference with patient presence."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from hospitalos.synthetic.config import load_config
from hospitalos.synthetic.generate import generate, source_hashes
from hospitalos.synthetic.learning import _events, verify_source
from hospitalos.synthetic.patient_asof import PatientAsOfCursor, PatientReconciliation, PatientRow
from hospitalos.synthetic.patient_care import CareDelivery, DeparturePlan, OnlineCare
from hospitalos.synthetic.patient_care_asof import CareAsOfCursor, PatientCareRow
from hospitalos.synthetic.patient_census import CensusDelivery, CensusProfile, OnlineCensus
from hospitalos.synthetic.patient_learning import TruthStay, patient_target, prepare_patient_run
from hospitalos.synthetic.patient_observations import OnlinePatients, PatientDelivery


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    truth_dir = args.source or args.output / "truth"
    if args.source is None:
        config = load_config(Path("configs/synthetic/hospital_observation_intermittent_v1.json"))
        generate(config, truth_dir)
    config, _ = verify_source(truth_dir)
    if config.partition != "development":
        raise ValueError("Care engineering validation requires a development world")
    simulation = json.loads((truth_dir / "manifest.json").read_text())
    patient_dir = args.output / "patients"
    manifest = prepare_patient_run(
        truth_dir, patient_dir, census_profile=CensusProfile(), with_care=True
    )
    print(json.dumps({"stage": "exports", "counts": manifest["counts"]}), flush=True)
    verified = 0
    for root, recorded in ((truth_dir, simulation), (patient_dir, manifest)):
        for name, digest in recorded["files_sha256"].items():
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
            verified += 1
    # A hash also matches an archive that was already truncated when hashed.
    # Check complete gzip streams and cardinalities before the costly replay.
    exported_rows = {
        "observed/movements.jsonl.gz": "deliveries",
        "observed/censuses.jsonl.gz": "census_deliveries",
        "observed/care.jsonl.gz": "care_deliveries",
        "observed/reconciliation.jsonl.gz": "reconciliation_rows",
        "features/patients_asof.jsonl.gz": "features",
        "features/patient_care_asof.jsonl.gz": "care_rows",
        "targets/stays.jsonl.gz": "truth_stays",
        "targets/departures.jsonl.gz": "targets",
    }
    for name, counter in exported_rows.items():
        with gzip.open(patient_dir / name, "rt") as exported:
            assert sum(1 for _ in exported) == manifest["counts"][counter], name
    with gzip.open(patient_dir / "targets/stays.jsonl.gz", "rt") as stream:
        truth = {s.stay_id: s for line in stream if (s := TruthStay.model_validate_json(line))}
    batches: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in _events(truth_dir):
        batches[event["h"]].append(event)
    movements, census, care = OnlinePatients(config), OnlineCensus(config), OnlineCare(config)
    cursor = PatientAsOfCursor(config, run_id=manifest["run_id"])
    care_cursor = CareAsOfCursor(config)
    checked: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    with (
        gzip.open(patient_dir / "observed/movements.jsonl.gz", "rt") as movement_file,
        gzip.open(patient_dir / "observed/censuses.jsonl.gz", "rt") as census_file,
        gzip.open(patient_dir / "observed/care.jsonl.gz", "rt") as care_file,
        gzip.open(patient_dir / "observed/reconciliation.jsonl.gz", "rt") as audit_file,
        gzip.open(patient_dir / "features/patients_asof.jsonl.gz", "rt") as feature_file,
        gzip.open(patient_dir / "features/patient_care_asof.jsonl.gz", "rt") as enriched_file,
        gzip.open(patient_dir / "targets/departures.jsonl.gz", "rt") as label_file,
    ):
        for hour in range(-config.warmup_days * 24, config.days * 24):
            batch = batches.pop(hour, [])
            movements.push(hour, batch)
            census.push(hour, batch)
            care.push(hour, batch)
            if hour < 0:
                continue
            delivered, counted, documented = (
                movements.receive(hour),
                census.receive(hour),
                care.receive(hour),
            )
            for movement in delivered:
                assert movement == PatientDelivery.model_validate_json(next(movement_file))
                checked["movement_receipts"] += 1
            for counted_unit in counted:
                assert counted_unit == CensusDelivery.model_validate_json(next(census_file))
                checked["census_receipts"] += 1
            for document in documented:
                assert document == CareDelivery.model_validate_json(next(care_file))
                checked["care_receipts"] += 1
                kinds[document.payload.kind] += 1
            care_cursor.advance(hour, documented)
            # Presence receives neither care documents nor outcome truth.
            for row in cursor.advance(hour, delivered, counted):
                assert row == PatientRow.model_validate_json(next(feature_file))
                enriched = care_cursor.for_patient(row)
                assert enriched == PatientCareRow.model_validate_json(next(enriched_file))
                assert patient_target(row, truth) == json.loads(next(label_file))
                checked["features_and_targets"] += 1
                if enriched.departure_plan:
                    plan = enriched.departure_plan.payload
                    assert isinstance(plan, DeparturePlan)
                    checked["forecast_beyond_extraction_rows"] += plan.planned_day >= config.days
                if enriched.downstream:
                    statuses[enriched.downstream.payload.model_dump()["status"]] += 1
            for change in cursor.reconciliations:
                assert change == PatientReconciliation.model_validate_json(next(audit_file))
                checked["reconciliations"] += 1
            if hour % (90 * 24) == 0:
                print(json.dumps({"stage": "online_verification", "day": hour // 24}), flush=True)
        for movement in movements.receive(config.days * 24):
            assert movement == PatientDelivery.model_validate_json(next(movement_file))
            checked["movement_receipts"] += 1
        for counted_unit in census.receive(config.days * 24):
            assert counted_unit == CensusDelivery.model_validate_json(next(census_file))
            checked["census_receipts"] += 1
        for document in care.receive(config.days * 24):
            assert document == CareDelivery.model_validate_json(next(care_file))
            checked["care_receipts"] += 1
            kinds[document.payload.kind] += 1
        assert all(
            next(f, None) is None
            for f in (
                movement_file,
                census_file,
                care_file,
                audit_file,
                feature_file,
                enriched_file,
                label_file,
            )
        )
    counts = manifest["counts"]
    assert (
        checked["features_and_targets"]
        == counts["features"]
        == counts["care_rows"]
        == counts["targets"]
    )
    assert checked["care_receipts"] == counts["care_deliveries"]
    assert checked["movement_receipts"] == counts["deliveries"]
    assert checked["census_receipts"] == counts["census_deliveries"]
    assert checked["reconciliations"] == counts["reconciliation_rows"]
    report = {
        "status": "complete",
        "synthetic_only": True,
        "test_opened": False,
        "purpose": "care-document contracts and joins, not prediction or clinical validation",
        "days": config.days,
        "warmup_days": config.warmup_days,
        "source_sha256": source_hashes(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "simulation_manifest": simulation,
        "patient_manifest": manifest,
        "files_verified": verified,
        "gzip_archives_verified": len(exported_rows),
        "checked": dict(checked),
        "care_receipts_by_kind": dict(kinds),
        "downstream_rows_by_status": dict(statuses),
        "online_offline_equal": True,
        "presence_independent_of_care": True,
        "late_care_receipts_retained_not_exported": len(care.pending),
        "limits": manifest["care_assumptions"]
        + [
            "Care observations do not establish presence or resolve unknown patient locations.",
            "Missing downstream evidence does not mean no downstream need.",
            "No model fitting, notes, clinical validation or mechanism generalization claim.",
        ],
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps({"stage": "verified", "checked": checked, "care_receipts_by_kind": kinds}),
        flush=True,
    )


if __name__ == "__main__":
    main()
