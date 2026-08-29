"""Execute the bounded M2B bake-off against the frozen M1 point-in-time slice."""

from __future__ import annotations

import hashlib
import json
import math
import pickle
import random
import time
import traceback
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeAlias, cast

import numpy as np
import numpy.typing as npt
from sklearn.ensemble import HistGradientBoostingRegressor  # type: ignore[import-untyped]

from hfwm.candidate.training import MinimalCandidateConfig
from hfwm.contracts import StateEncoderInput, TokenBatch
from hfwm.evaluation.canonical import canonical_json_bytes, semantic_hash
from hfwm.evaluation.preregistration import require_valid_preregistration
from hfwm.models.local import JointDynamicsConfig, LocalJointDynamicsModel
from hfwm.models.mechanistic import MechanisticConfig, MechanisticQueueSemiMarkov
from hfwm.models.shared import SharedHFWMModel
from p0d import sha256_json

FloatArray: TypeAlias = npt.NDArray[np.float64]

FROZEN_MANIFEST_SHA256 = "0115779941afea37605a0e221e8f82bf2494349aee92fdb339455dc572a334e2"
FROZEN_BUNDLE_SHA256 = "384c4e5ae707edabcf19523b5fd782f4301ca405722aa71fab31d90e141c37e6"
DATASET_HASH = "64e831ec1a3fbf6fdad2bd0ac716b675619216d3b4c180895ac6acdba2bbb965"
TARGETS = ("occupancy", "inflow")
SEEDS = (1729, 2718, 3141)
STEPS = 4
STEP_HOURS = 6
ARM_IDS = (
    "mechanistic_queue_semimarkov",
    "local_joint_from_scratch",
    "shared_hfwm_multitask",
    "hgbr_cqr",
)


class M2BExecutionError(RuntimeError):
    """The frozen M2B protocol cannot be executed faithfully."""


@dataclass(frozen=True, slots=True)
class Episode:
    episode_id: str
    site_id: str
    split: str
    origins: tuple[datetime, ...]
    states: FloatArray


@dataclass(frozen=True, slots=True)
class Predictions:
    teacher: FloatArray
    rollout: FloatArray
    lower: FloatArray | None = None
    upper: FloatArray | None = None


@dataclass(frozen=True, slots=True)
class FittedArm:
    predict: Callable[[Sequence[Episode]], Predictions]
    model_hash: str
    parameter_report: Mapping[str, object]


def execute_bakeoff(
    *,
    repository_root: Path,
    preregistration_dir: Path,
    output_dir: Path,
    reproduction_command: str,
) -> dict[str, object]:
    """Run every frozen arm/seed once and persist a complete evidence package."""

    root = repository_root.resolve(strict=True)
    output = output_dir.resolve(strict=False)
    if output.exists():
        raise FileExistsError("M2B output directory must not already exist")
    protocol = _authorize(root, preregistration_dir.resolve(strict=True))
    episodes, dataset_file_sha = _load_episodes(Path(protocol["dataset_path"]))
    splits = {
        name: tuple(item for item in episodes if item.split == name)
        for name in ("train", "validation", "test")
    }
    if tuple(len(splits[name]) for name in splits) != (42, 9, 9):
        raise M2BExecutionError("episode split counts differ from the frozen contract")
    train_iqr = _train_iqr(splits["train"])
    budgets = _budgets(protocol["document"])
    raw_runs: list[dict[str, object]] = []
    crashes: list[dict[str, object]] = []
    for seed in SEEDS:
        for arm_id in ARM_IDS:
            started_wall = time.perf_counter()
            started_cpu = time.process_time()
            try:
                fitted = _fit_arm(arm_id, seed, splits["train"], protocol["config"])
                fit_cpu = time.process_time() - started_cpu
                validation = fitted.predict(splits["validation"])
                first_test = fitted.predict(splits["test"])
                repeat_test = fitted.predict(splits["test"])
                intervals = _calibrated_intervals(validation, first_test, splits)
                elapsed_cpu = time.process_time() - started_cpu
                elapsed_wall = time.perf_counter() - started_wall
                result = _run_result(
                    arm_id=arm_id,
                    seed=seed,
                    fitted=fitted,
                    predictions=first_test,
                    repeat_predictions=repeat_test,
                    intervals=intervals,
                    test=splits["test"],
                    train_iqr=train_iqr,
                    fit_cpu=fit_cpu,
                    elapsed_cpu=elapsed_cpu,
                    elapsed_wall=elapsed_wall,
                    budget=budgets[arm_id],
                )
            except Exception as exc:  # preserve every crashed arm/seed
                elapsed_cpu = time.process_time() - started_cpu
                elapsed_wall = time.perf_counter() - started_wall
                trace = traceback.format_exc()
                crash = {
                    "arm_id": arm_id,
                    "seed": seed,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": trace,
                    "traceback_sha256": hashlib.sha256(trace.encode()).hexdigest(),
                    "cpu_seconds": elapsed_cpu,
                    "wall_seconds": elapsed_wall,
                }
                crashes.append(crash)
                result = {
                    "arm_id": arm_id,
                    "seed": seed,
                    "status": "CRASHED",
                    "decision": _crash_decision(arm_id),
                    "crash_sha256": crash["traceback_sha256"],
                    "cpu_seconds": elapsed_cpu,
                    "wall_seconds": elapsed_wall,
                }
            raw_runs.append(result)
    summary = _summarize(raw_runs, train_iqr=train_iqr)
    final_status = _final_status(summary, raw_runs)
    payload: dict[str, object] = {
        "schema_version": "hfwm.r0.m2b-bakeoff-results.v1",
        "protocol_id": protocol["document"]["protocol_id"],
        "frozen_manifest_sha256": FROZEN_MANIFEST_SHA256,
        "frozen_preregistration_bundle_sha256": FROZEN_BUNDLE_SHA256,
        "dataset_hash": DATASET_HASH,
        "dataset_file_sha256": dataset_file_sha,
        "dataset_scope": {
            "synthetic_only": True,
            "real_site_count": 0,
            "train_episodes": 42,
            "validation_episodes": 9,
            "test_episodes": 9,
            "targets": list(TARGETS),
            "step_hours": STEP_HOURS,
            "rollout_steps": STEPS,
        },
        "train_only_iqr": dict(zip(TARGETS, train_iqr.tolist(), strict=True)),
        "runs_per_seed": 1,
        "seeds": list(SEEDS),
        "raw_runs": raw_runs,
        "summary": summary,
        "ablations": {
            "status": "NONE_EXECUTED",
            "reason": "No ablation is explicitly preregistered in the frozen M2A manifest.",
        },
        "generic_tsfm": "EXCLUDED_NOT_EXECUTED",
        "crash_count": len(crashes),
        "reproduction_command": reproduction_command,
        "threshold_changes_after_observation": 0,
        "new_candidates_after_observation": 0,
        "weights_persisted": False,
        "claims": {
            "scope": "RETROSPECTIVE_SYNTHETIC_OBSERVATIONAL_SHADOW_ONLY",
            "foundation_status": "FOUNDATION_EVIDENCE_INSUFFICIENT",
            "action_status": "ACTION_CONDITIONING_NOT_IDENTIFIABLE",
        },
        "final_status": final_status,
    }
    _write_evidence(output, payload, crashes, root)
    return payload


def _authorize(root: Path, preregistration_dir: Path) -> dict[str, Any]:
    manifest_path = preregistration_dir / "HFWM_R0_BAKEOFF.yaml"
    observed_manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if observed_manifest_sha != FROZEN_MANIFEST_SHA256:
        raise M2BExecutionError("M2A manifest hash changed after preregistration")
    validation = require_valid_preregistration(preregistration_dir)
    if validation.manifest.get("manifest_sha256") != FROZEN_BUNDLE_SHA256:
        raise M2BExecutionError("preregistration bundle hash changed after M2A")
    document: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise M2BExecutionError("M2A manifest must be an object")
    expected = {
        "tasks": list(TARGETS),
        "horizons_hours": [STEP_HOURS],
        "rollout_steps": STEPS,
        "seeds": list(SEEDS),
        "results_status": "NOT_EXECUTED",
    }
    for key, value in expected.items():
        if document.get(key) != value:
            raise M2BExecutionError(f"frozen manifest field changed: {key}")
    primary = [item.get("id") for item in document["candidate_families"]]
    final = [item.get("id") for item in document["final_gate_comparators"]]
    if primary + final != list(ARM_IDS):
        raise M2BExecutionError("execution arm registry differs from M2A")
    if document.get("excluded_comparators", [{}])[0].get("id") != "generic_tsfm":
        raise M2BExecutionError("generic TSFM exclusion is missing")
    reference = cast(dict[str, Any], document["m1_references"])
    config_path = (preregistration_dir / reference["candidate_config"]).resolve(strict=True)
    dataset_path = (preregistration_dir / reference["dataset"]).resolve(strict=True)
    config = MinimalCandidateConfig.load(config_path)
    return {
        "document": document,
        "config": config,
        "dataset_path": str(dataset_path),
        "root": root,
    }


def _load_episodes(path: Path) -> tuple[tuple[Episode, ...], str]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("dataset_hash") != DATASET_HASH:
        raise M2BExecutionError("dataset identity differs from M2A")
    payload = {key: value for key, value in raw.items() if key != "dataset_hash"}
    if sha256_json(payload) != DATASET_HASH:
        raise M2BExecutionError("dataset semantic hash mismatch")
    rows = raw.get("rows")
    if not isinstance(rows, list) or len(rows) != 240:
        raise M2BExecutionError("dataset row count differs from M2A")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw_row in rows:
        if not isinstance(raw_row, dict) or not isinstance(raw_row.get("episode_id"), str):
            raise M2BExecutionError("malformed dataset row")
        grouped[raw_row["episode_id"]].append(raw_row)
    episodes: list[Episode] = []
    for episode_id, members in sorted(grouped.items()):
        ordered = sorted(members, key=lambda item: str(item["as_of"]))
        splits = {str(item["split"]) for item in ordered}
        sites = {str(item["site_id"]) for item in ordered}
        if len(ordered) != STEPS or len(splits) != 1 or len(sites) != 1:
            raise M2BExecutionError("episode shape, split or site violates M2A")
        initial = _row_state(ordered[0], "features")
        states = np.stack([initial, *(_row_state(row, "targets") for row in ordered)])
        episodes.append(
            Episode(
                episode_id=episode_id,
                site_id=next(iter(sites)),
                split=next(iter(splits)),
                origins=tuple(_parse_time(str(row["as_of"])) for row in ordered),
                states=states,
            )
        )
    if len(episodes) != 60:
        raise M2BExecutionError("episode count differs from M2A")
    return tuple(episodes), hashlib.sha256(path.read_bytes()).hexdigest()


def _row_state(row: Mapping[str, Any], section: str) -> FloatArray:
    values = row.get(section)
    if not isinstance(values, Mapping):
        raise M2BExecutionError(f"row.{section} is missing")
    inflow_key = "inflow_last_6h" if section == "features" else "inflow"
    raw = (values.get("occupancy"), values.get(inflow_key))
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in raw):
        raise M2BExecutionError(f"row.{section} contains a non-numeric target")
    result = np.asarray(raw, dtype=np.float64)
    if not np.all(np.isfinite(result)):
        raise M2BExecutionError(f"row.{section} contains non-finite values")
    return result


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _train_iqr(train: Sequence[Episode]) -> FloatArray:
    targets = np.concatenate([episode.states[1:] for episode in train], axis=0)
    iqr = np.quantile(targets, 0.75, axis=0) - np.quantile(targets, 0.25, axis=0)
    if np.any(iqr <= 0.0):
        raise M2BExecutionError("train-only target IQR is zero")
    return cast(FloatArray, iqr)


def _budgets(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    items = [*document["candidate_families"], *document["final_gate_comparators"]]
    return {str(item["id"]): cast(dict[str, Any], item) for item in items}


def _model_config(config: MinimalCandidateConfig, seed: int) -> JointDynamicsConfig:
    return JointDynamicsConfig(
        observation_dim=2,
        recording_dim=config.recording_dim,
        ridge_alpha=config.ridge_alpha,
        belief_update_rate=config.belief_update_rate,
        max_parameters=config.max_parameters,
        seed=seed,
    )


def _fit_arm(
    arm_id: str,
    seed: int,
    train: Sequence[Episode],
    config: MinimalCandidateConfig,
) -> FittedArm:
    if arm_id == "mechanistic_queue_semimarkov":
        mechanistic_model = MechanisticQueueSemiMarkov(MechanisticConfig(step_hours=6.0))
        return FittedArm(
            predict=lambda rows: _predict_mechanistic(mechanistic_model, rows),
            model_hash=cast(str, mechanistic_model.identity.artifact_hash),
            parameter_report={"learned_parameters": 0, "data_fit_constants": False},
        )
    if arm_id == "local_joint_from_scratch":
        by_site: dict[str, list[Episode]] = defaultdict(list)
        for episode in train:
            by_site[episode.site_id].append(episode)
        models = {
            site: LocalJointDynamicsModel(_model_config(config, seed)).fit(
                site_id=site,
                trajectories=np.stack([episode.states for episode in rows]),
            )
            for site, rows in sorted(by_site.items())
        }
        model_hash = semantic_hash(
            {site: model.backbone_hash() for site, model in sorted(models.items())}
        )
        return FittedArm(
            predict=lambda rows: _predict_learned(models, rows),
            model_hash=model_hash,
            parameter_report={
                "per_site_parameters": 18,
                "site_model_count": len(models),
                "aggregate_parameters": 18 * len(models),
            },
        )
    if arm_id == "shared_hfwm_multitask":
        by_site = defaultdict(list)
        for episode in train:
            by_site[episode.site_id].append(episode)
        shared_model = SharedHFWMModel(_model_config(config, seed)).pretrain(
            trajectories_by_site={
                site: np.stack([episode.states for episode in rows])
                for site, rows in sorted(by_site.items())
            }
        )
        return FittedArm(
            predict=lambda rows: _predict_learned({"*": shared_model}, rows),
            model_hash=shared_model.backbone_hash(),
            parameter_report={
                "shared_parameters": shared_model.parameter_count,
                "pretraining_site_count": shared_model.pretraining_site_count,
                "site_adaptation": "NONE",
            },
        )
    if arm_id == "hgbr_cqr":
        return _fit_hgbr(train, seed)
    raise M2BExecutionError(f"unknown frozen arm: {arm_id}")


def _state_input(values: FloatArray, episode: Episode, step: int) -> StateEncoderInput:
    instant = episode.origins[min(step, len(episode.origins) - 1)].isoformat()
    batch = TokenBatch(
        values=values,
        attention_mask=np.ones_like(values),
        entity_ids=(episode.site_id,),
        event_ids=(f"{episode.episode_id}:{step}",),
        available_at=(instant,),
        provenance=({"episode_id": episode.episode_id, "step": step},),
    )
    return StateEncoderInput(
        observations=batch,
        history=(),
        entity_graph={},
        recording_process={"missing_rate": 0.0, "observed_fraction": 1.0},
        context={},
        site_metadata={"site_id": episode.site_id},
    )


def _predict_learned(
    models: Mapping[str, LocalJointDynamicsModel], episodes: Sequence[Episode]
) -> Predictions:
    teachers: list[FloatArray] = []
    rollouts: list[FloatArray] = []
    for episode in episodes:
        model = models.get(episode.site_id, models.get("*"))
        if model is None:
            raise M2BExecutionError(f"no learned model for site {episode.site_id}")
        teacher = []
        for step in range(STEPS):
            state = model.infer_state(_state_input(episode.states[step], episode, step))
            teacher.append(np.asarray(model.predict_next(state, (), {}).next_state_distribution))
        initial = model.infer_state(_state_input(episode.states[0], episode, 0))
        rollout = model.rollout(initial, (), {}, horizon_steps=STEPS)
        teachers.append(np.stack(teacher))
        rollouts.append(np.asarray(rollout.state_trajectories, dtype=np.float64))
    return Predictions(teacher=np.stack(teachers), rollout=np.stack(rollouts))


def _mechanistic_input(values: FloatArray, episode: Episode, step: int) -> StateEncoderInput:
    instant = episode.origins[min(step, len(episode.origins) - 1)].isoformat()
    batch = TokenBatch(
        values={"occupancy": float(values[0]), "inflow": float(values[1]) / 6.0},
        attention_mask={"occupancy": True, "inflow": True},
        entity_ids=(episode.site_id,),
        event_ids=(f"{episode.episode_id}:{step}",),
        available_at=(instant,),
        provenance=({"episode_id": episode.episode_id, "step": step},),
    )
    return StateEncoderInput(
        observations=batch,
        history=(),
        entity_graph={},
        recording_process={},
        context={},
        site_metadata={"site_id": episode.site_id},
    )


def _mechanistic_vector(payload: object) -> FloatArray:
    if not isinstance(payload, Mapping):
        raise M2BExecutionError("mechanistic rollout state is not a mapping")
    return np.asarray(
        [float(payload["occupancy"]), float(payload["inflow"]) * 6.0],
        dtype=np.float64,
    )


def _predict_mechanistic(
    model: MechanisticQueueSemiMarkov, episodes: Sequence[Episode]
) -> Predictions:
    teachers: list[FloatArray] = []
    rollouts: list[FloatArray] = []
    for episode in episodes:
        teacher = []
        for step in range(STEPS):
            state = model.infer_state(_mechanistic_input(episode.states[step], episode, step))
            teacher.append(
                _mechanistic_vector(model.predict_next(state, (), {}).next_state_distribution)
            )
        initial = model.infer_state(_mechanistic_input(episode.states[0], episode, 0))
        rollout = model.rollout(initial, (), {}, horizon_steps=STEPS)
        teachers.append(np.stack(teacher))
        trajectory = cast(Sequence[object], rollout.state_trajectories)
        rollouts.append(np.stack([_mechanistic_vector(row) for row in trajectory]))
    return Predictions(teacher=np.stack(teachers), rollout=np.stack(rollouts))


def _hgbr_features(state: FloatArray, instant: datetime) -> FloatArray:
    hour = 2.0 * math.pi * (instant.hour + instant.minute / 60.0) / 24.0
    weekday = 2.0 * math.pi * instant.weekday() / 7.0
    return np.asarray(
        [state[0], state[1], math.sin(hour), math.cos(hour), math.sin(weekday), math.cos(weekday)],
        dtype=np.float64,
    )


def _fit_hgbr(train: Sequence[Episode], seed: int) -> FittedArm:
    design = np.stack(
        [_hgbr_features(ep.states[step], ep.origins[step]) for ep in train for step in range(STEPS)]
    )
    labels = np.stack([ep.states[step + 1] for ep in train for step in range(STEPS)])
    models: dict[tuple[int, float], HistGradientBoostingRegressor] = {}
    for target in range(len(TARGETS)):
        for quantile in (0.05, 0.5, 0.95):
            model = HistGradientBoostingRegressor(
                loss="quantile",
                quantile=quantile,
                max_iter=64,
                learning_rate=0.05,
                l2_regularization=0.01,
                max_leaf_nodes=15,
                min_samples_leaf=5,
                max_bins=64,
                early_stopping=False,
                random_state=seed,
            )
            model.fit(design, labels[:, target])
            models[(target, quantile)] = model

    def predict(episodes: Sequence[Episode]) -> Predictions:
        teacher_rows: list[FloatArray] = []
        rollout_rows: list[FloatArray] = []
        lower_rows: list[FloatArray] = []
        upper_rows: list[FloatArray] = []
        for episode in episodes:
            teacher = []
            for step in range(STEPS):
                features = _hgbr_features(episode.states[step], episode.origins[step])[None, :]
                teacher.append(
                    np.asarray([models[(target, 0.5)].predict(features)[0] for target in range(2)])
                )
            current = episode.states[0].copy()
            rollout = []
            lowers = []
            uppers = []
            for step in range(STEPS):
                instant = episode.origins[0] + timedelta(hours=STEP_HOURS * step)
                features = _hgbr_features(current, instant)[None, :]
                low = np.asarray(
                    [models[(target, 0.05)].predict(features)[0] for target in range(2)]
                )
                median = np.asarray(
                    [models[(target, 0.5)].predict(features)[0] for target in range(2)]
                )
                high = np.asarray(
                    [models[(target, 0.95)].predict(features)[0] for target in range(2)]
                )
                ordered = np.sort(np.stack((low, median, high)), axis=0)
                current = np.maximum(0.0, ordered[1])
                rollout.append(current.copy())
                lowers.append(np.maximum(0.0, ordered[0]))
                uppers.append(np.maximum(0.0, ordered[2]))
            teacher_rows.append(np.maximum(0.0, np.stack(teacher)))
            rollout_rows.append(np.stack(rollout))
            lower_rows.append(np.stack(lowers))
            upper_rows.append(np.stack(uppers))
        return Predictions(
            teacher=np.stack(teacher_rows),
            rollout=np.stack(rollout_rows),
            lower=np.stack(lower_rows),
            upper=np.stack(upper_rows),
        )

    leaf_count = 0
    for model in models.values():
        for iteration in getattr(model, "_predictors", []):
            for predictor in iteration:
                nodes = getattr(predictor, "nodes", None)
                if nodes is not None and "is_leaf" in nodes.dtype.names:
                    leaf_count += int(np.sum(nodes["is_leaf"]))
    serialized_bytes = len(pickle.dumps(models, protocol=pickle.HIGHEST_PROTOCOL))
    return FittedArm(
        predict=predict,
        model_hash=semantic_hash(
            {
                "seed": seed,
                "train_hash": semantic_hash(labels.tolist()),
                "config": "frozen-hgbr-cqr",
            }
        ),
        parameter_report={
            "model_count": len(models),
            "tree_leaf_count": leaf_count,
            "serialized_model_bytes": serialized_bytes,
            "parity_claim": False,
            "hyperparameter_search": False,
            "repair_scope": "EXACT_M1_ROWS_LEAKAGE_INTEGRITY_REPRODUCIBILITY_ONLY",
        },
    )


def _truth(episodes: Sequence[Episode]) -> FloatArray:
    return np.stack([episode.states[1:] for episode in episodes])


def _higher_quantile(values: FloatArray, coverage: float = 0.9) -> FloatArray:
    count = values.shape[0]
    level = min(1.0, math.ceil((count + 1) * coverage) / count)
    return cast(FloatArray, np.quantile(values, level, axis=0, method="higher"))


def _calibrated_intervals(
    validation: Predictions,
    test: Predictions,
    splits: Mapping[str, Sequence[Episode]],
) -> tuple[FloatArray, FloatArray, FloatArray]:
    validation_truth = _truth(splits["validation"])
    if validation.lower is not None and validation.upper is not None:
        scores = np.maximum(
            validation.lower - validation_truth,
            validation_truth - validation.upper,
        )
        qhat = np.maximum(0.0, _higher_quantile(scores))
        assert test.lower is not None and test.upper is not None
        lower = np.maximum(0.0, test.lower - qhat)
        upper = test.upper + qhat
    else:
        qhat = _higher_quantile(np.abs(validation.rollout - validation_truth))
        lower = np.maximum(0.0, test.rollout - qhat)
        upper = test.rollout + qhat
    return lower, upper, qhat


def _metric_payload(
    predictions: Predictions,
    intervals: tuple[FloatArray, FloatArray, FloatArray],
    test: Sequence[Episode],
    train_iqr: FloatArray,
) -> dict[str, object]:
    actual = _truth(test)
    teacher_error = predictions.teacher - actual
    rollout_error = predictions.rollout - actual
    normalized = np.abs(rollout_error) / train_iqr
    teacher_normalized = np.abs(teacher_error) / train_iqr
    lower, upper, qhat = intervals
    coverage = (actual >= lower) & (actual <= upper)
    per_episode = np.mean(normalized, axis=(1, 2))
    target_mae = np.mean(np.abs(rollout_error), axis=(0, 1))
    target_normalized = np.mean(normalized, axis=(0, 1))
    cells = {
        f"{target}@step{step + 1}": {
            "mae": float(np.mean(np.abs(rollout_error[:, step, target_index]))),
            "rmse": float(np.sqrt(np.mean(rollout_error[:, step, target_index] ** 2))),
            "normalized_mae": float(np.mean(normalized[:, step, target_index])),
            "coverage_90": float(np.mean(coverage[:, step, target_index])),
            "mean_interval_width_90": float(np.mean((upper - lower)[:, step, target_index])),
        }
        for target_index, target in enumerate(TARGETS)
        for step in range(STEPS)
    }
    return {
        "aggregate_normalized_mae": float(np.mean(normalized)),
        "teacher_forcing_normalized_mae": float(np.mean(teacher_normalized)),
        "rollout_drift_ratio": float(np.mean(normalized) / max(np.mean(teacher_normalized), 1e-12)),
        "per_target_mae": dict(zip(TARGETS, target_mae.tolist(), strict=True)),
        "per_target_normalized_mae": dict(zip(TARGETS, target_normalized.tolist(), strict=True)),
        "calibration_coverage_90": float(np.mean(coverage)),
        "mean_interval_width_90": float(np.mean(upper - lower)),
        "calibration_qhat_per_target_step": qhat.tolist(),
        "non_finite_output_rate": float(1.0 - np.mean(np.isfinite(predictions.rollout))),
        "non_negative_output_violation_rate": float(np.mean(predictions.rollout < 0.0)),
        "capacity_constraint_status": "INCONCLUSIVE_NOT_EXPOSED_IN_FROZEN_M1_ROWS",
        "conservation_constraint_status": "INCONCLUSIVE_DISCHARGES_NOT_A_FROZEN_M1_TARGET",
        "per_episode_primary": {
            episode.episode_id: float(value)
            for episode, value in zip(test, per_episode, strict=True)
        },
        "cells": cells,
    }


def _run_result(
    *,
    arm_id: str,
    seed: int,
    fitted: FittedArm,
    predictions: Predictions,
    repeat_predictions: Predictions,
    intervals: tuple[FloatArray, FloatArray, FloatArray],
    test: Sequence[Episode],
    train_iqr: FloatArray,
    fit_cpu: float,
    elapsed_cpu: float,
    elapsed_wall: float,
    budget: Mapping[str, Any],
) -> dict[str, object]:
    prediction_bytes = canonical_json_bytes(predictions.rollout.tolist())
    repeat_bytes = canonical_json_bytes(repeat_predictions.rollout.tolist())
    metrics = _metric_payload(predictions, intervals, test, train_iqr)
    budget_ok = elapsed_cpu <= float(budget["cpu_seconds_max_per_seed"])
    constraint_ok = (
        float(cast(float, metrics["non_finite_output_rate"])) == 0.0
        and float(cast(float, metrics["non_negative_output_violation_rate"])) <= 0.01
    )
    return {
        "arm_id": arm_id,
        "seed": seed,
        "status": "EXECUTED" if budget_ok and constraint_ok else "KILLED",
        "decision": "CONTINUE_TO_AGGREGATION"
        if budget_ok and constraint_ok
        else "KILL_AFFECTED_ARM",
        "model_hash": fitted.model_hash,
        "parameter_report": dict(fitted.parameter_report),
        "metrics": metrics,
        "fit_cpu_seconds": fit_cpu,
        "cpu_seconds": elapsed_cpu,
        "wall_seconds": elapsed_wall,
        "latency_ms_per_test_episode": elapsed_wall * 1000.0 / len(test),
        "cpu_budget_seconds": int(budget["cpu_seconds_max_per_seed"]),
        "cpu_budget_respected": budget_ok,
        "accelerator_hours": 0.0,
        "prediction_hash": hashlib.sha256(prediction_bytes).hexdigest(),
        "repeat_prediction_hash": hashlib.sha256(repeat_bytes).hexdigest(),
        "inference_repeat_hash_match": prediction_bytes == repeat_bytes,
        "training_reproducibility": "NOT_RETRAINED_RUNS_PER_SEED_1",
        "raw_test": {
            "episode_ids": [episode.episode_id for episode in test],
            "truth": _truth(test).tolist(),
            "teacher_forcing_predictions": predictions.teacher.tolist(),
            "free_running_predictions": predictions.rollout.tolist(),
            "interval_90_lower": intervals[0].tolist(),
            "interval_90_upper": intervals[1].tolist(),
        },
    }


def _bootstrap_ci(values: Mapping[str, float]) -> list[float]:
    ordered = [values[key] for key in sorted(values)]
    generator = random.Random(8675309)
    draws = [
        float(np.mean([ordered[generator.randrange(len(ordered))] for _ in ordered]))
        for _ in range(2000)
    ]
    return [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))]


def _summarize(
    raw_runs: Sequence[Mapping[str, object]], *, train_iqr: FloatArray
) -> dict[str, object]:
    del train_iqr
    executed: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for run in raw_runs:
        if run.get("status") == "EXECUTED":
            executed[str(run["arm_id"])].append(run)
    arms: dict[str, dict[str, Any]] = {}
    per_episode_by_arm: dict[str, dict[str, float]] = {}
    for arm_id in ARM_IDS:
        runs = executed.get(arm_id, [])
        if len(runs) != len(SEEDS):
            arms[arm_id] = {
                "status": "INCOMPLETE",
                "executed_seeds": len(runs),
                "decision": _crash_decision(arm_id),
            }
            continue
        metrics = [cast(Mapping[str, Any], run["metrics"]) for run in runs]
        episode_ids = sorted(cast(Mapping[str, float], metrics[0]["per_episode_primary"]))
        per_episode = {
            episode_id: float(
                np.mean([metric["per_episode_primary"][episode_id] for metric in metrics])
            )
            for episode_id in episode_ids
        }
        per_episode_by_arm[arm_id] = per_episode
        primary_by_seed = [float(metric["aggregate_normalized_mae"]) for metric in metrics]
        arms[arm_id] = {
            "status": "EXECUTED",
            "primary_metric_mean": float(np.mean(primary_by_seed)),
            "primary_metric_ci95_episode_bootstrap": _bootstrap_ci(per_episode),
            "primary_metric_by_seed": dict(zip(map(str, SEEDS), primary_by_seed, strict=True)),
            "primary_metric_std_between_seeds": float(np.std(primary_by_seed)),
            "calibration_coverage_90_mean": float(
                np.mean([metric["calibration_coverage_90"] for metric in metrics])
            ),
            "mean_interval_width_90": float(
                np.mean([metric["mean_interval_width_90"] for metric in metrics])
            ),
            "rollout_drift_ratio_mean": float(
                np.mean([metric["rollout_drift_ratio"] for metric in metrics])
            ),
            "non_finite_output_rate_max": max(
                float(metric["non_finite_output_rate"]) for metric in metrics
            ),
            "non_negative_output_violation_rate_max": max(
                float(metric["non_negative_output_violation_rate"]) for metric in metrics
            ),
            "cpu_seconds_total": float(np.sum([run["cpu_seconds"] for run in runs])),
            "wall_seconds_total": float(np.sum([run["wall_seconds"] for run in runs])),
            "latency_ms_per_test_episode_mean": float(
                np.mean([float(cast(float, run["latency_ms_per_test_episode"])) for run in runs])
            ),
            "inference_repeat_hash_match_rate": float(
                np.mean([bool(run["inference_repeat_hash_match"]) for run in runs])
            ),
            "per_target_normalized_mae": {
                target: float(
                    np.mean([metric["per_target_normalized_mae"][target] for metric in metrics])
                )
                for target in TARGETS
            },
        }
    comparison: dict[str, object] = {"status": "INCONCLUSIVE"}
    if all(arm in per_episode_by_arm for arm in ARM_IDS[:3]):
        controls = ARM_IDS[:2]
        strongest = min(
            controls,
            key=lambda arm: float(cast(Mapping[str, Any], arms[arm])["primary_metric_mean"]),
        )
        shared_values = per_episode_by_arm["shared_hfwm_multitask"]
        control_values = per_episode_by_arm[strongest]
        gains = {
            key: (control_values[key] - shared_values[key]) / max(control_values[key], 1e-12)
            for key in sorted(shared_values)
        }
        gain_by_seed = []
        for seed_index in range(len(SEEDS)):
            control = cast(Mapping[str, Any], arms[strongest])["primary_metric_by_seed"][
                str(SEEDS[seed_index])
            ]
            shared = cast(Mapping[str, Any], arms["shared_hfwm_multitask"])[
                "primary_metric_by_seed"
            ][str(SEEDS[seed_index])]
            gain_by_seed.append((float(control) - float(shared)) / max(float(control), 1e-12))
        target_regressions = {
            target: (
                float(
                    cast(Mapping[str, Any], arms["shared_hfwm_multitask"])[
                        "per_target_normalized_mae"
                    ][target]
                )
                - float(
                    cast(Mapping[str, Any], arms[strongest])["per_target_normalized_mae"][target]
                )
            )
            / max(
                float(
                    cast(Mapping[str, Any], arms[strongest])["per_target_normalized_mae"][target]
                ),
                1e-12,
            )
            for target in TARGETS
        }
        gain_mean = float(np.mean(list(gains.values())))
        gain_ci = _bootstrap_ci(gains)
        stable = sum(value > 0.0 for value in gain_by_seed)
        critical_regression = any(value > 0.05 for value in target_regressions.values())
        go = gain_mean >= 0.05 and gain_ci[0] > 0.0 and stable >= 3 and not critical_regression
        if critical_regression:
            decision = "REJECT_SHARED_CANDIDATE_FOR_M2"
        elif go:
            decision = "ELIGIBLE_FOR_NEXT_LOCAL_REVIEW_ONLY"
        else:
            decision = "WITHHOLD_SHARED_ADVANTAGE_CLAIM"
        comparison = {
            "status": "EXECUTED",
            "strongest_primary_control": strongest,
            "shared_relative_gain_mean": gain_mean,
            "shared_relative_gain_ci95_paired_episode_bootstrap": gain_ci,
            "shared_relative_gain_by_seed": dict(zip(map(str, SEEDS), gain_by_seed, strict=True)),
            "directionally_stable_seed_count": stable,
            "per_target_regression": target_regressions,
            "thresholds": {
                "relative_gain_min": 0.05,
                "paired_ci_lower_strictly_positive": True,
                "directionally_stable_seeds_min": 3,
                "per_target_regression_max": 0.05,
            },
            "decision": decision,
        }
        arms["shared_hfwm_multitask"]["decision"] = decision
    for arm_id in ("mechanistic_queue_semimarkov", "local_joint_from_scratch"):
        if arms.get(arm_id, {}).get("status") == "EXECUTED":
            arms[arm_id]["decision"] = "RETAIN_AS_CONTROL"
    if arms.get("hgbr_cqr", {}).get("status") == "EXECUTED":
        arms["hgbr_cqr"]["decision"] = "ELIGIBLE_FROZEN_FINAL_COMPARATOR"
    return {"arms": arms, "primary_comparison": comparison}


def _crash_decision(arm_id: str) -> str:
    if arm_id == "shared_hfwm_multitask":
        return "KILL_AFFECTED_ARM"
    if arm_id == "hgbr_cqr":
        return "MARK_HGBR_CQR_INELIGIBLE_AND_PERSIST_REASON"
    return "PRIMARY_COMPARISON_INCONCLUSIVE"


def _final_status(summary: Mapping[str, object], raw_runs: Sequence[Mapping[str, object]]) -> str:
    shared_runs = [run for run in raw_runs if run.get("arm_id") == "shared_hfwm_multitask"]
    if any(run.get("status") in {"CRASHED", "KILLED"} for run in shared_runs):
        return "HFWM_R0_CANDIDATE_KILLED"
    comparison = cast(Mapping[str, object], summary["primary_comparison"])
    if comparison.get("status") != "EXECUTED":
        return "HFWM_R0_BAKEOFF_INCONCLUSIVE"
    if comparison.get("decision") == "REJECT_SHARED_CANDIDATE_FOR_M2":
        return "HFWM_R0_CANDIDATE_KILLED"
    return "HFWM_R0_BAKEOFF_COMPLETE"


def _write_evidence(
    output: Path,
    payload: Mapping[str, object],
    crashes: Sequence[Mapping[str, object]],
    root: Path,
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    files: dict[str, bytes] = {
        "results.json": canonical_json_bytes(payload) + b"\n",
        "crashes.json": canonical_json_bytes({"crashes": list(crashes)}) + b"\n",
        "comparative_table.md": _markdown_table(payload).encode("utf-8"),
        "reproduce.txt": (str(payload["reproduction_command"]) + "\n").encode("utf-8"),
    }
    entries = []
    for name, content in files.items():
        (output / name).write_bytes(content)
        entries.append(
            {
                "path": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        )
    manifest_payload = {
        "schema_version": "hfwm.r0.m2b-evidence-manifest.v1",
        "frozen_manifest_sha256": FROZEN_MANIFEST_SHA256,
        "frozen_preregistration_bundle_sha256": FROZEN_BUNDLE_SHA256,
        "dataset_hash": DATASET_HASH,
        "git_head": _git_output(root, ["rev-parse", "HEAD"]),
        "git_status_sha256": hashlib.sha256(
            _git_output(root, ["status", "--porcelain=v1", "--untracked-files=all"]).encode()
        ).hexdigest(),
        "files": entries,
        "weights_persisted": False,
        "final_status": payload["final_status"],
    }
    manifest = {**manifest_payload, "manifest_sha256": semantic_hash(manifest_payload)}
    (output / "manifest.json").write_bytes(canonical_json_bytes(manifest) + b"\n")


def _git_output(root: Path, arguments: Sequence[str]) -> str:
    import subprocess

    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _markdown_table(payload: Mapping[str, object]) -> str:
    summary = cast(Mapping[str, Any], payload["summary"])
    arms = cast(Mapping[str, Mapping[str, Any]], summary["arms"])
    lines = [
        "# HFWM-R0 M2B — tableau comparatif\n",
        "| Bras | Statut | NMAE primaire [IC95] | Couverture 90% | Dérive | "
        "CPU total (s) | Latence/épisode (ms) | Décision |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for arm_id in ARM_IDS:
        arm = arms[arm_id]
        if arm.get("status") != "EXECUTED":
            lines.append(
                f"| {arm_id} | {arm.get('status')} | — | — | — | — | — | {arm.get('decision')} |"
            )
            continue
        ci = arm["primary_metric_ci95_episode_bootstrap"]
        primary = f"{arm['primary_metric_mean']:.6f} [{ci[0]:.6f}, {ci[1]:.6f}]"
        lines.append(
            f"| {arm_id} | EXECUTED | {primary} | {arm['calibration_coverage_90_mean']:.4f} | "
            f"{arm['rollout_drift_ratio_mean']:.4f} | {arm['cpu_seconds_total']:.4f} | "
            f"{arm['latency_ms_per_test_episode_mean']:.4f} | {arm.get('decision')} |"
        )
    comparison = summary["primary_comparison"]
    lines.extend(
        [
            "",
            "## Décision primaire",
            "",
            "```json",
            json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            f"Statut terminal : `{payload['final_status']}`",
            "",
            "Portée : données synthétiques rétrospectives, shadow only, aucun site réel.",
            "",
        ]
    )
    return "\n".join(lines)
