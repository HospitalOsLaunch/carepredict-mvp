"""S0a exporter verification, only fabricated archived events (no simulation)."""
from __future__ import annotations

from typing import Any

import copy
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_lab.integrated_full_model_v1_contract import make_v041_synthetic_spec
from research_lab.synthetic_action_export_v041 import (
    LEVER_CHANNELS,
    build_ledger,
    export_existing_truth,
)
from research_lab.synthetic_adapter_v1_files import build_from_archives, read_sources

START = dt.datetime(2026, 11, 10, tzinfo=dt.timezone(dt.timedelta(hours=1)))


def clock(h: int) -> str:
    return (START + dt.timedelta(hours=h)).isoformat()


def decision(h: int, u: str, *active: str) -> dict[str, Any]:
    return {
        "event_id": f"S0:E:{h}:{u}",
        "hospital_id": "S0",
        "pole_id": "P0",
        "unit_id": u,
        "h": h,
        "timestamp": clock(h),
        "type": "DECISION",
        "payload": {name: int(name in active) for name in LEVER_CHANNELS},
    }


def sample(days: int = 2) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    config = {
        "start": "2026-11-10", "hospital_id": "S0", "partition": "development",
        "days": days, "warmup_days": 1,
        "poles": [{"pole_id": "P0", "units": [
            {"unit_id": "U_A"}, {"unit_id": "U_B"},
        ]}],
    }
    rows = [
        decision(d * 24 + 9, u, *(("renfort_soignant",) if u == "U_A" else ()))
        for d in range(days) for u in ("U_A", "U_B")
    ]
    truth = {
        "status": "complete", "synthetic_only": True,
        "data_role": "simulation_truth_not_training_inputs",
        "partition": config["partition"], "hospital_id": "S0",
        "counts": {"events_including_warmup": len(rows)},
    }
    return truth, config, rows


def test_extracts_actual_native_levers_not_phasea_deltas() -> None:
    truth, cfg, events = sample()
    actions, proof = build_ledger(truth=truth, config=cfg, events=events)
    assert len(actions) == 48
    assert proof["decision_events"] == 4
    assert proof["zero_proof"] == "full_09h_daily_unit_decision_grid_verified"
    # The decisions happened at 09:00; the source state at the end of hour 09
    # is observable at 10:00. This is explicit conservative as-of accounting.
    assert actions[9]["interval_start"] == clock(9)
    assert actions[9]["available_at"] == clock(10)
    assert actions[9]["values"] == {
        "anticipation_sorties": 0, "lits_supplementaires": 0,
        "renfort_soignant": 1, "acceleration_aval": 0,
    }
    assert actions[8]["values"] == dict.fromkeys(LEVER_CHANNELS, 0)
    assert actions[10]["values"] == dict.fromkeys(LEVER_CHANNELS, 0)
    assert proof["action_semantics"].startswith("hospital_count_of_requested")
    assert all("staffing_delta" not in a["values"] for a in actions)


def test_missing_unit_decision_cannot_be_imputed_as_zero() -> None:
    truth, cfg, events = sample()
    with pytest.raises(ValueError, match="Incomplete daily decision coverage"):
        build_ledger(truth=truth, config=cfg, events=events[:-1])


def test_duplicate_and_wrong_time_fail_closed() -> None:
    truth, cfg, events = sample()
    with pytest.raises(ValueError, match="Duplicate"):
        build_ledger(truth=truth, config=cfg, events=[*events, events[0]])
    bad = copy.deepcopy(events)
    bad[0]["h"] = 10
    with pytest.raises(ValueError, match="Unexpected decision time"):
        build_ledger(truth=truth, config=cfg, events=bad)
    bad = copy.deepcopy(events)
    bad[0]["timestamp"] = clock(10)
    with pytest.raises(ValueError, match="clock"):
        build_ledger(truth=truth, config=cfg, events=bad)


def test_nonbinary_unknown_hidden_and_crosshospital_values_fail() -> None:
    truth, cfg, events = sample()
    bad = copy.deepcopy(events)
    bad[0]["payload"]["renfort_soignant"] = 2
    with pytest.raises(ValueError, match="nonbinary"):
        build_ledger(truth=truth, config=cfg, events=bad)
    bad = copy.deepcopy(events)
    bad[0]["payload"]["oracle_effect"] = 4
    with pytest.raises(ValueError, match="nonbinary"):
        build_ledger(truth=truth, config=cfg, events=bad)
    bad = copy.deepcopy(events)
    bad[0]["hospital_id"] = "elsewhere"
    with pytest.raises(ValueError, match="another hospital"):
        build_ledger(truth=truth, config=cfg, events=bad)


def test_reserved_holdout_fails_without_extraction() -> None:
    truth, cfg, events = sample()
    truth["partition"] = cfg["partition"] = "test"
    with pytest.raises(PermissionError, match="Reserved"):
        build_ledger(truth=truth, config=cfg, events=events)


def _write_gz(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, sort_keys=True) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def truth_archive(root: Path) -> Path:
    root.mkdir()
    manifest, config, rows = sample()
    (root / "config.json").write_text(json.dumps(config))
    events_sha = _write_gz(root / "truth/events.jsonl.gz", rows)
    manifest["files_sha256"] = {
        "config.json": hashlib.sha256((root / "config.json").read_bytes()).hexdigest(),
        "truth/events.jsonl.gz": events_sha,
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root


def observation_archive(root: Path, source: Path) -> Path:
    root.mkdir()
    def observation(t: int, waiting: int) -> dict[str, Any]:
        return {
            "schema_version": "OPERATIONAL_V2_RESEARCH_1",
            "event_id": f"S0:obs:{t}", "version": 1,
            "entity_id": "S0", "level": "hospital",
            "source_system": "synthetic_observed",
            "event_time": clock(t), "recorded_at": clock(t),
            "ingested_at": clock(t), "available_at": clock(t),
            "values": {"ed_waiting": waiting, "occupancy": waiting + 12},
        }
    recorded_times = [10, 11, 12, 13, 18, 36]
    data_sha = _write_gz(
        root / "observations/hospital.jsonl.gz",
        [observation(t, t % 20 + 5) for t in recorded_times],
    )
    topology = {
        "schema_version": "OPERATIONAL_V2_RESEARCH_1",
        "topology_id": "S0:structure", "version": 1,
        "valid_from": clock(-24), "valid_to": None,
        "available_at": clock(-24),
        "nodes": [{"entity_id": "S0", "level": "hospital", "parent_id": None,
                   "capacity_beds": 45.0}],
    }
    (root / "topology.json").write_text(json.dumps(topology))
    topo_sha = hashlib.sha256((root / "topology.json").read_bytes()).hexdigest()
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": "OPERATIONAL_V2_RESEARCH_1",
        "status": "complete", "synthetic_only": True,
        "data_role": "operational_observations_no_targets",
        "partition": "development", "source_clock": "fixed_utc_plus_01_no_dst",
        "source_manifest_sha256": hashlib.sha256(
            (source / "manifest.json").read_bytes()
        ).hexdigest(),
        "claims": {"real_connector_validated": False},
        "modes": {"hospital": {
            "path": "observations/hospital.jsonl.gz", "frontier": ["S0"],
        }},
        "files_sha256": {
            "observations/hospital.jsonl.gz": data_sha, "topology.json": topo_sha,
        },
    }))
    return root


def test_genuine_same_run_export_wires_into_v041_adapter_fixture(tmp_path: Path) -> None:
    truth = truth_archive(tmp_path / "truth")
    observed = observation_archive(tmp_path / "observed", truth)
    action_root = tmp_path / "actions"
    receipt = export_existing_truth(truth, action_root)
    assert receipt["source_manifest_sha256"] == hashlib.sha256(
        (truth / "manifest.json").read_bytes()
    ).hexdigest()
    assert receipt["coverage"]["hour_intervals"] == 48
    assert receipt["training"] is False
    _, _, _, partition, provenance = read_sources(observed, action_root, "S0")
    assert partition == "development"
    assert provenance["same_run_asserted_by_export_manifests"] is True
    spec = make_v041_synthetic_spec()
    spec["history_steps"] = 3
    stage1 = SimpleNamespace(
        latent_dim=128, rssm_deter_dim=256, rssm_stoch_dim=32,
        action_dim=4, encoder_max_steps=512,
    )
    built = build_from_archives(
        observed_root=observed, action_root=action_root,
        entity_id="S0", spec=spec,
        origin=clock(12), label_cutoff=clock(37), max_age_hours=3,
        stage1=stage1,
    )
    assert built["provenance"]["s0b_four_channel_binding"]["rssm_action_dim"] == 4
    assert len(built["actions_context"][0][0]) == 4
    assert built["actions_context"][0][0][2] == 1.0  # 09:00 staffing action @ 10:00
    assert built["actions_context"][0][1] == [0.0] * 4
    assert built["supervision_alignment"]["training_loss_authorized"] is False
    assert built["forward_executed"] is False
    assert built["training_executed"] is False
    with pytest.raises(FileExistsError):
        export_existing_truth(truth, action_root)


def test_source_hash_tampering_fails_before_export(tmp_path: Path) -> None:
    truth = truth_archive(tmp_path / "truth")
    with (truth / "truth/events.jsonl.gz").open("ab") as out:
        out.write(b"tamper")
    with pytest.raises(ValueError, match="frozen manifest"):
        export_existing_truth(truth, tmp_path / "actions")


def test_truth_holdout_archive_is_never_read(tmp_path: Path) -> None:
    truth = truth_archive(tmp_path / "truth")
    path = truth / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["partition"] = "test"
    path.write_text(json.dumps(manifest))
    with pytest.raises(PermissionError, match="Reserved"):
        export_existing_truth(truth, tmp_path / "actions")
