"""Focused tests for shared HFWM pretraining and bounded site adaptation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import numpy.typing as npt
import pytest

from hfwm.contracts.interfaces import StateEncoderInput, TokenBatch
from hfwm.models.local import JointDynamicsConfig, LocalJointDynamicsModel
from hfwm.models.shared import SharedHFWMModel

FloatArray = npt.NDArray[np.float64]


def trajectories(*, offset: float, episodes: int = 5, steps: int = 10) -> FloatArray:
    """Create a small coupled site trajectory tensor."""
    result = np.zeros((episodes, steps, 3), dtype=np.float64)
    for episode in range(episodes):
        result[episode, 0] = [8.0 + offset + episode, 2.0, 1.0 + episode]
        for step in range(1, steps):
            previous = result[episode, step - 1]
            result[episode, step] = [
                0.70 * previous[0] + 0.40 * previous[1] + 1.0,
                0.15 * previous[0] + 0.65 * previous[1] + 0.3,
                0.20 * previous[1] + 0.50 * previous[2] + 0.2,
            ]
    return result


def token(values: FloatArray, mask: FloatArray, *, hour: int) -> TokenBatch:
    """Build one point-in-time token row."""
    instant = datetime(2026, 2, 1, tzinfo=UTC) + timedelta(hours=hour)
    return TokenBatch(
        values=values,
        attention_mask=mask,
        entity_ids=("unit",),
        event_ids=(f"e-{hour}",),
        available_at=(instant.isoformat(),),
        provenance=(),
    )


def state_input() -> StateEncoderInput:
    """Build history with missingness and a changed recording process."""
    return StateEncoderInput(
        observations=token(np.asarray([12.0, np.nan, 2.0]), np.asarray([1.0, 0.0, 1.0]), hour=1),
        history=(token(np.asarray([10.0, 3.0, 1.0]), np.ones(3), hour=0),),
        entity_graph={},
        recording_process={"delay_hours": 2.0, "missing_rate": 0.4},
        context={},
        site_metadata={},
    )


def pretrained() -> SharedHFWMModel:
    """Fit a shared backbone on two tiny in-memory sites."""
    model = SharedHFWMModel(JointDynamicsConfig(observation_dim=3, recording_dim=2))
    return model.pretrain(
        trajectories_by_site={
            "site-a": trajectories(offset=0.0),
            "site-b": trajectories(offset=4.0),
        }
    )


def test_pretraining_is_deterministic_and_site_identity_ablated() -> None:
    """Renaming/reordering sites does not alter the content-pooled backbone."""
    first = pretrained()
    renamed = SharedHFWMModel(JointDynamicsConfig(observation_dim=3, recording_dim=2))
    renamed.pretrain(
        trajectories_by_site={
            "unrelated-z": trajectories(offset=4.0),
            "unrelated-y": trajectories(offset=0.0),
        }
    )
    assert first.backbone_hash() == renamed.backbone_hash()
    assert first.pretraining_site_count == 2
    assert first.parameter_report()["site_identity_feature"] is False


def test_belief_update_tracks_missingness_and_recording_process() -> None:
    """Missing values retain past state while reliability and recorder state update."""
    model = pretrained()
    state = model.infer_state(state_input())
    packed = np.asarray(state.value)
    values = packed[:3]
    reliability = packed[3:6]
    recording = packed[6:]
    assert values.tolist() == [12.0, 3.0, 2.0]
    assert reliability[1] < reliability[0]
    assert recording.tolist() == [2.0, 0.4]
    updated = model.update_state(
        state,
        token(np.asarray([13.0, 4.0, np.nan]), np.asarray([1.0, 1.0, 0.0]), hour=2),
        {"delay_hours": 1.0, "missing_rate": 0.2},
    )
    updated_values = np.asarray(updated.value)[:3]
    assert updated_values.tolist() == [13.0, 4.0, 2.0]


def test_adaptation_is_bounded_and_backbone_is_immutable() -> None:
    """Only the local adapter changes, using at most the frozen 256 transitions."""
    model = pretrained()
    before = model.backbone_hash()
    summary = model.adapt_site(
        site_id="site-new",
        trajectories=trajectories(offset=8.0, episodes=40, steps=9),
        local_data_budget=256,
    )
    assert summary.local_examples_used == 256
    assert summary.local_data_budget == 256
    assert summary.backbone_hash_before == before
    assert summary.backbone_hash_after == before == model.backbone_hash()
    assert len(summary.adapter_hash) == 64
    with pytest.raises(ValueError, match=r"\[1, 256\]"):
        model.adapt_site(
            site_id="site-new",
            trajectories=trajectories(offset=8.0),
            local_data_budget=257,
        )


def test_parameter_capacity_matches_local_control() -> None:
    """Shared and local learned candidates reserve exactly the same capacity."""
    config = JointDynamicsConfig(observation_dim=5, recording_dim=3)
    local = LocalJointDynamicsModel(config)
    shared = SharedHFWMModel(config)
    assert local.core_parameter_count == shared.core_parameter_count
    assert local.adapter_parameter_count == shared.adapter_parameter_count
    assert local.parameter_count == shared.parameter_count
    assert shared.parameter_count <= 2_000_000
    assert shared.parameter_report()["belief_features"] == [
        "values",
        "observation_reliability",
        "recording_process",
    ]


def test_shared_rollout_is_free_running_with_growing_uncertainty() -> None:
    """Shared factual rollouts inherit the same joint dynamics and constraints."""
    model = pretrained()
    state = model.infer_state(state_input())
    rollout = model.rollout(state, (), {"occupancy_capacity": 20.0}, horizon_steps=4)
    states = np.asarray(rollout.state_trajectories)
    uncertainty = np.asarray(rollout.uncertainty_by_horizon)
    assert rollout.free_running
    assert states.shape == (4, 3)
    assert np.all(states >= 0.0)
    assert np.all(states[:, 0] <= 20.0)
    assert np.all(np.diff(uncertainty, axis=0) >= 0.0)
