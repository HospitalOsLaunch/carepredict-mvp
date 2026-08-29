"""Deterministic single-candidate training and rollout evaluation for M1B."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import time
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import numpy.typing as npt

from hfwm.contracts.interfaces import StateEncoderInput, TokenBatch
from hfwm.models.local import JointDynamicsConfig, LocalJointDynamicsModel
from p0d import canonical_json_bytes, sha256_json

FloatArray = npt.NDArray[np.float64]
SCHEMA_VERSION = "hfwm.r0.minimal-candidate-training.v1"
CHECKPOINT_SCHEMA = "hfwm.r0.local-joint-checkpoint.v1"
METRICS_SCHEMA = "hfwm.r0.minimal-candidate-metrics.v1"
MANIFEST_SCHEMA = "hfwm.r0.minimal-candidate-manifest.v1"
SMOKE_TEST_COMMAND = (
    "PYTHONPATH=src python scripts/hfwm/train_minimal_candidate.py "
    "--config configs/hfwm/r0_m1b_minimal.yaml "
    "--output-dir artifacts/hfwm-r0/backbone"
)
REPRODUCIBILITY_TEST_COMMAND = (
    "PYTHONPATH=src pytest -p no:cacheprovider "
    "tests/hfwm/candidate/test_training.py -q"
)


class CandidateTrainingError(ValueError):
    """The frozen M1B candidate contract cannot be executed faithfully."""


@dataclass(frozen=True, slots=True)
class MinimalCandidateConfig:
    candidate_id: str
    model_family: str
    dataset_path: str
    expected_dataset_hash: str
    site_id: str
    target_order: tuple[str, ...]
    step_hours: int
    rollout_steps: int
    seed: int
    ridge_alpha: float
    belief_update_rate: float
    recording_dim: int
    max_parameters: int
    max_train_episodes: int
    cpu_seconds_budget: int
    uncertainty: str
    hyperparameter_search: bool
    dataset_reduction_allowed_once_on_timeout: bool

    @classmethod
    def load(cls, path: Path) -> MinimalCandidateConfig:
        """Load the frozen JSON-compatible YAML config without implicit defaults."""

        raw: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
            raise CandidateTrainingError("unsupported minimal-candidate config")
        targets = raw.get("target_order")
        if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
            raise CandidateTrainingError("target_order must be a string list")
        try:
            config = cls(
                candidate_id=str(raw["candidate_id"]),
                model_family=str(raw["model_family"]),
                dataset_path=str(raw["dataset_path"]),
                expected_dataset_hash=str(raw["expected_dataset_hash"]),
                site_id=str(raw["site_id"]),
                target_order=tuple(targets),
                step_hours=int(raw["step_hours"]),
                rollout_steps=int(raw["rollout_steps"]),
                seed=int(raw["seed"]),
                ridge_alpha=float(raw["ridge_alpha"]),
                belief_update_rate=float(raw["belief_update_rate"]),
                recording_dim=int(raw["recording_dim"]),
                max_parameters=int(raw["max_parameters"]),
                max_train_episodes=int(raw["max_train_episodes"]),
                cpu_seconds_budget=int(raw["cpu_seconds_budget"]),
                uncertainty=str(raw["uncertainty"]),
                hyperparameter_search=bool(raw["hyperparameter_search"]),
                dataset_reduction_allowed_once_on_timeout=bool(
                    raw["dataset_reduction_allowed_once_on_timeout"]
                ),
            )
        except KeyError as error:
            raise CandidateTrainingError(f"missing config field: {error.args[0]}") from error
        config.validate()
        return config

    def validate(self) -> None:
        if self.model_family != "local_joint_from_scratch":
            raise CandidateTrainingError("M1B permits only the selected local joint family")
        if self.target_order != ("occupancy", "inflow"):
            raise CandidateTrainingError("M1B target order must be occupancy/inflow")
        if self.step_hours != 6 or self.rollout_steps < 2:
            raise CandidateTrainingError("M1B requires 6h steps and a rollout of at least two")
        if self.hyperparameter_search:
            raise CandidateTrainingError("hyperparameter search is forbidden in M1B")
        if self.max_train_episodes < 1 or self.cpu_seconds_budget < 1:
            raise CandidateTrainingError("training budgets must be positive")
        if len(self.expected_dataset_hash) != 64:
            raise CandidateTrainingError("expected_dataset_hash must be SHA-256")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "model_family": self.model_family,
            "dataset_path": self.dataset_path,
            "expected_dataset_hash": self.expected_dataset_hash,
            "site_id": self.site_id,
            "target_order": list(self.target_order),
            "step_hours": self.step_hours,
            "rollout_steps": self.rollout_steps,
            "seed": self.seed,
            "ridge_alpha": self.ridge_alpha,
            "belief_update_rate": self.belief_update_rate,
            "recording_dim": self.recording_dim,
            "max_parameters": self.max_parameters,
            "max_train_episodes": self.max_train_episodes,
            "cpu_seconds_budget": self.cpu_seconds_budget,
            "uncertainty": self.uncertainty,
            "hyperparameter_search": self.hyperparameter_search,
            "dataset_reduction_allowed_once_on_timeout": (
                self.dataset_reduction_allowed_once_on_timeout
            ),
        }


@dataclass(frozen=True, slots=True)
class EpisodeTrajectory:
    episode_id: str
    split: str
    values: FloatArray
    rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class TrainingRun:
    checkpoint: Mapping[str, object]
    metrics: Mapping[str, object]
    manifest: Mapping[str, object]
    model_hash: str

    def export(self, output_dir: Path) -> tuple[Path, ...]:
        output_dir.mkdir(parents=True, exist_ok=True)
        payloads = (
            ("checkpoint.json", self.checkpoint),
            ("metrics.json", self.metrics),
            ("training_manifest.json", self.manifest),
        )
        paths: list[Path] = []
        for name, payload in payloads:
            path = output_dir / name
            path.write_bytes(canonical_json_bytes(payload) + b"\n")
            paths.append(path)
        return tuple(paths)


def _load_dataset(path: Path, expected_hash: str) -> tuple[str, list[dict[str, Any]]]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CandidateTrainingError("dataset must be an object")
    observed_hash = raw.get("dataset_hash")
    payload = {key: value for key, value in raw.items() if key != "dataset_hash"}
    if observed_hash != sha256_json(payload) or observed_hash != expected_hash:
        raise CandidateTrainingError("dataset hash differs from the frozen config")
    rows = raw.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise CandidateTrainingError("dataset rows must be objects")
    return cast(str, observed_hash), cast(list[dict[str, Any]], rows)


def _finite_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateTrainingError(f"{path} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise CandidateTrainingError(f"{path} must be finite")
    return number


def _row_state(row: Mapping[str, Any], section: str, fields: tuple[str, ...]) -> FloatArray:
    raw = row.get(section)
    if not isinstance(raw, Mapping):
        raise CandidateTrainingError(f"row.{section} must be an object")
    names = (
        "inflow_last_6h" if name == "inflow" and section == "features" else name
        for name in fields
    )
    return np.asarray(
        [_finite_number(raw.get(name), f"row.{section}.{name}") for name in names],
        dtype=np.float64,
    )


def _trajectories(
    rows: list[dict[str, Any]], config: MinimalCandidateConfig
) -> tuple[EpisodeTrajectory, ...]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("site_id") != config.site_id:
            continue
        episode_id = row.get("episode_id")
        if not isinstance(episode_id, str):
            raise CandidateTrainingError("dataset row has no episode_id")
        grouped[episode_id].append(row)
    trajectories: list[EpisodeTrajectory] = []
    for episode_id, members in sorted(grouped.items()):
        ordered = sorted(members, key=lambda row: str(row.get("as_of")))
        splits = {row.get("split") for row in ordered}
        if len(splits) != 1 or not all(isinstance(item, str) for item in splits):
            raise CandidateTrainingError(f"episode crosses splits: {episode_id}")
        states = [_row_state(ordered[0], "features", config.target_order)]
        states.extend(_row_state(row, "targets", config.target_order) for row in ordered)
        if len(states) - 1 < config.rollout_steps:
            raise CandidateTrainingError(f"episode is shorter than rollout: {episode_id}")
        trajectories.append(
            EpisodeTrajectory(
                episode_id=episode_id,
                split=cast(str, next(iter(splits))),
                values=np.stack(states),
                rows=tuple(ordered),
            )
        )
    if not trajectories:
        raise CandidateTrainingError(f"site absent from dataset: {config.site_id}")
    return tuple(trajectories)


def _state_input(values: FloatArray, row: Mapping[str, Any]) -> StateEncoderInput:
    features = row.get("features")
    if not isinstance(features, Mapping):
        raise CandidateTrainingError("row.features must be an object")
    observed = _finite_number(features.get("observed_hours_last_6h"), "observed hours")
    as_of = row.get("as_of")
    example_id = row.get("example_id")
    if not isinstance(as_of, str) or not isinstance(example_id, str):
        raise CandidateTrainingError("row identity is incomplete")
    batch = TokenBatch(
        values=values,
        attention_mask=np.ones_like(values),
        entity_ids=(str(row.get("unit_id")),),
        event_ids=(example_id,),
        available_at=(as_of,),
        provenance=({"dataset_example_id": example_id},),
    )
    return StateEncoderInput(
        observations=batch,
        history=(),
        entity_graph={},
        recording_process={
            "missing_rate": max(0.0, 1.0 - observed / 6.0),
            "observed_fraction": min(1.0, observed / 6.0),
        },
        context={},
        site_metadata={"site_id": str(row.get("site_id"))},
    )


def _metric_summary(
    predictions: FloatArray, actual: FloatArray, uncertainty: FloatArray, targets: tuple[str, ...]
) -> dict[str, object]:
    finite = np.isfinite(predictions) & np.isfinite(uncertainty)
    error = predictions - actual
    absolute = np.abs(error)
    squared = error**2
    interval_hit = np.abs(error) <= 1.6448536269514722 * uncertainty
    return {
        "evaluated_values": int(predictions.size),
        "aggregate_mae": float(np.mean(absolute)),
        "aggregate_rmse": float(np.sqrt(np.mean(squared))),
        "per_target_mae": {
            target: float(np.mean(absolute[..., index]))
            for index, target in enumerate(targets)
        },
        "per_target_rmse": {
            target: float(np.sqrt(np.mean(squared[..., index])))
            for index, target in enumerate(targets)
        },
        "mean_predictive_std": float(np.mean(uncertainty)),
        "interval_90_coverage": float(np.mean(interval_hit)),
        "non_finite_output_rate": float(1.0 - np.mean(finite)),
    }


def _evaluate(
    model: LocalJointDynamicsModel,
    episodes: tuple[EpisodeTrajectory, ...],
    config: MinimalCandidateConfig,
) -> tuple[dict[str, object], dict[str, object]]:
    teacher_predictions: list[FloatArray] = []
    teacher_actual: list[FloatArray] = []
    teacher_uncertainty: list[FloatArray] = []
    rollout_predictions: list[FloatArray] = []
    rollout_actual: list[FloatArray] = []
    rollout_uncertainty: list[FloatArray] = []
    for episode in episodes:
        steps = config.rollout_steps
        actual = episode.values[1 : steps + 1]
        for step in range(steps):
            state = model.infer_state(_state_input(episode.values[step], episode.rows[step]))
            prediction = model.predict_next(state, (), {})
            teacher_predictions.append(np.asarray(prediction.next_state_distribution))
            teacher_actual.append(actual[step])
            teacher_uncertainty.append(np.asarray(prediction.uncertainty))
        initial = model.infer_state(_state_input(episode.values[0], episode.rows[0]))
        rollout = model.rollout(initial, (), {}, horizon_steps=steps)
        rollout_predictions.append(np.asarray(rollout.state_trajectories))
        rollout_actual.append(actual)
        rollout_uncertainty.append(np.asarray(rollout.uncertainty_by_horizon))
    teacher = _metric_summary(
        np.stack(teacher_predictions),
        np.stack(teacher_actual),
        np.stack(teacher_uncertainty),
        config.target_order,
    )
    free_running = _metric_summary(
        np.stack(rollout_predictions),
        np.stack(rollout_actual),
        np.stack(rollout_uncertainty),
        config.target_order,
    )
    free_errors = np.abs(np.stack(rollout_predictions) - np.stack(rollout_actual))
    free_running["per_step_mae"] = [
        float(np.mean(free_errors[:, step, :])) for step in range(config.rollout_steps)
    ]
    free_running["rollout_steps"] = config.rollout_steps
    free_running["free_running"] = True
    return teacher, free_running


def _checkpoint(
    model: LocalJointDynamicsModel, config: MinimalCandidateConfig
) -> dict[str, object]:
    state = model.fitted_state()
    payload: dict[str, object] = {
        "schema_version": CHECKPOINT_SCHEMA,
        "candidate_id": config.candidate_id,
        "model_family": config.model_family,
        "site_id": config.site_id,
        "model_config": {
            "observation_dim": len(config.target_order),
            "recording_dim": config.recording_dim,
            "ridge_alpha": config.ridge_alpha,
            "belief_update_rate": config.belief_update_rate,
            "max_parameters": config.max_parameters,
            "seed": config.seed,
            "occupancy_index": 0,
        },
        "state": {name: value.tolist() for name, value in state.items()},
        "model_hash": model.backbone_hash(),
    }
    return {**payload, "checkpoint_hash": sha256_json(payload)}


def load_candidate_checkpoint(checkpoint: Mapping[str, object]) -> LocalJointDynamicsModel:
    """Restore and identity-check one locally produced M1B checkpoint."""

    payload = {key: value for key, value in checkpoint.items() if key != "checkpoint_hash"}
    if checkpoint.get("checkpoint_hash") != sha256_json(payload):
        raise CandidateTrainingError("checkpoint hash mismatch")
    raw_config = checkpoint.get("model_config")
    raw_state = checkpoint.get("state")
    site_id = checkpoint.get("site_id")
    if not isinstance(raw_config, Mapping) or not isinstance(raw_state, Mapping):
        raise CandidateTrainingError("checkpoint config or state is missing")
    if not isinstance(site_id, str):
        raise CandidateTrainingError("checkpoint site_id is missing")
    config = JointDynamicsConfig(
        observation_dim=int(cast(int, raw_config["observation_dim"])),
        recording_dim=int(cast(int, raw_config["recording_dim"])),
        ridge_alpha=float(cast(float, raw_config["ridge_alpha"])),
        belief_update_rate=float(cast(float, raw_config["belief_update_rate"])),
        max_parameters=int(cast(int, raw_config["max_parameters"])),
        seed=int(cast(int, raw_config["seed"])),
        occupancy_index=int(cast(int, raw_config["occupancy_index"])),
    )
    model = LocalJointDynamicsModel(config).restore_fitted_state(
        coefficient=np.asarray(raw_state["coefficient"], dtype=np.float64),
        residual_variance=np.asarray(raw_state["residual_variance"], dtype=np.float64),
        local_bias=np.asarray(raw_state["local_bias"], dtype=np.float64),
        site_id=site_id,
    )
    if model.backbone_hash() != checkpoint.get("model_hash"):
        raise CandidateTrainingError("restored model hash mismatch")
    return model


def _file_identity(path: Path, root: Path) -> dict[str, object]:
    raw = path.read_bytes()
    try:
        logical_path = path.relative_to(root).as_posix()
    except ValueError:
        logical_path = f"external-config/{path.name}"
    return {
        "path": logical_path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def train_minimal_candidate(
    config: MinimalCandidateConfig,
    *,
    repository_root: Path,
    config_path: Path,
) -> TrainingRun:
    """Fit exactly one ridge candidate and evaluate teacher/free-running paths."""

    start = time.process_time()
    dataset_path = Path(config.dataset_path)
    if not dataset_path.is_absolute():
        dataset_path = repository_root / dataset_path
    dataset_hash, rows = _load_dataset(dataset_path, config.expected_dataset_hash)
    episodes = _trajectories(rows, config)
    by_split = {
        split: tuple(item for item in episodes if item.split == split)
        for split in ("train", "validation", "test")
    }
    if any(not by_split[split] for split in by_split):
        raise CandidateTrainingError("selected site must contain train/validation/test episodes")
    if len(by_split["train"]) > config.max_train_episodes:
        raise CandidateTrainingError("train episodes exceed the frozen budget")
    model_config = JointDynamicsConfig(
        observation_dim=len(config.target_order),
        recording_dim=config.recording_dim,
        ridge_alpha=config.ridge_alpha,
        belief_update_rate=config.belief_update_rate,
        max_parameters=config.max_parameters,
        seed=config.seed,
        occupancy_index=0,
    )
    train_values = np.stack([item.values for item in by_split["train"]])
    model = LocalJointDynamicsModel(model_config).fit(
        site_id=config.site_id, trajectories=train_values
    )
    validation_teacher, validation_rollout = _evaluate(
        model, by_split["validation"], config
    )
    test_teacher, test_rollout = _evaluate(model, by_split["test"], config)
    elapsed = time.process_time() - start
    if elapsed > config.cpu_seconds_budget:
        raise CandidateTrainingError("training exceeded the declared CPU-time budget")
    checkpoint = _checkpoint(model, config)
    metrics_payload: dict[str, object] = {
        "schema_version": METRICS_SCHEMA,
        "candidate_id": config.candidate_id,
        "dataset_hash": dataset_hash,
        "teacher_forcing": {
            "validation": validation_teacher,
            "test": test_teacher,
        },
        "free_running": {
            "validation": validation_rollout,
            "test": test_rollout,
        },
        "non_finite_output_rate": max(
            _finite_number(
                validation_teacher["non_finite_output_rate"], "validation teacher rate"
            ),
            _finite_number(test_teacher["non_finite_output_rate"], "test teacher rate"),
            _finite_number(
                validation_rollout["non_finite_output_rate"], "validation rollout rate"
            ),
            _finite_number(test_rollout["non_finite_output_rate"], "test rollout rate"),
        ),
    }
    metrics = {
        **metrics_payload,
        "metrics_hash": sha256_json(metrics_payload),
        "training_cpu_seconds": elapsed,
    }
    code_paths = (
        repository_root / "src/hfwm/models/local/model.py",
        repository_root / "src/hfwm/candidate/training.py",
        repository_root / "scripts/hfwm/train_minimal_candidate.py",
        config_path,
    )
    config_hash = sha256_json(config.to_dict())
    manifest_payload: dict[str, object] = {
        "schema_version": MANIFEST_SCHEMA,
        "candidate_id": config.candidate_id,
        "candidate_status": "EXPERIMENTAL_NOT_A_DEMONSTRATED_WORLD_MODEL",
        "dataset_hash": dataset_hash,
        "dataset_path": config.dataset_path,
        "config_hash": config_hash,
        "seed": config.seed,
        "model_family": config.model_family,
        "model_hash": model.backbone_hash(),
        "checkpoint_hash": checkpoint["checkpoint_hash"],
        "metrics_hash": metrics["metrics_hash"],
        "parameter_count": model.parameter_count,
        "train_episode_count": len(by_split["train"]),
        "validation_episode_count": len(by_split["validation"]),
        "test_episode_count": len(by_split["test"]),
        "rollout_steps": config.rollout_steps,
        "step_hours": config.step_hours,
        "targets": list(config.target_order),
        "uncertainty": config.uncertainty,
        "smoke_test_command": SMOKE_TEST_COMMAND,
        "reproducibility_test_command": REPRODUCIBILITY_TEST_COMMAND,
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "code": [_file_identity(path.resolve(strict=True), repository_root) for path in code_paths],
        "hyperparameter_search_executed": False,
        "dataset_reduction_executed": False,
    }
    manifest = {**manifest_payload, "manifest_hash": sha256_json(manifest_payload)}
    restored = load_candidate_checkpoint(checkpoint)
    if restored.backbone_hash() != model.backbone_hash():
        raise CandidateTrainingError("checkpoint round-trip changed the model identity")
    return TrainingRun(
        checkpoint=checkpoint,
        metrics=metrics,
        manifest=manifest,
        model_hash=model.backbone_hash(),
    )
