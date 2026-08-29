"""Immutable in-memory contracts for the preregistered HFWM-R0 bake-off."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, TypeAlias

import numpy as np
import numpy.typing as npt

from hfwm.corpus import CorpusConfig

FloatArray: TypeAlias = npt.NDArray[np.float64]

TASKS: tuple[str, ...] = ("occupancy", "inflow", "discharges", "staffing", "pressure")
HORIZONS: tuple[int, ...] = (6, 24, 72)
SEEDS: tuple[int, ...] = (1729, 2718, 3141)
CORE_MODEL_IDS: tuple[str, ...] = (
    "persistence",
    "seasonal_naive_168h",
    "mechanistic_queue_semimarkov",
    "local_joint_from_scratch",
    "shared_hfwm_multitask",
)
PREREGISTERED_ABLATIONS: tuple[str, ...] = (
    "shared_pretraining_removed",
    "joint_heads_replaced_by_independent_heads",
    "site_identity_removed",
    "recording_process_features_removed",
)
PREREGISTERED_NEGATIVE_CONTROLS: tuple[str, ...] = (
    "future_observation_leakage_sentinel",
    "future_action_leakage_sentinel",
    "label_permutation",
    "site_identity_shortcut",
    "action_permutation_if_observable",
)


class BakeoffAuthorizationError(ValueError):
    """Raised before corpus construction when a frozen execution gate fails."""


@dataclass(frozen=True, slots=True)
class RunProfile:
    """Execution size; the main profile is closed and tests must use ``smoke``."""

    name: str
    corpus_config: CorpusConfig
    bootstrap_draws: int
    max_test_windows: int | None
    main_run: bool

    def __post_init__(self) -> None:
        if not self.name or self.bootstrap_draws <= 0:
            raise ValueError("run profile name and bootstrap_draws must be positive")
        if self.max_test_windows is not None and self.max_test_windows <= 0:
            raise ValueError("max_test_windows must be absent or positive")
        if self.main_run and (
            self.corpus_config != CorpusConfig()
            or self.bootstrap_draws != 2000
            or self.max_test_windows is not None
            or self.name != "main"
        ):
            raise ValueError("main profile must use the frozen full corpus and 2000 draws")

    @classmethod
    def main(cls) -> RunProfile:
        """Return the sole profile authorized for a main synthetic run."""
        return cls(
            name="main",
            corpus_config=CorpusConfig(),
            bootstrap_draws=2000,
            max_test_windows=None,
            main_run=True,
        )

    @classmethod
    def smoke(cls) -> RunProfile:
        """Return a tiny non-main profile reserved for harness verification."""
        return cls(
            name="smoke",
            corpus_config=CorpusConfig(
                organization_count=3,
                episodes_per_unit=4,
                episode_hours=96,
                history_hours=20,
                horizons_hours=HORIZONS,
                purge_gap_hours=24,
                window_stride_hours=6,
            ),
            bootstrap_draws=40,
            max_test_windows=6,
            main_run=False,
        )


@dataclass(frozen=True, slots=True)
class TrainingSiteData:
    """Already point-in-time, train-only arrays for one pseudo-site."""

    site_id: str
    trajectories: FloatArray
    observed_mask: FloatArray
    recording_process: FloatArray


@dataclass(frozen=True, slots=True)
class PreparedWindow:
    """One common test cohort row shared by every comparator."""

    window_id: str
    episode_id: str
    site_id: str
    unit_id: str
    history: FloatArray
    history_mask: FloatArray
    history_recording: FloatArray
    current: FloatArray
    current_mask: FloatArray
    recording_process: FloatArray
    capacity: float
    truth_by_horizon: Mapping[int, FloatArray]
    seasonal_by_horizon: Mapping[int, FloatArray]


@dataclass(frozen=True, slots=True)
class PreparedCohort:
    """Frozen common cohorts, targets and train-only normalization statistics."""

    corpus_hash: str
    cohort_hash: str
    source_id: str
    training_by_site: Mapping[str, TrainingSiteData]
    test_windows: tuple[PreparedWindow, ...]
    train_iqr: FloatArray
    tasks: tuple[str, ...] = TASKS
    horizons: tuple[int, ...] = HORIZONS


@dataclass(frozen=True, slots=True)
class ComparatorForecast:
    """Predictions for every frozen horizon of one prepared window."""

    predictions: Mapping[int, FloatArray]
    uncertainty: Mapping[int, FloatArray] | None
    free_running: bool


class ExternalComparator(Protocol):
    """Future read-only integration point for the frozen HGBR/CQR comparator."""

    comparator_id: str

    def predict(
        self,
        window: PreparedWindow,
        horizons: Sequence[int],
        *,
        seed: int,
    ) -> ComparatorForecast: ...


@dataclass(frozen=True, slots=True)
class ForecastRecord:
    """One common-cohort forecast row consumed by all registered metrics."""

    model_id: str
    seed: int
    window_id: str
    episode_id: str
    horizon: int
    truth: FloatArray
    prediction: FloatArray
    uncertainty: FloatArray | None
    capacity: float
    free_running: bool


@dataclass(frozen=True, slots=True)
class BakeoffResult:
    """Pure in-memory result without models, weights or filesystem references."""

    run_profile: str
    main_run: bool
    preregistration_manifest_sha256: str
    corpus_hash: str
    cohort_hash: str
    seeds: tuple[int, ...]
    tasks: tuple[str, ...]
    horizons: tuple[int, ...]
    budgets: Mapping[str, Mapping[str, int]]
    gates: Mapping[str, object]
    evaluations: Mapping[str, object]
    comparators: Mapping[str, object]
    ablations: Mapping[str, object]
    negative_controls: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        """Return a detached JSON-compatible evidence payload."""
        return {
            "schema_version": "hfwm.bakeoff-result.v1",
            "run_profile": self.run_profile,
            "main_run": self.main_run,
            "preregistration_manifest_sha256": self.preregistration_manifest_sha256,
            "corpus_hash": self.corpus_hash,
            "cohort_hash": self.cohort_hash,
            "seeds": list(self.seeds),
            "tasks": list(self.tasks),
            "horizons": list(self.horizons),
            "budgets": {key: dict(value) for key, value in sorted(self.budgets.items())},
            "gates": dict(self.gates),
            "evaluations": dict(self.evaluations),
            "comparators": dict(self.comparators),
            "ablations": dict(self.ablations),
            "negative_controls": dict(self.negative_controls),
            "weights_persisted": False,
            "tsfm_status": "NOT_EXECUTED",
            "action_status": "ACTION_CONDITIONING_NOT_IDENTIFIABLE",
            "foundation_status": "FOUNDATION_EVIDENCE_INSUFFICIENT",
        }
