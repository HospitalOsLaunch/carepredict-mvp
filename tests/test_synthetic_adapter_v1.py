"""Offline synthetic_adapter_v1 tests: no simulator, torch, or model forward."""
from __future__ import annotations

import copy
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from research_lab.integrated_full_model_v1_contract import make_example_spec
from research_lab.synthetic_adapter_v1 import ACTION_SCHEMA, build_window
from research_lab.synthetic_adapter_v1_files import build_from_archives, read_sources

T = dt.datetime(2026, 11, 10, 12, tzinfo=dt.UTC)
STEP = dt.timedelta(hours=1)
SOURCE_HASH = "b" * 64


def ts(hours: int) -> str:
    return (T + hours * STEP).isoformat()


def spec() -> dict[str, Any]:
    out = make_example_spec()
    out["history_steps"] = 3
    return out


def obs(hours: int, waiting: int | None, occupancy: int, *,
        version: int = 1, delivery_hours: int | None = None,
        event_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": "OPERATIONAL_V2_RESEARCH_1",
        "event_id": event_id or f"H:{hours}",
        "version": version,
        "entity_id": "H",
        "level": "hospital",
        "source_system": "synthetic_observed",
        "event_time": ts(hours),
        "recorded_at": ts(hours),
        "ingested_at": ts(hours),
        "available_at": ts(hours if delivery_hours is None else delivery_hours),
        "values": {"ed_waiting": waiting, "occupancy": occupancy},
    }


def action(hours: int, staffing: float, discharge: float, *,
           version: int = 1, delivery_hours: int | None = None) -> dict[str, Any]:
    return {
        "schema": ACTION_SCHEMA,
        "event_id": f"H:action:{hours}",
        "version": version,
        "entity_id": "H",
        "source_system": "synthetic_action_observed",
        "interval_start": ts(hours - 1),
        "interval_end": ts(hours),
        "recorded_at": ts(hours),
        "available_at": ts(hours if delivery_hours is None else delivery_hours),
        "values": {"staffing_delta": staffing, "discharge_delta": discharge},
        "synthetic_only": True,
    }


def topology() -> dict[str, Any]:
    return {
        "schema_version": "OPERATIONAL_V2_RESEARCH_1",
        "topology_id": "H:structure",
        "version": 1,
        "valid_from": ts(-200),
        "valid_to": None,
        "available_at": ts(-200),
        "nodes": [
            {"entity_id": "H", "level": "hospital", "parent_id": None,
             "capacity_beds": 40.0}
        ],
    }


def fixture() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    observations = [
        obs(-2, 5, 18),
        obs(-1, 6, 19),
        obs(0, 7, 20),
        obs(-1, 99, 19, version=2, delivery_hours=2),
        obs(1, 8, 21),
        obs(6, 10, 25),
        obs(24, 15, 30),
    ]
    actions = [action(-2, 0.0, 0.0), action(-1, 0.15, 0.0),
               action(0, 0.0, 0.1)]
    return spec(), observations, actions, topology()


def build(**changes: object) -> dict[str, Any]:
    model, observations, actions, structure = fixture()
    args: dict[str, Any] = {
        "spec": model, "observations": observations,
        "action_intervals": actions, "topology": structure,
        "entity_id": "H", "origin": ts(0), "label_cutoff": ts(25),
        "partition": "development", "max_age_hours": 3,
    }
    args.update(changes)
    return build_window(**args)


def test_temporal_alignment_and_explicit_no_op() -> None:
    item = build()
    assert item["x"][0][0] == [5.0, 0.0, 0.0]
    assert item["x"][0][1] == [6.0, 0.0, 0.0]
    assert item["x"][0][2] == [7.0, 0.0, 0.0]
    assert item["static"] == [[40.0]]
    assert item["actions_context"] == [
        [[0.0, 0.0], [0.15, 0.0], [0.0, 0.1]]
    ]
    assert item["action_mode"] == "no_op"
    assert item["future_actions"] is None
    assert item["future_actions_available_ns"] is None
    assert item["training_targets"] == [[[8.0, 21.0], [10.0, 25.0], [15.0, 30.0]]]
    assert item["training_target_mask"] == [[[1, 1], [1, 1], [1, 1]]]
    assert item["origin_ns"][0] == item["event_ns"][0][-1]
    assert all(t <= item["origin_ns"][0] for t in item["action_available_ns"][0])
    assert item["supervision_alignment"]["no_op_forecast_can_be_scored_against_labels"] is False
    assert item["supervision_alignment"]["training_loss_authorized"] is False
    assert item["forward_executed"] is False
    assert item["training_executed"] is False


def test_late_correction_cannot_rewrite_history_at_origin() -> None:
    item = build()
    assert item["x"][0][1][0] == 6.0
    model, observations, actions, structure = fixture()
    observations.append(obs(-2, 100, 18, version=2, delivery_hours=10))
    assert build(
        observations=observations, spec=model,
        action_intervals=actions, topology=structure
    )["x"] == item["x"]


def test_missing_value_has_explicit_mask_not_a_real_zero() -> None:
    model, observations, actions, structure = fixture()
    observations[2] = obs(0, None, 20)
    result = build(spec=model, observations=observations,
                   action_intervals=actions, topology=structure)
    assert result["x"][0][-1] == [0.0, 1.0, 0.0]
    assert result["provenance"]["missing_feature_values"] == 1


def test_delayed_delivery_uses_last_known_observation_and_age() -> None:
    model, observations, actions, structure = fixture()
    observations[2] = obs(0, 7, 20, delivery_hours=1)
    result = build(spec=model, observations=observations,
                   action_intervals=actions, topology=structure)
    assert result["x"][0][-1] == [6.0, 0.0, 1.0]
    assert result["available_ns"][0][-1] <= result["origin_ns"][0]


@pytest.mark.parametrize("bad_partition", ["test", "holdout", "reserved", "unknown"])
def test_reserved_split_never_read(bad_partition: str) -> None:
    with pytest.raises(PermissionError):
        build(partition=bad_partition)


def test_missing_action_interval_is_a_hard_failure() -> None:
    _model, _observations, actions, _topology = fixture()
    with pytest.raises(ValueError, match="never impute zero"):
        build(action_intervals=actions[:-1])


def test_incompatible_action_oracle_and_invalid_provenance_rejected() -> None:
    _model, _observations, actions, _topology = fixture()
    altered = copy.deepcopy(actions)
    altered[0]["values"] = {
        "discharge_delta": 0.0, "staffing_delta": 0.0
    }
    # The JSON object order is immaterial; the tensor channel order is pinned.
    assert build(action_intervals=altered)["actions_context"][0][0] == [0.0, 0.0]
    altered = copy.deepcopy(actions)
    altered[0]["values"]["extra_oracle_action"] = 2.0
    with pytest.raises(ValueError, match="exact synthetic contract"):
        build(action_intervals=altered)
    altered = copy.deepcopy(actions)
    altered[0]["synthetic_only"] = False
    with pytest.raises(ValueError, match="synthetic"):
        build(action_intervals=altered)


def test_no_hidden_labels_allowed() -> None:
    _model, observations, _actions, _topology = fixture()
    altered = copy.deepcopy(observations)
    altered[0]["values"]["criticality"] = 0.2
    with pytest.raises(ValueError, match="observable value"):
        build(observations=altered)


def test_bad_revision_conflicting_event_or_source_collision_rejected() -> None:
    _model, observations, actions, _topology = fixture()
    altered = copy.deepcopy(observations)
    altered[0]["values"]["ed_waiting"] = 123
    altered.append(observations[0])
    with pytest.raises(ValueError, match="Conflicting retransmission"):
        build(observations=altered)
    altered = copy.deepcopy(observations)
    altered.append(obs(-2, 5, 18, event_id="another-source-id"))
    with pytest.raises(ValueError, match="Multiple source events"):
        build(observations=altered)
    changed = copy.deepcopy(actions)
    changed[0]["available_at"] = ts(4)
    with pytest.raises(ValueError, match="never impute zero"):
        build(action_intervals=changed)


def test_future_labels_missing_remain_masked() -> None:
    model, observations, actions, structure = fixture()
    observations = [o for o in observations if o["event_time"] != ts(6)]
    result = build(spec=model, observations=observations,
                   action_intervals=actions, topology=structure)
    assert result["training_targets"][0][1] == [0.0, 0.0]
    assert result["training_target_mask"][0][1] == [0, 0]


def test_topology_or_label_availability_fail_closed() -> None:
    model, observations, actions, structure = fixture()
    structure["available_at"] = ts(1)
    with pytest.raises(ValueError, match="Topology unavailable"):
        build(spec=model, observations=observations,
              action_intervals=actions, topology=structure)
    with pytest.raises(ValueError, match="Labels not mature"):
        build(label_cutoff=ts(23))


def _write_gz(path: Path, records: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for row in records:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_fixture(tmp: Path) -> tuple[Path, Path]:
    _model, observations, actions, structure = fixture()
    observed = tmp / "observed"
    action_root = tmp / "action"
    observed.mkdir()
    action_root.mkdir()
    obs_sha = _write_gz(observed / "observations/hospital.jsonl.gz", observations)
    act_sha = _write_gz(action_root / "actions/intervals.jsonl.gz", actions)
    (observed / "topology.json").write_text(json.dumps(structure))
    topo_sha = hashlib.sha256((observed / "topology.json").read_bytes()).hexdigest()
    (observed / "manifest.json").write_text(json.dumps({
        "schema_version": "OPERATIONAL_V2_RESEARCH_1",
        "synthetic_only": True, "status": "complete",
        "partition": "development",
        "data_role": "operational_observations_no_targets",
        "source_manifest_sha256": SOURCE_HASH,
        "source_clock": "fixed_utc_plus_01_no_dst",
        "claims": {"real_connector_validated": False},
        "modes": {"hospital": {
            "path": "observations/hospital.jsonl.gz", "frontier": ["H"]
        }},
        "files_sha256": {
            "observations/hospital.jsonl.gz": obs_sha,
            "topology.json": topo_sha,
        },
    }))
    (action_root / "manifest.json").write_text(json.dumps({
        "schema": ACTION_SCHEMA, "status": "complete", "synthetic_only": True,
        "partition": "development", "source_manifest_sha256": SOURCE_HASH,
        "source_clock": "fixed_utc_plus_01_no_dst",
        "entity_id": "H", "entity_level": "hospital",
        "file": "actions/intervals.jsonl.gz",
        "files_sha256": {"actions/intervals.jsonl.gz": act_sha},
    }))
    return observed, action_root


def test_verified_archive_reader_and_window(tmp_path: Path) -> None:
    observed, actions = archive_fixture(tmp_path)
    result = build_from_archives(
        observed_root=observed, action_root=actions, entity_id="H",
        spec=spec(), origin=ts(0), label_cutoff=ts(25), max_age_hours=3
    )
    assert result["x"][0][-1] == [7.0, 0.0, 0.0]
    assert result["provenance"]["archives"]["real_hospital_verified"] is False
    assert result["forward_executed"] is False


def test_archive_cross_run_hash_mismatch_and_test_holdout(tmp_path: Path) -> None:
    observed, actions = archive_fixture(tmp_path)
    path = actions / "manifest.json"
    data = json.loads(path.read_text())
    data["source_manifest_sha256"] = "9" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="same-run"):
        read_sources(observed, actions, "H")
    data["source_manifest_sha256"] = SOURCE_HASH
    path.write_text(json.dumps(data))
    manifest = observed / "manifest.json"
    original = json.loads(manifest.read_text())
    original["partition"] = "test"
    manifest.write_text(json.dumps(original))
    with pytest.raises(PermissionError, match="Reserved test"):
        read_sources(observed, actions, "H")


def test_archive_tampered_bytes_fail_before_parsing(tmp_path: Path) -> None:
    observed, actions = archive_fixture(tmp_path)
    with (actions / "actions/intervals.jsonl.gz").open("ab") as stream:
        stream.write(b"tampering")
    with pytest.raises(ValueError, match="immutable manifest"):
        read_sources(observed, actions, "H")
