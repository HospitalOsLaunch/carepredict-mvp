"""Regression tests for RSSM action-channel alignment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from scripts.train_rssm_synthetic import build_action_matrix
from services.api.schemas.simulate import ActionStep
from services.ml.world_model.action_channels import ACTION_CHANNEL_INDEX, ACTION_CHANNELS


def test_action_step_vector_order_matches_canonical_rssm_channels() -> None:
    assert ACTION_CHANNELS == (
        "admissions",
        "discharges",
        "surgeries",
        "transfers_in",
        "transfers_out",
    )
    assert ACTION_CHANNEL_INDEX == {
        "admissions": 0,
        "discharges": 1,
        "surgeries": 2,
        "transfers_in": 3,
        "transfers_out": 4,
    }

    step = ActionStep(
        scheduled_admissions=1,
        scheduled_discharges=2,
        scheduled_surgeries=3,
        expected_transfers_in=4,
        expected_transfers_out=5,
        staff_redeployments=99,
    )

    assert step.to_vector() == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_legacy_expected_transfers_maps_to_transfers_in_only() -> None:
    step = ActionStep(
        scheduled_admissions=0,
        scheduled_discharges=0,
        scheduled_surgeries=0,
        expected_transfers=7,
        staff_redeployments=99,
    )

    assert step.to_vector() == [0.0, 0.0, 0.0, 7.0, 0.0]


def test_build_action_matrix_uses_same_channel_positions() -> None:
    timestamps = [datetime(2025, 1, 1, hour, tzinfo=UTC) for hour in range(3)]
    dataset = SimpleNamespace(
        admissions=[
            SimpleNamespace(admission_time=timestamps[0] + timedelta(minutes=12)),
            SimpleNamespace(admission_time=timestamps[2] + timedelta(minutes=45)),
        ],
        discharges=[SimpleNamespace(discharge_time=timestamps[1] + timedelta(minutes=30))],
    )

    actions = build_action_matrix(dataset, timestamps, action_dim=len(ACTION_CHANNELS))

    assert actions[:, ACTION_CHANNEL_INDEX["admissions"]].tolist() == [1.0, 0.0, 1.0]
    assert actions[:, ACTION_CHANNEL_INDEX["discharges"]].tolist() == [0.0, 1.0, 0.0]
    assert actions[:, ACTION_CHANNEL_INDEX["surgeries"]].tolist() == [0.0, 0.0, 0.0]
    assert actions[:, ACTION_CHANNEL_INDEX["transfers_in"]].tolist() == [0.0, 0.0, 0.0]
    assert actions[:, ACTION_CHANNEL_INDEX["transfers_out"]].tolist() == [0.0, 0.0, 0.0]
