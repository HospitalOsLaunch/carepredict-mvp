"""Compare movement-only and census reconciliation on the same development year."""

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
from hospitalos.synthetic.patient_census import CensusDelivery, CensusProfile, OnlineCensus
from hospitalos.synthetic.patient_learning import TruthStay, patient_target, prepare_patient_run
from hospitalos.synthetic.patient_observations import OnlinePatients, PatientDelivery


def scores(rows: tuple[PatientRow, ...], present: set[str]) -> Counter[str]:
    admitted = {r.stay_id for r in rows if r.status == "admitted"}
    return Counter(
        features=len(rows),
        stale_rows=sum(r.stale for r in rows),
        bed_conflict_rows=sum(r.bed_conflict for r in rows),
        admitted_rows=len(admitted),
        waiting_rows=len(rows) - len(admitted),
        ghost_admitted_hours=len(admitted - present),
        missing_present_hours=len(present - admitted),
        truth_present_hours=len(present),
    )


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
        raise ValueError("Census engineering validation requires a development world")
    simulation = json.loads((truth_dir / "manifest.json").read_text())
    patient_dir = args.output / "patients"
    profile = CensusProfile()
    patient = prepare_patient_run(truth_dir, patient_dir, census_profile=profile)
    print(json.dumps({"stage": "exports", "counts": patient["counts"]}), flush=True)
    verified = 0
    for root, manifest in ((truth_dir, simulation), (patient_dir, patient)):
        for name, digest in manifest["files_sha256"].items():
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
            verified += 1
    with gzip.open(patient_dir / "targets/stays.jsonl.gz", "rt") as stream:
        truth = {s.stay_id: s for line in stream if (s := TruthStay.model_validate_json(line))}
    arrivals: dict[int, set[str]] = defaultdict(set)
    departures: dict[int, set[str]] = defaultdict(set)
    present = set()
    for stay in truth.values():
        if stay.admission_h is not None:
            if stay.admission_h < 0 and (stay.departure_h is None or stay.departure_h >= 0):
                present.add(stay.stay_id)
            if stay.admission_h >= 0:
                arrivals[int(stay.admission_h)].add(stay.stay_id)
            if stay.departure_h is not None and stay.departure_h >= 0:
                departures[int(stay.departure_h)].add(stay.stay_id)
    batches: dict[int, list[dict[str, Any]]] = defaultdict(list)
    occupancy: dict[tuple[float, str], int] = {}
    for event in _events(truth_dir):
        batches[event["h"]].append(event)
        if event["type"] == "ETAT_UNITE":
            occupancy[(float(event["h"] + 1), event["unit_id"])] = event["payload"]["lits_occupes"]
    # Independent aggregate physical journal validates the synthetic census source.
    complete_checked = 0
    with gzip.open(patient_dir / "observed/censuses.jsonl.gz", "rt") as stream:
        for line in stream:
            snapshot = CensusDelivery.model_validate_json(line)
            actual = occupancy[snapshot.event_h, snapshot.unit_id]
            assert len(snapshot.members) <= actual
            if snapshot.complete:
                assert len(snapshot.members) == actual
                complete_checked += 1
    movements, census = OnlinePatients(config), OnlineCensus(config, profile)
    cursor = PatientAsOfCursor(config, run_id=patient["run_id"])
    baseline = PatientAsOfCursor(config, run_id="movement_baseline")
    comparison: dict[str, Counter[str]] = {"movement_only": Counter(), "with_census": Counter()}
    checked: Counter[str] = Counter()
    with (
        gzip.open(patient_dir / "observed/movements.jsonl.gz", "rt") as movement_file,
        gzip.open(patient_dir / "observed/censuses.jsonl.gz", "rt") as census_file,
        gzip.open(patient_dir / "observed/reconciliation.jsonl.gz", "rt") as audit_file,
        gzip.open(patient_dir / "features/patients_asof.jsonl.gz", "rt") as feature_file,
        gzip.open(patient_dir / "targets/departures.jsonl.gz", "rt") as label_file,
    ):
        for hour in range(-config.warmup_days * 24, config.days * 24):
            batch = batches.pop(hour, [])
            movements.push(hour, batch)
            census.push(hour, batch)
            if hour < 0:
                continue
            delivered, counted = movements.receive(hour), census.receive(hour)
            for movement in delivered:
                assert movement == PatientDelivery.model_validate_json(next(movement_file))
                checked["movement_receipts"] += 1
            for counted_unit in counted:
                assert counted_unit == CensusDelivery.model_validate_json(next(census_file))
                checked["census_receipts"] += 1
            rows = cursor.advance(hour, delivered, counted)
            for row in rows:
                assert row == PatientRow.model_validate_json(next(feature_file))
                assert patient_target(row, truth) == json.loads(next(label_file))
                checked["features_and_targets"] += 1
            for change in cursor.reconciliations:
                assert change == PatientReconciliation.model_validate_json(next(audit_file))
                checked["reconciliations"] += 1
            present.update(arrivals.pop(hour, set()))
            present.difference_update(departures.pop(hour, set()))
            comparison["movement_only"].update(scores(baseline.advance(hour, delivered), present))
            comparison["with_census"].update(scores(rows, present))
            if hour % (90 * 24) == 0:
                print(json.dumps({"stage": "replay", "day": hour // 24}), flush=True)
        for movement in movements.receive(config.days * 24):
            assert movement == PatientDelivery.model_validate_json(next(movement_file))
            checked["movement_receipts"] += 1
        for counted_unit in census.receive(config.days * 24):
            assert counted_unit == CensusDelivery.model_validate_json(next(census_file))
            checked["census_receipts"] += 1
        assert all(
            next(f, None) is None
            for f in (
                movement_file,
                census_file,
                audit_file,
                feature_file,
                label_file,
            )
        )
    assert (
        checked["features_and_targets"]
        == patient["counts"]["features"]
        == patient["counts"]["targets"]
    )
    assert checked["movement_receipts"] == patient["counts"]["deliveries"]
    assert checked["census_receipts"] == patient["counts"]["census_deliveries"]
    assert checked["reconciliations"] == patient["counts"]["reconciliation_rows"]
    assert (
        comparison["with_census"]["ghost_admitted_hours"]
        < comparison["movement_only"]["ghost_admitted_hours"]
    )
    report = {
        "status": "complete",
        "synthetic_only": True,
        "test_opened": False,
        "purpose": "observed census reconciliation; no prediction or clinical validation",
        "days": config.days,
        "warmup_days": config.warmup_days,
        "source_sha256": source_hashes(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "simulation_manifest": simulation,
        "patient_manifest": patient,
        "files_verified": verified,
        "complete_censuses_checked_against_physical_occupancy": complete_checked,
        "checked": dict(checked),
        "online_offline_equal": True,
        "late_censuses_retained_not_exported": len(census.pending),
        "comparison": comparison,
        "limits": [
            "Complete coverage is trusted; no undocumented omissions in complete snapshots.",
            "Unit absence leaves hospital presence unknown and never creates a discharge date.",
            "Unadmitted requests are outside the occupied-bed census scope.",
            "Single development year; no population or site generalization claim.",
        ],
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps({"stage": "verified", "checked": checked, "comparison": comparison}), flush=True
    )


if __name__ == "__main__":
    main()
