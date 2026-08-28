"""CPU-only multivariate ridge dynamics trained independently for one site."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias, cast

import numpy as np
import numpy.typing as npt

from hfwm.contracts.interfaces import (
    ActionObservation,
    BeliefState,
    ComponentIdentity,
    StateEncoderInput,
    TokenBatch,
    TrajectoryRollout,
    TrajectoryScore,
    TransitionPrediction,
)
from hfwm.contracts.serialization import JSONValue

FloatArray: TypeAlias = npt.NDArray[np.float64]


class ModelNotFittedError(RuntimeError):
    """Raised when prediction is requested before the local fit."""


class ActionConditioningNotIdentifiableError(ValueError):
    """Raised because HFWM-R0 factual models do not accept action conditioning."""


@dataclass(frozen=True, slots=True)
class JointDynamicsConfig:
    """Frozen representation and capacity shared by bake-off families B and C."""

    observation_dim: int
    recording_dim: int = 2
    ridge_alpha: float = 1.0
    belief_update_rate: float = 0.25
    max_parameters: int = 2_000_000
    seed: int = 1729
    occupancy_index: int = 0

    def __post_init__(self) -> None:
        if self.observation_dim <= 0 or self.recording_dim < 0:
            raise ValueError("observation_dim must be positive and recording_dim non-negative")
        if not math.isfinite(self.ridge_alpha) or self.ridge_alpha <= 0.0:
            raise ValueError("ridge_alpha must be finite and positive")
        if not 0.0 < self.belief_update_rate <= 1.0:
            raise ValueError("belief_update_rate must be in (0, 1]")
        if not 0 <= self.occupancy_index < self.observation_dim:
            raise ValueError("occupancy_index is outside the observation vector")
        if self.max_parameters <= 0:
            raise ValueError("max_parameters must be positive")

    @property
    def design_dim(self) -> int:
        """Values, observation reliability, recording process and intercept."""
        return 2 * self.observation_dim + self.recording_dim + 1

    @property
    def belief_dim(self) -> int:
        """Values, observation reliability and recording process."""
        return 2 * self.observation_dim + self.recording_dim


class LocalJointDynamicsModel:
    """One multivariate transition model fitted from scratch for exactly one site.

    Training accepts only in-memory arrays already authorized, split and point-in-time.
    No site identity is encoded in features and no I/O is performed.
    """

    identity: ComponentIdentity

    def __init__(self, config: JointDynamicsConfig) -> None:
        self.config = config
        self.identity = ComponentIdentity(
            component_type="DynamicsCore",
            implementation_id="local_joint_from_scratch",
            contract_version="hfwm.dynamics-core.v1",
            implementation_version="hfwm-r0.1",
        )
        self._coefficient: FloatArray | None = None
        self._residual_variance: FloatArray | None = None
        self._local_bias = np.zeros(config.observation_dim, dtype=np.float64)
        self._site_id: str | None = None
        if self.parameter_count > config.max_parameters:
            raise ValueError("configured model exceeds max_parameters")

    @property
    def core_parameter_count(self) -> int:
        """Count ridge coefficients plus residual variances."""
        return self.config.design_dim * self.config.observation_dim + self.config.observation_dim

    @property
    def adapter_parameter_count(self) -> int:
        """Reserve the same bounded local calibration vector in both learned families."""
        return self.config.observation_dim

    @property
    def parameter_count(self) -> int:
        """Return the explicit learned parameter budget."""
        return self.core_parameter_count + self.adapter_parameter_count

    @property
    def fitted_site_id(self) -> str | None:
        """Site for which this independent model was fitted."""
        return self._site_id

    def parameter_report(self) -> dict[str, JSONValue]:
        """Return capacity and representation details for bake-off parity review."""
        return {
            "adapter_parameters": self.adapter_parameter_count,
            "belief_features": ["values", "observation_reliability", "recording_process"],
            "core_parameters": self.core_parameter_count,
            "max_parameters": self.config.max_parameters,
            "site_identity_feature": False,
            "total_parameters": self.parameter_count,
        }

    def fit(
        self,
        *,
        site_id: str,
        trajectories: FloatArray,
        observed_mask: FloatArray | None = None,
        recording_process: FloatArray | None = None,
    ) -> LocalJointDynamicsModel:
        """Fit one site-specific ridge transition from already split trajectories."""
        if not site_id:
            raise ValueError("site_id must not be empty")
        design, target, target_mask = self._training_rows(
            trajectories, observed_mask=observed_mask, recording_process=recording_process
        )
        self._fit_rows(design, target, target_mask)
        self._local_bias.fill(0.0)
        self._site_id = site_id
        self.identity = ComponentIdentity(
            component_type="DynamicsCore",
            implementation_id="local_joint_from_scratch",
            contract_version="hfwm.dynamics-core.v1",
            implementation_version="hfwm-r0.1",
            artifact_hash=self.backbone_hash(),
        )
        return self

    def infer_state(self, inputs: StateEncoderInput) -> BeliefState:
        """Infer a causal belief using only explicitly supplied history and current data."""
        batches = [*inputs.history, inputs.observations]
        values = np.zeros(self.config.observation_dim, dtype=np.float64)
        reliability = np.zeros(self.config.observation_dim, dtype=np.float64)
        provenance: list[Mapping[str, JSONValue]] = []
        as_of = ""
        for batch in batches:
            current, mask = self._observation(batch)
            values = np.where(mask > 0.0, current, values)
            rate = self.config.belief_update_rate
            reliability = (1.0 - rate) * reliability + rate * mask
            provenance.extend(batch.provenance)
            if batch.available_at:
                as_of = max(as_of, max(batch.available_at))
        recording = self._recording_vector(inputs.recording_process)
        return self._belief_state(
            values,
            reliability,
            recording,
            provenance=provenance,
            as_of=as_of,
        )

    def update_state(
        self,
        state: BeliefState,
        observations: TokenBatch,
        context: Mapping[str, JSONValue],
    ) -> BeliefState:
        """Update values and reliability without imputing from a future row."""
        values, reliability, previous_recording = self._unpack_belief(state)
        current, mask = self._observation(observations)
        values = np.where(mask > 0.0, current, values)
        rate = self.config.belief_update_rate
        reliability = (1.0 - rate) * reliability + rate * mask
        recording = self._recording_vector(context) if context else previous_recording
        as_of = state.as_of
        if observations.available_at:
            as_of = max(as_of, max(observations.available_at))
        return self._belief_state(
            values,
            reliability,
            recording,
            provenance=[*state.provenance, *observations.provenance],
            as_of=as_of,
        )

    def predict_next(
        self,
        state: BeliefState,
        actions: Sequence[ActionObservation],
        context: Mapping[str, JSONValue],
    ) -> TransitionPrediction:
        """Predict one factual step and reject every action-conditioned request."""
        self._reject_actions(actions)
        coefficient, variance = self._fitted_arrays()
        values, reliability, recording = self._unpack_belief(state)
        design = np.concatenate((values, reliability, recording, np.ones(1, dtype=np.float64)))
        mean = design @ coefficient + self._local_bias
        mean = self._enforce_constraints(mean, context)
        uncertainty = np.sqrt(np.maximum(variance + (1.0 - reliability), 1e-12))
        return TransitionPrediction(
            next_state_distribution=mean,
            event_distribution=mean - values,
            uncertainty=uncertainty,
            constraint_context={
                "action_conditioning": "ACTION_CONDITIONING_NOT_IDENTIFIABLE",
                "non_negative": True,
                "occupancy_capacity_applied": self._capacity(context) is not None,
            },
            horizon_steps=1,
        )

    def rollout(
        self,
        state: BeliefState,
        actions: Sequence[ActionObservation],
        context: Mapping[str, JSONValue],
        horizon_steps: int,
    ) -> TrajectoryRollout:
        """Generate a free-running mean trajectory with monotone process uncertainty."""
        self._reject_actions(actions)
        if horizon_steps <= 0:
            raise ValueError("horizon_steps must be positive")
        _, variance = self._fitted_arrays()
        initial_values, reliability, recording = self._unpack_belief(state)
        current = initial_values.copy()
        trajectory: list[FloatArray] = []
        events: list[FloatArray] = []
        uncertainty: list[FloatArray] = []
        for step in range(1, horizon_steps + 1):
            design = np.concatenate(
                (current, reliability, recording, np.ones(1, dtype=np.float64))
            )
            predicted = self._enforce_constraints(
                design @ self._coefficient_array() + self._local_bias, context
            )
            trajectory.append(predicted)
            events.append(predicted - current)
            uncertainty.append(
                np.sqrt(np.maximum(variance * step + (1.0 - reliability), 1e-12))
            )
            current = predicted
        return TrajectoryRollout(
            state_trajectories=np.stack(trajectory),
            event_trajectories=np.stack(events),
            uncertainty_by_horizon=np.stack(uncertainty),
            free_running=True,
            horizon_steps=horizon_steps,
            provenance=state.provenance,
        )

    def sample_futures(
        self,
        state: BeliefState,
        actions: Sequence[ActionObservation],
        context: Mapping[str, JSONValue],
        horizon_steps: int,
        sample_count: int,
        seed: int,
    ) -> TrajectoryRollout:
        """Sample deterministic-by-seed futures around the free-running mean."""
        if sample_count <= 0:
            raise ValueError("sample_count must be positive")
        mean_rollout = self.rollout(state, actions, context, horizon_steps)
        means = cast(FloatArray, mean_rollout.state_trajectories)
        scale = cast(FloatArray, mean_rollout.uncertainty_by_horizon)
        generator = np.random.default_rng(seed)
        noise = generator.normal(size=(sample_count, *means.shape)) * scale[np.newaxis, :, :]
        samples = means[np.newaxis, :, :] + noise
        for sample_index in range(sample_count):
            for step in range(horizon_steps):
                samples[sample_index, step] = self._enforce_constraints(
                    samples[sample_index, step], context
                )
        initial = np.broadcast_to(
            self._unpack_belief(state)[0], (sample_count, 1, self.config.observation_dim)
        )
        events = np.diff(np.concatenate((initial, samples), axis=1), axis=1)
        return TrajectoryRollout(
            state_trajectories=samples,
            event_trajectories=events,
            uncertainty_by_horizon=scale,
            free_running=True,
            horizon_steps=horizon_steps,
            provenance=state.provenance,
        )

    def score_observed_trajectory(
        self,
        rollout: TrajectoryRollout,
        observed: Sequence[Mapping[str, JSONValue]],
    ) -> TrajectoryScore:
        """Score a factual trajectory with per-step multivariate RMSE."""
        if not observed:
            raise ValueError("observed trajectory must not be empty")
        predicted = np.asarray(rollout.state_trajectories, dtype=np.float64)
        if predicted.ndim == 3:
            predicted = predicted.mean(axis=0)
        if predicted.ndim != 2 or predicted.shape[1] != self.config.observation_dim:
            raise ValueError("rollout has an incompatible state trajectory shape")
        if len(observed) > predicted.shape[0]:
            raise ValueError("observed trajectory exceeds rollout horizon")
        actual_rows: list[FloatArray] = []
        for index, row in enumerate(observed):
            value = row.get("state")
            actual = np.asarray(value, dtype=np.float64)
            if actual.shape != (self.config.observation_dim,) or not np.all(np.isfinite(actual)):
                raise ValueError(f"observed[{index}].state has an invalid shape or value")
            actual_rows.append(actual)
        actual_matrix = np.stack(actual_rows)
        per_step = np.sqrt(np.mean((predicted[: len(actual_rows)] - actual_matrix) ** 2, axis=1))
        return TrajectoryScore(
            aggregate_score=float(np.mean(per_step)),
            per_step_scores=tuple(float(value) for value in per_step),
            scoring_rule="MULTIVARIATE_RMSE",
            metadata={"observed_steps": len(actual_rows), "free_running": rollout.free_running},
        )

    def backbone_hash(self) -> str:
        """Hash only the shared/core arrays, excluding the local adapter vector."""
        coefficient, variance = self._fitted_arrays()
        digest = hashlib.sha256()
        config_payload = {
            "belief_update_rate": self.config.belief_update_rate,
            "observation_dim": self.config.observation_dim,
            "recording_dim": self.config.recording_dim,
            "ridge_alpha": self.config.ridge_alpha,
            "seed": self.config.seed,
        }
        digest.update(json.dumps(config_payload, sort_keys=True, separators=(",", ":")).encode())
        for array in (coefficient, variance):
            digest.update(str(array.shape).encode("ascii"))
            digest.update(array.astype("<f8", copy=False).tobytes(order="C"))
        return digest.hexdigest()

    def _training_rows(
        self,
        trajectories: FloatArray,
        *,
        observed_mask: FloatArray | None,
        recording_process: FloatArray | None,
    ) -> tuple[FloatArray, FloatArray, FloatArray]:
        values = np.asarray(trajectories, dtype=np.float64)
        if (
            values.ndim != 3
            or values.shape[1] < 2
            or values.shape[2] != self.config.observation_dim
        ):
            raise ValueError("trajectories must have shape (episodes, steps>=2, observation_dim)")
        mask = np.isfinite(values).astype(np.float64)
        if observed_mask is not None:
            supplied_mask = np.asarray(observed_mask, dtype=np.float64)
            if supplied_mask.shape != values.shape or not np.all(
                np.isin(supplied_mask, (0.0, 1.0))
            ):
                raise ValueError("observed_mask must be binary and match trajectories")
            mask *= supplied_mask
        imputed = self._forward_impute(values, mask)
        recording_shape = (*values.shape[:2], self.config.recording_dim)
        if recording_process is None:
            recording = np.zeros(recording_shape, dtype=np.float64)
        else:
            recording = np.asarray(recording_process, dtype=np.float64)
            if recording.shape != recording_shape or not np.all(np.isfinite(recording)):
                raise ValueError("recording_process has an invalid shape or non-finite values")
        design = np.concatenate(
            (
                imputed[:, :-1, :],
                mask[:, :-1, :],
                recording[:, :-1, :],
                np.ones((*values.shape[:2][:-1], values.shape[1] - 1, 1), dtype=np.float64),
            ),
            axis=2,
        )
        return (
            design.reshape(-1, self.config.design_dim),
            imputed[:, 1:, :].reshape(-1, self.config.observation_dim),
            mask[:, 1:, :].reshape(-1, self.config.observation_dim),
        )

    def _fit_rows(self, design: FloatArray, target: FloatArray, target_mask: FloatArray) -> None:
        coefficient = np.zeros(
            (self.config.design_dim, self.config.observation_dim), dtype=np.float64
        )
        variance = np.zeros(self.config.observation_dim, dtype=np.float64)
        penalty = self.config.ridge_alpha * np.eye(self.config.design_dim, dtype=np.float64)
        penalty[-1, -1] = 0.0
        for feature in range(self.config.observation_dim):
            selected = target_mask[:, feature] > 0.0
            if not np.any(selected):
                raise ValueError(f"no observed training target for feature {feature}")
            x_feature = design[selected]
            y_feature = target[selected, feature]
            coefficient[:, feature] = np.linalg.solve(
                x_feature.T @ x_feature + penalty,
                x_feature.T @ y_feature,
            )
            residual = y_feature - x_feature @ coefficient[:, feature]
            variance[feature] = max(float(np.mean(residual**2)), 1e-8)
        self._coefficient = coefficient
        self._residual_variance = variance

    def _forward_impute(self, values: FloatArray, mask: FloatArray) -> FloatArray:
        result = np.zeros_like(values)
        for episode in range(values.shape[0]):
            previous = np.zeros(self.config.observation_dim, dtype=np.float64)
            for step in range(values.shape[1]):
                current = np.where(mask[episode, step] > 0.0, values[episode, step], previous)
                result[episode, step] = current
                previous = current
        return result

    def _observation(self, batch: TokenBatch) -> tuple[FloatArray, FloatArray]:
        values = np.asarray(batch.values, dtype=np.float64)
        if values.shape != (self.config.observation_dim,):
            raise ValueError(
                "TokenBatch.values must contain exactly one current row; "
                "future/multi-row input rejected"
            )
        finite = np.isfinite(values)
        raw_mask = np.asarray(batch.attention_mask)
        if raw_mask.shape != values.shape:
            raise ValueError("TokenBatch.attention_mask must match the current observation row")
        mask = (raw_mask.astype(bool) & finite).astype(np.float64)
        return np.where(mask > 0.0, values, 0.0), mask

    def _recording_vector(self, recording: Mapping[str, JSONValue]) -> FloatArray:
        numeric = [
            float(value)
            for key, value in sorted(recording.items())
            if not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
        ]
        result = np.zeros(self.config.recording_dim, dtype=np.float64)
        count = min(len(numeric), self.config.recording_dim)
        result[:count] = numeric[:count]
        return result

    def _belief_state(
        self,
        values: FloatArray,
        reliability: FloatArray,
        recording: FloatArray,
        *,
        provenance: Sequence[Mapping[str, JSONValue]],
        as_of: str,
    ) -> BeliefState:
        base_variance = (
            self._residual_variance.copy()
            if self._residual_variance is not None
            else np.ones(self.config.observation_dim, dtype=np.float64)
        )
        return BeliefState(
            value=np.concatenate((values, reliability, recording)),
            state_uncertainty=base_variance + (1.0 - reliability),
            entity_states={},
            hierarchical_states={},
            provenance=tuple(provenance),
            as_of=as_of,
        )

    def _unpack_belief(self, state: BeliefState) -> tuple[FloatArray, FloatArray, FloatArray]:
        packed = np.asarray(state.value, dtype=np.float64)
        if packed.shape != (self.config.belief_dim,) or not np.all(np.isfinite(packed)):
            raise ValueError("BeliefState.value is incompatible with this dynamics configuration")
        dimension = self.config.observation_dim
        return packed[:dimension], packed[dimension : 2 * dimension], packed[2 * dimension :]

    def _fitted_arrays(self) -> tuple[FloatArray, FloatArray]:
        if self._coefficient is None or self._residual_variance is None:
            raise ModelNotFittedError("fit must complete before prediction")
        return self._coefficient, self._residual_variance

    def _coefficient_array(self) -> FloatArray:
        return self._fitted_arrays()[0]

    def _capacity(self, context: Mapping[str, JSONValue]) -> float | None:
        value = context.get("occupancy_capacity")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        capacity = float(value)
        return capacity if math.isfinite(capacity) and capacity >= 0.0 else None

    def _enforce_constraints(
        self, prediction: FloatArray, context: Mapping[str, JSONValue]
    ) -> FloatArray:
        constrained = np.maximum(np.asarray(prediction, dtype=np.float64), 0.0)
        capacity = self._capacity(context)
        if capacity is not None:
            constrained[self.config.occupancy_index] = min(
                constrained[self.config.occupancy_index], capacity
            )
        return constrained

    @staticmethod
    def _reject_actions(actions: Sequence[ActionObservation]) -> None:
        if actions:
            raise ActionConditioningNotIdentifiableError(
                "HFWM-R0 factual dynamics reject actions: ACTION_CONDITIONING_NOT_IDENTIFIABLE"
            )
