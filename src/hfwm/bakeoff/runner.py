"""Offline, preregistration-gated HFWM-R0 bake-off execution."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np
import yaml

from hfwm.contracts import (
    DataRightsRegistry,
    RightsUse,
    StateEncoderInput,
    TokenBatch,
)
from hfwm.contracts.serialization import JSONValue
from hfwm.corpus import SOURCE_ID, build_temporal_corpus
from hfwm.evaluation.preregistration import require_valid_preregistration
from hfwm.models.local import JointDynamicsConfig, LocalJointDynamicsModel
from hfwm.models.mechanistic import MechanisticQueueSemiMarkov
from hfwm.models.shared import SharedHFWMModel

from .contracts import (
    CORE_MODEL_IDS,
    HORIZONS,
    PREREGISTERED_ABLATIONS,
    PREREGISTERED_NEGATIVE_CONTROLS,
    SEEDS,
    TASKS,
    BakeoffAuthorizationError,
    BakeoffResult,
    ComparatorForecast,
    ExternalComparator,
    FloatArray,
    ForecastRecord,
    PreparedCohort,
    PreparedWindow,
    RunProfile,
)
from .data import prepare_common_cohort
from .metrics import assert_common_cohort, evaluate_forecasts

_REQUIRED_DOCUMENTS = frozenset(
    {
        "HFWM_R0_MOAT_CHARTER.md",
        "HFWM_R0_SPEC.yaml",
        "HFWM_R0_BAKEOFF.yaml",
        "HFWM_R0_DATA_CARD.md",
        "HFWM_R0_DATA_RIGHTS.yaml",
        "HFWM_R0_SPLITS.yaml",
        "HFWM_R0_DECONTAMINATION.md",
        "HFWM_R0_METRICS.yaml",
        "HFWM_R0_KILL_CRITERIA.yaml",
        "HFWM_R0_CLAIMS_POLICY.yaml",
        "HFWM_R0_BLOCKERS.md",
    }
)


def run_bakeoff(
    *,
    preregistration_dir: Path,
    profile: RunProfile,
    external_comparators: Mapping[str, ExternalComparator] | None = None,
) -> BakeoffResult:
    """Execute an offline run in memory after all authorization gates pass.

    The function performs no filesystem writes, subprocess calls or network I/O and
    never returns learned arrays or model weights.
    """
    preregistration, bakeoff_document, budgets = _authorize(preregistration_dir, profile)
    corpus = build_temporal_corpus(profile.corpus_config)
    if corpus.source_id != SOURCE_ID:
        raise BakeoffAuthorizationError("constructed corpus source differs from authorized source")
    cohort = prepare_common_cohort(corpus, profile)
    comparators = dict(external_comparators or {})
    unknown = set(comparators) - {"hgbr_cqr"}
    if unknown:
        raise BakeoffAuthorizationError(f"unpreregistered external comparators: {sorted(unknown)}")
    if "hgbr_cqr" in comparators and comparators["hgbr_cqr"].comparator_id != "hgbr_cqr":
        raise BakeoffAuthorizationError("HGBR/CQR protocol identity mismatch")

    records = _execute_matrix(cohort, external_comparators=comparators)
    executed_ids = CORE_MODEL_IDS + (("hgbr_cqr",) if "hgbr_cqr" in comparators else ())
    execution_cohort_hash = assert_common_cohort(records, expected_model_ids=executed_ids)
    evaluations = evaluate_forecasts(
        records,
        train_iqr=cohort.train_iqr,
        bootstrap_draws=profile.bootstrap_draws,
    )
    comparator_status: dict[str, object] = {
        "persistence": {"status": "EXECUTED"},
        "seasonal_naive_168h": {"status": "EXECUTED"},
        "hgbr_cqr": {
            "status": "EXECUTED" if "hgbr_cqr" in comparators else "NOT_EXECUTED",
            "integration": (
                "ExternalComparator protocol; frozen no-optimization implementation required"
            ),
        },
        "generic_tsfm": {
            "status": "NOT_EXECUTED",
            "reason": "no verified local checkpoint identity/licence/provenance",
        },
    }
    ablations = _frozen_plan(
        tuple(cast(Sequence[str], bakeoff_document["ablations"])),
        PREREGISTERED_ABLATIONS,
    )
    controls = _frozen_plan(
        tuple(cast(Sequence[str], bakeoff_document["negative_controls"])),
        PREREGISTERED_NEGATIVE_CONTROLS,
    )
    return BakeoffResult(
        run_profile=profile.name,
        main_run=profile.main_run,
        preregistration_manifest_sha256=str(
            preregistration.manifest["manifest_sha256"]
        ),
        corpus_hash=cohort.corpus_hash,
        cohort_hash=cohort.cohort_hash,
        seeds=SEEDS,
        tasks=TASKS,
        horizons=HORIZONS,
        budgets=budgets,
        gates={
            "preregistration_valid": True,
            "main_runs_authorized": True,
            "required_document_count": 11,
            "source_id": SOURCE_ID,
            "training_allowed": True,
            "evaluation_allowed": True,
            "publication_allowed": False,
            "weights_allowed": False,
            "same_cohort_for_all_models": True,
            "execution_cohort_hash": execution_cohort_hash,
            "test_window_count": len(cohort.test_windows),
            "profile_is_main": profile.main_run,
        },
        evaluations=evaluations,
        comparators=comparator_status,
        ablations=ablations,
        negative_controls=controls,
    )


def _authorize(
    directory: Path, profile: RunProfile
) -> tuple[Any, Mapping[str, Any], dict[str, Mapping[str, int]]]:
    preregistration = require_valid_preregistration(directory)
    manifest_names = {
        entry["logical_name"]
        for entry in preregistration.manifest.get("entries", [])
        if isinstance(entry, dict) and isinstance(entry.get("logical_name"), str)
    }
    if manifest_names != _REQUIRED_DOCUMENTS:
        raise BakeoffAuthorizationError("the exact eleven preregistration documents are required")
    if not preregistration.main_runs_authorized:
        raise BakeoffAuthorizationError("main_runs_authorized must be true before any profile")
    bakeoff = _load_yaml_mapping(directory / "HFWM_R0_BAKEOFF.yaml")
    if tuple(bakeoff.get("seeds", ())) != SEEDS:
        raise BakeoffAuthorizationError("seeds must be exactly 1729/2718/3141")
    if tuple(bakeoff.get("horizons_hours", ())) != HORIZONS:
        raise BakeoffAuthorizationError("horizons must be exactly 6/24/72")
    if tuple(bakeoff.get("tasks", ())) != TASKS:
        raise BakeoffAuthorizationError("tasks differ from the frozen five-task contract")
    rights_document = _load_yaml_mapping(directory / "HFWM_R0_DATA_RIGHTS.yaml")
    registry = DataRightsRegistry.from_dict(cast(JSONValue, rights_document))
    source = next((item for item in registry.sources if item.source_id == SOURCE_ID), None)
    if source is None:
        raise BakeoffAuthorizationError("authorized synthetic source is absent")
    if not source.permits(RightsUse.TRAINING) or not source.permits(RightsUse.EVALUATION):
        raise BakeoffAuthorizationError("synthetic source must allow local training and evaluation")
    if source.permits(RightsUse.WEIGHTS) or source.permits(RightsUse.PUBLICATION):
        raise BakeoffAuthorizationError("synthetic source must forbid weights and publication")
    if profile.main_run and profile != RunProfile.main():
        raise BakeoffAuthorizationError("main run profile differs from frozen execution size")
    candidates = bakeoff.get("candidate_families")
    if not isinstance(candidates, list):
        raise BakeoffAuthorizationError("candidate budget registry is absent")
    budgets: dict[str, Mapping[str, int]] = {}
    fields = (
        "tuning_trials_max",
        "cpu_core_hours_max_per_seed",
        "accelerator_hours_max_per_seed",
        "learned_parameters_max",
    )
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str):
            raise BakeoffAuthorizationError("candidate budget entry is malformed")
        if any(not isinstance(candidate.get(field), int) for field in fields):
            raise BakeoffAuthorizationError("candidate budget must contain frozen integers")
        budgets[candidate["id"]] = {field: int(candidate[field]) for field in fields}
    return preregistration, bakeoff, budgets


def _execute_matrix(
    cohort: PreparedCohort,
    *,
    external_comparators: Mapping[str, ExternalComparator],
) -> tuple[ForecastRecord, ...]:
    records: list[ForecastRecord] = []
    trajectories_by_site = {
        site_id: data.trajectories for site_id, data in cohort.training_by_site.items()
    }
    masks_by_site = {
        site_id: data.observed_mask for site_id, data in cohort.training_by_site.items()
    }
    recording_by_site = {
        site_id: data.recording_process for site_id, data in cohort.training_by_site.items()
    }
    for seed in SEEDS:
        config = JointDynamicsConfig(
            observation_dim=len(TASKS),
            recording_dim=2,
            seed=seed,
        )
        local_models = {
            site_id: LocalJointDynamicsModel(config).fit(
                site_id=site_id,
                trajectories=data.trajectories,
                observed_mask=data.observed_mask,
                recording_process=data.recording_process,
            )
            for site_id, data in sorted(cohort.training_by_site.items())
        }
        shared_backbone = SharedHFWMModel(config).pretrain(
            trajectories_by_site=trajectories_by_site,
            observed_masks_by_site=masks_by_site,
            recording_process_by_site=recording_by_site,
        )
        shared_models: dict[str, SharedHFWMModel] = {}
        for site_id, data in sorted(cohort.training_by_site.items()):
            adapted = copy.deepcopy(shared_backbone)
            adapted.adapt_site(
                site_id=site_id,
                trajectories=data.trajectories,
                observed_mask=data.observed_mask,
                recording_process=data.recording_process,
                local_data_budget=256,
            )
            shared_models[site_id] = adapted
        mechanistic = MechanisticQueueSemiMarkov()
        for window in cohort.test_windows:
            forecasts: dict[str, ComparatorForecast] = {
                "persistence": ComparatorForecast(
                    predictions={horizon: window.current.copy() for horizon in HORIZONS},
                    uncertainty=None,
                    free_running=False,
                ),
                "seasonal_naive_168h": ComparatorForecast(
                    predictions=window.seasonal_by_horizon,
                    uncertainty=None,
                    free_running=False,
                ),
                "mechanistic_queue_semimarkov": _mechanistic_forecast(mechanistic, window),
                "local_joint_from_scratch": _learned_forecast(
                    local_models[window.site_id], window
                ),
                "shared_hfwm_multitask": _learned_forecast(
                    shared_models[window.site_id], window
                ),
            }
            for model_id, comparator in external_comparators.items():
                forecasts[model_id] = comparator.predict(window, HORIZONS, seed=seed)
            for model_id, forecast in sorted(forecasts.items()):
                records.extend(_forecast_records(model_id, seed, window, forecast))
    return tuple(records)


def _learned_forecast(
    model: LocalJointDynamicsModel, window: PreparedWindow
) -> ComparatorForecast:
    history = tuple(
        _learned_token(row, mask, recording, index=index)
        for index, (row, mask, recording) in enumerate(
            zip(
                window.history,
                window.history_mask,
                window.history_recording,
                strict=True,
            )
        )
    )
    current = _learned_token(
        window.current,
        window.current_mask,
        window.recording_process,
        index=len(history),
    )
    state = model.infer_state(
        StateEncoderInput(
            observations=current,
            history=history,
            entity_graph={},
            recording_process={
                "delay_hours": float(window.recording_process[0]),
                "missing_rate": float(window.recording_process[1]),
            },
            context={},
            site_metadata={},
        )
    )
    rollout = model.rollout(
        state,
        (),
        {"occupancy_capacity": window.capacity},
        horizon_steps=max(HORIZONS),
    )
    states = np.asarray(rollout.state_trajectories, dtype=np.float64)
    uncertainty = np.asarray(rollout.uncertainty_by_horizon, dtype=np.float64)
    return ComparatorForecast(
        predictions={horizon: states[horizon - 1].copy() for horizon in HORIZONS},
        uncertainty={horizon: uncertainty[horizon - 1].copy() for horizon in HORIZONS},
        free_running=rollout.free_running,
    )


def _learned_token(
    values: FloatArray,
    mask: FloatArray,
    recording: FloatArray,
    *,
    index: int,
) -> TokenBatch:
    return TokenBatch(
        values=values,
        attention_mask=mask,
        entity_ids=("unit",),
        event_ids=(f"point-in-time-{index}",),
        available_at=(f"point-in-time-{index}",),
        provenance=(),
        metadata={
            "delay_hours": float(recording[0]),
            "missing_rate": float(recording[1]),
        },
    )


def _mechanistic_forecast(
    model: MechanisticQueueSemiMarkov, window: PreparedWindow
) -> ComparatorForecast:
    values = {
        task: float(window.current[index]) for index, task in enumerate(TASKS)
    } | {"capacity": window.capacity}
    mask = {
        task: bool(window.current_mask[index]) for index, task in enumerate(TASKS)
    } | {"capacity": True}
    token = TokenBatch(
        values=values,
        attention_mask=mask,
        entity_ids=(window.unit_id,),
        event_ids=(window.window_id,),
        available_at=(window.window_id,),
        provenance=(),
        metadata={"observation_delay_hours": float(window.recording_process[0])},
    )
    state = model.infer_state(
        StateEncoderInput(
            observations=token,
            history=(),
            entity_graph={},
            recording_process={
                "delay_hours": float(window.recording_process[0]),
                "missing_rate": float(window.recording_process[1]),
            },
            context={},
            site_metadata={},
        )
    )
    rollout = model.rollout(state, (), {}, max(HORIZONS))
    state_rows = cast(Sequence[Mapping[str, object]], rollout.state_trajectories)
    uncertainty_rows = cast(Sequence[Mapping[str, object]], rollout.uncertainty_by_horizon)
    predictions: dict[int, FloatArray] = {}
    uncertainty: dict[int, FloatArray] = {}
    for horizon in HORIZONS:
        row = state_rows[horizon - 1]
        predictions[horizon] = np.asarray(
            [float(cast(float, row[task])) for task in TASKS], dtype=np.float64
        )
        scalar = float(cast(float, uncertainty_rows[horizon - 1]["scalar"]))
        uncertainty[horizon] = np.full(len(TASKS), scalar, dtype=np.float64)
    return ComparatorForecast(
        predictions=predictions,
        uncertainty=uncertainty,
        free_running=rollout.free_running,
    )


def _forecast_records(
    model_id: str,
    seed: int,
    window: PreparedWindow,
    forecast: ComparatorForecast,
) -> list[ForecastRecord]:
    if set(forecast.predictions) != set(HORIZONS):
        raise ValueError(f"{model_id} did not return every preregistered horizon")
    if forecast.uncertainty is not None and set(forecast.uncertainty) != set(HORIZONS):
        raise ValueError(f"{model_id} uncertainty does not cover every horizon")
    return [
        ForecastRecord(
            model_id=model_id,
            seed=seed,
            window_id=window.window_id,
            episode_id=window.episode_id,
            horizon=horizon,
            truth=window.truth_by_horizon[horizon].copy(),
            prediction=np.asarray(forecast.predictions[horizon], dtype=np.float64).copy(),
            uncertainty=(
                np.asarray(forecast.uncertainty[horizon], dtype=np.float64).copy()
                if forecast.uncertainty is not None
                else None
            ),
            capacity=window.capacity,
            free_running=forecast.free_running,
        )
        for horizon in HORIZONS
    ]


def _frozen_plan(actual: tuple[str, ...], expected: tuple[str, ...]) -> dict[str, object]:
    if actual != expected:
        raise BakeoffAuthorizationError("ablation/control plan differs from preregistration")
    return {
        identifier: {
            "status": "NOT_EXECUTED",
            "available_in_frozen_plan": True,
            "post_hoc_addition_allowed": False,
        }
        for identifier in expected
    }


def _load_yaml_mapping(path: Path) -> Mapping[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BakeoffAuthorizationError(f"{path.name} must contain a mapping")
    return value
