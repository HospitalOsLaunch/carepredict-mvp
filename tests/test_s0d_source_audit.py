"""S0d archive triplet, lineage and time-leakage tests. Zero model execution."""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from research_lab.integrated_full_model_v1_contract import make_v041_synthetic_spec
from research_lab.s0c_world_registry import build_registry
from research_lab.s0d_legacy_evidence import summarize_evidence
from research_lab.s0d_source_audit import audit_world
from research_lab.synthetic_adapter_v1 import ACTION_SCHEMA

LOCAL = dt.timezone(dt.timedelta(hours=1))
START = dt.datetime(2026, 11, 10, tzinfo=LOCAL)


def at(h: int) -> str:
    return (START + dt.timedelta(hours=h)).isoformat()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")
    return sha(path)


def write_gz(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for item in rows:
            stream.write(json.dumps(item, sort_keys=True) + "\n")
    return sha(path)


def source_dirs(root: Path) -> tuple[Path, Path, Path]:
    truth_root, observed_root, action_root = (
        root / "truth", root / "observed", root / "actions"
    )
    for path in (truth_root, observed_root, action_root):
        path.mkdir()
    cfg = {
        "start": "2026-11-10", "days": 3,
        "partition": "train", "hospital_id": "H",
        "mechanism_family": "v041", "observation": {"mode": "v041"},
    }
    config_hash = write_json(truth_root / "config.json", cfg)
    events = truth_root / "truth" / "events.jsonl.gz"
    write_gz(events, [{"type": "DECISION", "hour": 9}])
    units_file = truth_root / "truth" / "units_hourly.csv"
    units_file.write_text("hour,unit\n", encoding="utf-8")
    source_manifest = {
        "synthetic_only": True, "status": "complete",
        "data_role": "simulation_truth_not_training_inputs",
        "partition": "train", "hospital_id": "H",
        "mechanism_family": "v041",
        "files_sha256": {
            "config.json": config_hash,
            "truth/events.jsonl.gz": sha(events),
            "truth/units_hourly.csv": sha(units_file),
        },
    }
    source_sha = write_json(truth_root / "manifest.json", source_manifest)

    topology = {
        "schema_version": "OPERATIONAL_V2_RESEARCH_1",
        "topology_id": "H:structure", "version": 1,
        "valid_from": at(0), "available_at": at(0),
        "valid_to": None,
        "nodes": [{"entity_id": "H", "level": "hospital",
                   "parent_id": None, "capacity_beds": 40.0}],
    }
    topo_sha = write_json(observed_root / "topology.json", topology)
    obs_records = []
    for h in range(1, 73):
        obs_records.append({
            "schema_version": "OPERATIONAL_V2_RESEARCH_1",
            "event_id": f"H:obs:{h}", "version": 1,
            "entity_id": "H", "level": "hospital",
            "source_system": "synthetic_observed",
            "event_time": at(h), "recorded_at": at(h),
            "ingested_at": at(h), "available_at": at(h),
            "values": {"ed_waiting": h, "occupancy": h + 20},
        })
    obs_sha = write_gz(
        observed_root / "observations" / "hospital.jsonl.gz", obs_records
    )
    write_json(observed_root / "manifest.json", {
        "schema_version": "OPERATIONAL_V2_RESEARCH_1",
        "status": "complete", "synthetic_only": True,
        "data_role": "operational_observations_no_targets",
        "partition": "train", "hospital_id": "H",
        "source_manifest_sha256": source_sha,
        "source_clock": "fixed_utc_plus_01_no_dst",
        "start": at(0), "end_exclusive": at(72),
        "claims": {"real_connector_validated": False},
        "modes": {"hospital": {
            "frontier": ["H"], "path": "observations/hospital.jsonl.gz",
        }},
        "files_sha256": {
            "observations/hospital.jsonl.gz": obs_sha, "topology.json": topo_sha,
        },
    })
    channels = (
        "anticipation_sorties", "lits_supplementaires",
        "renfort_soignant", "acceleration_aval",
    )
    action_records = []
    for h in range(72):
        values = dict.fromkeys(channels, 0)
        if h % 24 == 9:
            values["renfort_soignant"] = 1
        action_records.append({
            "schema": ACTION_SCHEMA, "event_id": f"H:policy:{h:09d}",
            "version": 1, "entity_id": "H",
            "source_system": "synthetic_action_observed",
            "interval_start": at(h), "interval_end": at(h + 1),
            "recorded_at": at(h + 1), "available_at": at(h + 1),
            "values": values, "synthetic_only": True,
        })
    actions_sha = write_gz(
        action_root / "actions" / "intervals.jsonl.gz", action_records
    )
    write_json(action_root / "manifest.json", {
        "schema": ACTION_SCHEMA, "status": "complete",
        "synthetic_only": True, "partition": "train",
        "entity_id": "H", "entity_level": "hospital",
        "source_manifest_sha256": source_sha,
        "source_clock": "fixed_utc_plus_01_no_dst",
        "file": "actions/intervals.jsonl.gz",
        "source_files_sha256": source_manifest["files_sha256"],
        "files_sha256": {"actions/intervals.jsonl.gz": actions_sha},
        "coverage": {
            "channels": list(channels),
            "zero_proof": "full_09h_daily_unit_decision_grid_verified",
            "action_semantics": "hospital_count_of_requested_levers_not_execution_effect",
            "unit_count": 2, "decision_events": 6,
            "hour_intervals": 72,
        },
    })
    return truth_root, observed_root, action_root


def world_registry(
    truth_root: Path, observed_root: Path, action_root: Path
) -> dict[str, Any]:
    worlds = []
    for i, part in enumerate(
        ("train", "train", "development", "validation", "ood_blind")
    ):
        worlds.append({
            "world_id": f"w{i}", "partition": part,
            "hospital_id": "H" if i == 0 else f"H{i}",
            "generator_family": "v041", "observation_profile": "v041",
            "policy_family": "reference_policy",
            "structure_family": "blind" if i == 4 else "known",
            "seed_group": f"seed-lineage-{i}",
            "source_manifest_sha256": (
                sha(truth_root / "manifest.json") if i == 0 else f"{i + 5:064x}"
            ),
            "observation_manifest_sha256": (
                sha(observed_root / "manifest.json") if i == 0 else f"{i + 10:064x}"
            ),
            "action_manifest_sha256": (
                sha(action_root / "manifest.json") if i == 0 else f"{i + 20:064x}"
            ),
            "source_clock": "fixed_utc_plus_01_no_dst",
            "mechanism_tags": ["reference"],
            "readable_by_lab": part != "ood_blind",
        })
    return build_registry(worlds, freeze_id="fixture-s0d")


def audit(tmp_path: Path, **changes: Any) -> dict[str, Any]:
    truth, observed, actions = source_dirs(tmp_path)
    model = make_v041_synthetic_spec()
    model["history_steps"] = 3
    kwargs: dict[str, Any] = {
        "registry": world_registry(truth, observed, actions),
        "world_id": "w0",
        "truth_root": truth, "observed_root": observed, "action_root": actions,
        "spec": model, "origins": [at(28), at(29)],
        "label_cutoff": at(60), "max_age_hours": 6,
    }
    kwargs.update(changes)
    return audit_world(**kwargs)


def test_valid_synthetic_archive_triplet_and_origin_prefixes(tmp_path: Path) -> None:
    result = audit(tmp_path)
    assert result["status"] == "SOURCE_PREFIXES_CHECKED_NOT_TRAINING_ELIGIBLE"
    assert result["asof_windows_checked"] == 2
    assert result["correlated_window_pairs"] == 1
    assert result["future_labels_present"] == 6 * 2
    assert result["future_label_slots"] == 6 * 2
    assert result["native_action_coverage"] == {
        "hour_intervals": 72, "decision_events": 6, "units": 2
    }
    assert result["model_forward"] is False
    assert result["training"] is False
    assert result["trainable_supervision_verified"] is False
    assert result["future_factual_labels_compatible_with_no_op"] is False


def test_blind_and_validation_rejected_before_touching_files(tmp_path: Path) -> None:
    truth, obs, actions = source_dirs(tmp_path)
    reg = world_registry(truth, obs, actions)
    for ident in ("w3", "w4"):
        with pytest.raises(PermissionError):
            audit_world(
                registry=reg, world_id=ident,
                truth_root=tmp_path / "does-not-exist",
                observed_root=tmp_path / "not-mounted",
                action_root=tmp_path / "not-mounted",
                spec=make_v041_synthetic_spec(), origins=[at(28)],
                label_cutoff=at(60), max_age_hours=6,
            )


def test_manifest_commitment_tamper_refused(tmp_path: Path) -> None:
    truth, obs, actions = source_dirs(tmp_path)
    reg = world_registry(truth, obs, actions)
    reg["readable_worlds"][0]["policy_family"] = "malicious_changed"
    with pytest.raises(ValueError, match="modified"):
        audit_world(
            registry=reg, world_id="w0",
            truth_root=truth, observed_root=obs, action_root=actions,
            spec=make_v041_synthetic_spec(),
            origins=[at(28)], label_cutoff=at(60), max_age_hours=6,
        )


def test_invalid_source_hash_refused(tmp_path: Path) -> None:
    truth, obs, actions = source_dirs(tmp_path)
    reg = world_registry(truth, obs, actions)
    (truth / "truth/events.jsonl.gz").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Source truth bytes"):
        audit_world(
            registry=reg, world_id="w0",
            truth_root=truth, observed_root=obs, action_root=actions,
            spec=make_v041_synthetic_spec(),
            origins=[at(28)], label_cutoff=at(60), max_age_hours=6,
        )


def test_overlap_duplicate_and_boundary_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Duplicate origin"):
        audit(tmp_path, origins=[at(28), at(28)])


def test_evidence_manifest_in_repository_is_not_training_proof() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "docs/synthetic/evidence/lot05_cohort_manifest.json"
    result = summarize_evidence(path)
    assert result["aggregate_world_counts"] == {
        "train": 4, "validation": 4, "test": 4
    }
    assert result["actual_archive_triplets_verified"] == 0
    assert result["asof_windows_audited"] == 0
    assert result["reserved_data_opened"] is False
    assert "W_" not in json.dumps(result)


def test_invalid_evidence_role_or_partition_refused(tmp_path: Path) -> None:
    doc = tmp_path / "evidence.json"
    doc.write_text(json.dumps({"synthetic_only": False, "data_role": "real"}))
    with pytest.raises(ValueError, match="synthetic-only"):
        summarize_evidence(doc)
    doc.write_text(json.dumps({
        "synthetic_only": True,
        "data_role": "cohort_registry_no_trajectories",
        "partitions": {"unknown": {"worlds": 4}},
    }))
    with pytest.raises(ValueError, match="legacy partition"):
        summarize_evidence(doc)


@pytest.mark.parametrize(
    ("origin", "cutoff", "error"),
    [
        (at(1), at(60), "Context or forecast target"),
        (at(60), at(70), "Context or forecast target"),
        (at(28), at(40), "Labels not matured"),
        (at(28), at(74), "Labels not matured"),
    ],
)
def test_temporal_boundaries_refuse_bad_source_windows(
    tmp_path: Path, origin: str, cutoff: str, error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        audit(tmp_path, origins=[origin], label_cutoff=cutoff)


def test_incomplete_same_run_actions_refused_even_if_sha_updated(
    tmp_path: Path,
) -> None:
    truth, observed, actions = source_dirs(tmp_path)
    file = actions / "actions/intervals.jsonl.gz"
    with gzip.open(file, "rt", encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream]
    # Delete a historical interval: never silently reinterpret it as zero.
    write_gz(file, records[:-1])
    path = actions / "manifest.json"
    metadata = json.loads(path.read_text())
    metadata["files_sha256"]["actions/intervals.jsonl.gz"] = sha(file)
    write_json(path, metadata)
    registry = world_registry(truth, observed, actions)
    model = make_v041_synthetic_spec()
    model["history_steps"] = 3
    with pytest.raises(ValueError, match="Incomplete"):
        audit_world(
            registry=registry, world_id="w0", truth_root=truth,
            observed_root=observed, action_root=actions,
            spec=model, origins=[at(28)], label_cutoff=at(60),
            max_age_hours=6,
        )


def test_cross_world_action_source_reference_fails(
    tmp_path: Path,
) -> None:
    truth, observed, actions = source_dirs(tmp_path)
    path = actions / "manifest.json"
    metadata = json.loads(path.read_text())
    metadata["source_manifest_sha256"] = "9" * 64
    write_json(path, metadata)
    registry = world_registry(truth, observed, actions)
    model = make_v041_synthetic_spec()
    model["history_steps"] = 3
    with pytest.raises(ValueError, match="same run"):
        audit_world(
            registry=registry, world_id="w0", truth_root=truth,
            observed_root=observed, action_root=actions,
            spec=model, origins=[at(28)], label_cutoff=at(60),
            max_age_hours=6,
        )
