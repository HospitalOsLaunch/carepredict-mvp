from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from hfwm.candidate import (
    MinimalCandidateConfig,
    TrainingRun,
    load_candidate_checkpoint,
    train_minimal_candidate,
)
from hfwm.data_slice import build_point_in_time_data_slice

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _config(
    tmp_path: Path, dataset_hash: str, dataset_path: Path
) -> tuple[Path, MinimalCandidateConfig]:
    payload = {
        "schema_version": "hfwm.r0.minimal-candidate-training.v1",
        "candidate_id": "hfwm-r0-m1b-test",
        "model_family": "local_joint_from_scratch",
        "dataset_path": dataset_path.as_posix(),
        "expected_dataset_hash": dataset_hash,
        "site_id": "synthetic-site-0-0",
        "target_order": ["occupancy", "inflow"],
        "step_hours": 6,
        "rollout_steps": 4,
        "seed": 1729,
        "ridge_alpha": 1.0,
        "belief_update_rate": 0.25,
        "recording_dim": 2,
        "max_parameters": 100,
        "max_train_episodes": 14,
        "cpu_seconds_budget": 60,
        "uncertainty": "residual_gaussian_90pct_interval",
        "hyperparameter_search": False,
        "dataset_reduction_allowed_once_on_timeout": True,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, MinimalCandidateConfig.load(path)


def _run(tmp_path: Path) -> TrainingRun:
    data_dir = tmp_path / "data"
    data = build_point_in_time_data_slice()
    data.export(data_dir)
    config_path, config = _config(tmp_path, data.dataset_hash, data_dir / "dataset.json")
    return train_minimal_candidate(
        config,
        repository_root=REPOSITORY_ROOT,
        config_path=config_path,
    )


def test_candidate_training_is_reproducible(tmp_path: Path) -> None:
    first = _run(tmp_path)
    second = _run(tmp_path)

    assert first.model_hash == second.model_hash
    assert first.checkpoint == second.checkpoint
    first_metrics = dict(first.metrics)
    second_metrics = dict(second.metrics)
    first_metrics.pop("training_cpu_seconds")
    second_metrics.pop("training_cpu_seconds")
    assert first_metrics == second_metrics


def test_candidate_has_joint_uncertain_free_running_rollout(tmp_path: Path) -> None:
    result = _run(tmp_path)
    free_running = result.metrics["free_running"]
    assert isinstance(free_running, dict)
    test_metrics = free_running["test"]
    assert isinstance(test_metrics, dict)

    assert test_metrics["free_running"] is True
    assert test_metrics["rollout_steps"] >= 2
    assert test_metrics["mean_predictive_std"] > 0.0
    assert set(test_metrics["per_target_mae"]) == {"occupancy", "inflow"}
    assert result.metrics["non_finite_output_rate"] == 0.0


def test_checkpoint_round_trip_preserves_model_identity(tmp_path: Path) -> None:
    result = _run(tmp_path)
    restored = load_candidate_checkpoint(result.checkpoint)
    state = restored.fitted_state()

    assert restored.backbone_hash() == result.model_hash
    assert all(np.all(np.isfinite(array)) for array in state.values())
