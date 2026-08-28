from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

import pytest

from hfwm.contracts import (
    ActionObservation,
    BeliefState,
    DynamicsCore,
    StateEncoderInput,
    TokenBatch,
)
from hfwm.models.mechanistic import (
    MechanisticQueueSemiMarkov,
    hard_violation_rate,
)


def _batch(
    values: Mapping[str, object] | None = None,
    *,
    mask: Mapping[str, object] | None = None,
    delay: float = 0.0,
) -> TokenBatch:
    return TokenBatch(
        values=values
        or {
            "occupancy": 74.0,
            "inflow": 7.0,
            "discharges": 5.0,
            "staffing": 17.0,
            "pressure": 1.1,
            "capacity": 90.0,
        },
        attention_mask=mask or {},
        entity_ids=("hospital",),
        event_ids=(),
        available_at=("2026-08-28T08:00:00Z",),
        provenance=(),
        metadata={"observation_delay_hours": delay},
    )


def _state(
    model: MechanisticQueueSemiMarkov,
    batch: TokenBatch | None = None,
) -> BeliefState:
    return model.infer_state(
        StateEncoderInput(
            observations=batch or _batch(),
            history=(),
            entity_graph={},
            recording_process={},
            context={},
            site_metadata={},
        )
    )


def test_implements_dynamics_core_and_identity_is_config_bound() -> None:
    first = MechanisticQueueSemiMarkov()
    second = MechanisticQueueSemiMarkov()

    assert isinstance(first, DynamicsCore)
    assert first.identity.implementation_id == "mechanistic_queue_semimarkov"
    assert first.identity.artifact_hash == second.identity.artifact_hash


def test_each_transition_audits_exact_conservation_and_capacity() -> None:
    model = MechanisticQueueSemiMarkov()
    prediction = model.predict_next(_state(model), (), {})
    payload = prediction.next_state_distribution
    assert isinstance(payload, Mapping)
    audit = payload["conservation_audit"]
    assert isinstance(audit, Mapping)

    assert audit["residual"] == pytest.approx(0.0, abs=1e-9)
    assert payload["occupancy"] == pytest.approx(
        audit["previous_occupancy"]
        + audit["admitted_inflow"]
        - audit["discharges"]
    )
    assert 0.0 <= payload["occupancy"] <= payload["capacity"]
    assert all(payload[name] >= 0.0 for name in ("inflow", "discharges", "staffing", "pressure"))


def test_rollout_is_free_running_and_uncertainty_grows_with_horizon() -> None:
    model = MechanisticQueueSemiMarkov()
    rollout = model.rollout(_state(model), (), {}, horizon_steps=24)

    assert rollout.free_running is True
    assert rollout.horizon_steps == 24
    assert isinstance(rollout.state_trajectories, Sequence)
    assert len(rollout.state_trajectories) == 24
    uncertainty = rollout.uncertainty_by_horizon
    assert isinstance(uncertainty, Sequence)
    assert isinstance(uncertainty[0], Mapping)
    assert isinstance(uncertainty[-1], Mapping)
    assert uncertainty[0]["scalar"] < uncertainty[-1]["scalar"]
    assert hard_violation_rate(rollout) == 0.0


def test_seeded_future_sampling_is_deterministic_but_seed_sensitive() -> None:
    model = MechanisticQueueSemiMarkov()
    state = _state(model)

    first = model.sample_futures(state, (), {}, horizon_steps=12, sample_count=4, seed=982)
    repeated = model.sample_futures(state, (), {}, horizon_steps=12, sample_count=4, seed=982)
    other = model.sample_futures(state, (), {}, horizon_steps=12, sample_count=4, seed=983)

    assert first.state_trajectories == repeated.state_trajectories
    assert first.event_trajectories == repeated.event_trajectories
    assert first.state_trajectories != other.state_trajectories
    assert hard_violation_rate(first) == 0.0


def test_missing_and_delayed_observations_are_explicitly_signalled() -> None:
    model = MechanisticQueueSemiMarkov()
    state = _state(
        model,
        _batch(
            {
                "occupancy": 51.0,
                "inflow": 4.0,
                "discharges": 3.0,
                "staffing": 12.0,
                "capacity": 75.0,
            },
            mask={"staffing": False},
            delay=8.0,
        ),
    )
    uncertainty = state.state_uncertainty
    assert isinstance(state.value, Mapping)
    assert isinstance(uncertainty, Mapping)

    assert "staffing" in state.value["missing_variables"]
    assert "pressure" in state.value["missing_variables"]
    assert uncertainty["observation_delay_hours"] == 8.0
    assert uncertainty["scalar"] > model.config.base_uncertainty
    assert {item.get("signal") for item in state.provenance} >= {
        "masked_or_missing",
        "observation_delay",
    }


def test_state_update_carries_forward_masked_joint_variables() -> None:
    model = MechanisticQueueSemiMarkov()
    initial = _state(model)
    updated = model.update_state(
        initial,
        _batch({"occupancy": 61.0}, delay=2.0),
        {},
    )
    assert isinstance(initial.value, Mapping)
    assert isinstance(updated.value, Mapping)

    assert updated.value["occupancy"] == 61.0
    assert updated.value["inflow"] == initial.value["inflow"]
    assert "inflow" in updated.value["missing_variables"]
    assert any(item.get("signal") == "state_update_carried_forward" for item in updated.provenance)


def test_masked_observation_does_not_contribute_to_score() -> None:
    model = MechanisticQueueSemiMarkov()
    rollout = model.rollout(_state(model), (), {}, horizon_steps=2)
    score = model.score_observed_trajectory(
        rollout,
        (
            {
                "occupancy": 10_000.0,
                "inflow": 6.0,
                "mask": {"occupancy": False},
            },
            {"occupancy": None, "staffing": 17.0},
        ),
    )

    assert score.scoring_rule == "masked_negative_scaled_squared_error_v1"
    assert score.metadata["evaluated_values"] == 2
    assert score.metadata["masked_values"] == 8
    assert score.metadata["hard_violation_rate"] == 0.0


def test_action_conditioning_is_rejected_everywhere() -> None:
    model = MechanisticQueueSemiMarkov()
    state = _state(model)
    action = ActionObservation(
        action_type="add_staff",
        parameters={},
        dose=None,
        timing=None,
        scope=None,
        execution_status="unknown",
        deviation=None,
        observed_at=None,
        provenance=(),
    )

    with pytest.raises(ValueError, match="ACTION_CONDITIONING_NOT_IDENTIFIABLE"):
        model.predict_next(state, (action,), {})
    with pytest.raises(ValueError, match="ACTION_CONDITIONING_NOT_IDENTIFIABLE"):
        model.rollout(state, (action,), {}, horizon_steps=2)
    with pytest.raises(ValueError, match="ACTION_CONDITIONING_NOT_IDENTIFIABLE"):
        model.sample_futures(state, (action,), {}, horizon_steps=2, sample_count=2, seed=1)


def test_constraint_projection_makes_invalid_initial_values_safe() -> None:
    model = MechanisticQueueSemiMarkov()
    state = _state(
        model,
        _batch(
            {
                "occupancy": 120.0,
                "inflow": -4.0,
                "discharges": -2.0,
                "staffing": -1.0,
                "pressure": -3.0,
                "capacity": 80.0,
            }
        ),
    )
    assert isinstance(state.value, Mapping)

    assert state.value["occupancy"] == 80.0
    assert state.value["inflow"] == 0.0
    assert state.value["discharges"] == 0.0
    assert state.value["staffing"] == 0.0
    assert state.value["pressure"] >= 0.0
    rollout = model.rollout(state, (), {}, horizon_steps=6)
    assert hard_violation_rate(rollout) == 0.0


def test_missing_conservation_audit_counts_as_hard_violation() -> None:
    model = MechanisticQueueSemiMarkov()
    rollout = model.rollout(_state(model), (), {}, horizon_steps=1)
    states = rollout.state_trajectories
    assert isinstance(states, list)
    assert isinstance(states[0], Mapping)
    tampered = dict(states[0])
    del tampered["conservation_audit"]
    tampered_rollout = replace(rollout, state_trajectories=[tampered])

    assert hard_violation_rate(tampered_rollout) == 1.0
