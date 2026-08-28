"""Focused tests for the local from-scratch joint ridge family."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import numpy.typing as npt
import pytest

from hfwm.contracts.interfaces import (
    ActionObservation,
    DynamicsCore,
    StateEncoderInput,
    TokenBatch,
)
from hfwm.models.local import (
    ActionConditioningNotIdentifiableError,
    JointDynamicsConfig,
    LocalJointDynamicsModel,
)

FloatArray = npt.NDArray[np.float64]


def trajectories(*, offset: float = 0.0, episodes: int = 5, steps: int = 10) -> FloatArray:
    """Create tiny non-negative coupled trajectories without external data."""
    result = np.zeros((episodes, steps, 3), dtype=np.float64)
    for episode in range(episodes):
        result[episode, 0] = [10.0 + offset + episode, 2.0 + episode, 1.0]
        for step in range(1, steps):
            previous = result[episode, step - 1]
            result[episode, step] = [
                0.75 * previous[0] + 0.50 * previous[1] + 1.0,
                0.20 * previous[0] + 0.60 * previous[1] + 0.5,
                0.10 * previous[0] + 0.30 * previous[2] + 0.25,
            ]
    return result


def token(values: FloatArray, mask: FloatArray, *, hour: int) -> TokenBatch:
    """Build one current point-in-time observation."""
    available_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=hour)
    return TokenBatch(
        values=values,
        attention_mask=mask,
        entity_ids=("unit-1",),
        event_ids=(f"event-{hour}",),
        available_at=(available_at.isoformat(),),
        provenance=(),
    )


def state_input(*, future_row: bool = False) -> StateEncoderInput:
    """Build a causal state input or a deliberately invalid multi-row batch."""
    values = np.asarray([13.0, 4.0, 2.0])
    if future_row:
        values = np.stack((values, np.asarray([999.0, 999.0, 999.0])))
    return StateEncoderInput(
        observations=token(values, np.ones_like(values), hour=2),
        history=(
            token(np.asarray([10.0, 2.0, 1.0]), np.ones(3), hour=0),
            token(np.asarray([11.0, 3.0, 1.5]), np.ones(3), hour=1),
        ),
        entity_graph={},
        recording_process={"delay_hours": 0.5, "missing_rate": 0.1},
        context={},
        site_metadata={},
    )


def fitted_model(*, seed: int = 1729) -> LocalJointDynamicsModel:
    """Fit the tiny deterministic local model."""
    config = JointDynamicsConfig(observation_dim=3, recording_dim=2, seed=seed)
    return LocalJointDynamicsModel(config).fit(site_id="site-1", trajectories=trajectories())


def test_local_fit_is_deterministic_joint_and_protocol_compatible() -> None:
    """The same site arrays produce byte-identical multivariate backbones."""
    first = fitted_model()
    second = fitted_model()
    assert isinstance(first, DynamicsCore)
    assert first.backbone_hash() == second.backbone_hash()
    assert first.identity.artifact_hash == first.backbone_hash()
    assert first.fitted_site_id == "site-1"
    assert first.parameter_count == second.parameter_count
    assert first.parameter_count <= 2_000_000
    assert first.parameter_report()["site_identity_feature"] is False


def test_free_running_rollout_shapes_constraints_uncertainty_and_score() -> None:
    """Rollouts are joint, free-running, constrained and increasingly uncertain."""
    model = fitted_model()
    state = model.infer_state(state_input())
    rollout = model.rollout(state, (), {"occupancy_capacity": 25.0}, horizon_steps=5)
    states = np.asarray(rollout.state_trajectories)
    uncertainty = np.asarray(rollout.uncertainty_by_horizon)
    assert rollout.free_running
    assert states.shape == (5, 3)
    assert np.asarray(rollout.event_trajectories).shape == (5, 3)
    assert uncertainty.shape == (5, 3)
    assert np.all(np.diff(uncertainty, axis=0) >= 0.0)
    assert np.all(states >= 0.0)
    assert np.all(states[:, 0] <= 25.0)
    observed = tuple({"state": row.tolist()} for row in states)
    score = model.score_observed_trajectory(rollout, observed)
    assert score.aggregate_score == 0.0
    assert score.scoring_rule == "MULTIVARIATE_RMSE"


def test_seeded_future_samples_are_deterministic() -> None:
    """Sampling changes only when the explicit seed changes."""
    model = fitted_model()
    state = model.infer_state(state_input())
    first = model.sample_futures(state, (), {}, 4, 3, 42)
    second = model.sample_futures(state, (), {}, 4, 3, 42)
    third = model.sample_futures(state, (), {}, 4, 3, 43)
    assert np.array_equal(
        np.asarray(first.state_trajectories), np.asarray(second.state_trajectories)
    )
    assert not np.array_equal(
        np.asarray(first.state_trajectories), np.asarray(third.state_trajectories)
    )
    assert np.asarray(first.state_trajectories).shape == (3, 4, 3)


def test_future_or_multirow_observation_is_rejected() -> None:
    """The state API accepts one current row, never a suffix containing future rows."""
    model = fitted_model()
    with pytest.raises(ValueError, match="future/multi-row input rejected"):
        model.infer_state(state_input(future_row=True))


def test_action_conditioning_is_rejected() -> None:
    """Factual HFWM-R0 never silently interprets an observed/intended action."""
    model = fitted_model()
    state = model.infer_state(state_input())
    action = ActionObservation(
        action_type="staffing",
        parameters={},
        dose=None,
        timing=None,
        scope=None,
        execution_status="intention_only",
        deviation=None,
        observed_at=None,
        provenance=(),
    )
    with pytest.raises(
        ActionConditioningNotIdentifiableError,
        match="ACTION_CONDITIONING_NOT_IDENTIFIABLE",
    ):
        model.rollout(state, (action,), {}, horizon_steps=2)
