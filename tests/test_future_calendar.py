import datetime as dt

import pytest

from research_lab.future_calendar import FEATURES, MINUTE_NS, calendar_grid
from research_lab.integrated_full_model_v1_contract import (
    fingerprint,
    make_v041_synthetic_spec,
    validate_spec,
)


def instant(stamp):
    return int(dt.datetime.fromisoformat(stamp).timestamp()) * 1_000_000_000


FRIDAY = instant("2026-11-20T18:00:00+01:00")
SATURDAY = FRIDAY + 24 * 60 * MINUTE_NS


@pytest.mark.parametrize(("minutes", "count"), [(15, 96), (30, 48), (60, 24)])
def test_real_time_and_weekend_are_preserved(minutes, count):
    grid = calendar_grid(FRIDAY, 24, minutes)
    assert len(grid) == count
    assert sum(row[-1] for row in grid) == 24
    assert sum(row[-2] * row[-1] for row in grid) == 6
    assert grid[6 * 60 // minutes - 1][-2] == 1
    assert grid[6 * 60 // minutes][-2] == 0
    assert all(len(row) == len(FEATURES) for row in grid)


def test_midnight_holiday_and_original_checkpoint_contract():
    grid = calendar_grid(instant("2026-12-31T23:45:00+01:00"), 1, 30)
    assert grid[0][-3:] == (0.5, 0.5, 0.5)
    assert grid[1][-3:] == (1.0, 0.0, 0.5)
    original = make_v041_synthetic_spec()
    enabled = make_v041_synthetic_spec(future_step_minutes=30)
    assert "future_calendar" not in original and fingerprint(original) != fingerprint(enabled)
    assert enabled["step_hours"] == 1
    for bad in (0, -1, 30.0, True, 45):
        with pytest.raises(ValueError):
            calendar_grid(FRIDAY, 24, bad)
    with pytest.raises(ValueError):
        calendar_grid(FRIDAY + 1, 24, 30)
    enabled["future_calendar"]["source"] = "realized_capacity"
    with pytest.raises(ValueError):
        validate_spec(enabled)


def test_same_model_two_grids_action_timing_and_checkpoint(tmp_path):
    import torch

    from rs_jepa.config import Stage1Config
    from rs_jepa.integrated_full_model_v1 import (
        IntegratedFullModelV1,
        load_untrained_assembly,
        save_untrained_assembly,
    )

    cfg = Stage1Config(
        latent_dim=8,
        rssm_deter_dim=12,
        rssm_stoch_dim=4,
        action_dim=4,
        encoder_model_dim=8,
        encoder_heads=2,
        encoder_ff_dim=16,
        encoder_depth=1,
    )
    spec = make_v041_synthetic_spec(future_step_minutes=30)
    spec.update(history_steps=4, latent_dim=8, rssm_deter_dim=12, rssm_stoch_dim=4)
    torch.manual_seed(7)
    model = IntegratedFullModelV1(spec=spec, stage1=cfg).eval()
    origin = torch.tensor([FRIDAY, SATURDAY])
    clocks = origin[:, None] - torch.arange(3, -1, -1)[None, :] * 60 * MINUTE_NS
    x = torch.zeros(2, 4, 3)
    common = {
        "static": torch.ones(2, 1),
        "actions_context": torch.zeros(2, 4, 4),
        "origin_ns": origin,
        "action_available_ns": clocks,
        "event_ns": clocks,
        "available_ns": clocks,
    }
    with torch.no_grad():
        half = model(x, **common, action_mode="no_op")
        assert half.horizons_hours == (1, 6, 24) and half.future_step_minutes == 30
        dense = model(x, **common, action_mode="no_op", return_grid_forecasts=True)
        assert dense.grid.end_offsets_minutes == tuple(range(30, 1441, 30))
        assert dense.grid.means.shape == (2, 48, 2)
        assert torch.all(dense.grid.scales > 0)
        assert dense.grid is not None and half.grid is None
        torch.testing.assert_close(dense.grid.means[:, [1, 11, 47]], half.means)
        assert half.predicted_latents.shape == (2, 48, 8)
        assert not torch.equal(half.belief_states[0, 0], half.belief_states[1, 0])
        expected, _ = model.forecast_head(half.predicted_latents, (1, 11, 47))
        assert torch.equal(half.means, expected)
        hour = model(x, **common, action_mode="no_op", future_step_minutes=60)
        assert hour.predicted_latents.shape == (2, 24, 8)
        torch.testing.assert_close(half.means, hour.means)
        assert torch.equal(hour.belief_states, half.belief_states[:, 1::2])
        hourly = torch.zeros(2, 24, 4)
        hourly[:, 1, 2] = 1
        aligned = torch.zeros(2, 48, 4)
        aligned[:, 2, 2] = 1
        a = model(
            x, **common, action_mode="counterfactual", future_actions=hourly, future_step_minutes=60
        )
        b = model(x, **common, action_mode="counterfactual", future_actions=aligned)
        assert torch.equal(a.belief_states, b.belief_states[:, 1::2])
        torch.testing.assert_close(a.means, b.means)
        schedule = torch.zeros(2, 48, 4)
        schedule[:, 1, 2] = 1  # A single request in [18:30, 19:00).
        plan = model(x, **common, action_mode="counterfactual", future_actions=schedule)
        assert torch.equal(plan.belief_states[:, 0], half.belief_states[:, 0])
        assert not torch.equal(plan.belief_states[:, 1], half.belief_states[:, 1])
        with pytest.raises(ValueError, match="shape"):
            model(
                x,
                **common,
                action_mode="counterfactual",
                future_actions=schedule,
                future_step_minutes=60,
            )
        with pytest.raises(ValueError, match="not available"):
            model(
                x,
                **common,
                action_mode="known_plan",
                future_actions=schedule,
                future_actions_available_ns=origin[:, None].expand(-1, 48) + MINUTE_NS,
            )
        save_untrained_assembly(model, tmp_path / "model", source_commit="a" * 40)
        restored = load_untrained_assembly(tmp_path / "model", stage1=cfg).eval()
        assert torch.equal(restored(x, **common, action_mode="no_op").means, half.means)
        spec["future_calendar"]["use_civil_calendar"] = False
        blind = IntegratedFullModelV1(spec=spec, stage1=cfg).eval()
        blind.load_state_dict(model.state_dict())
        unconditioned = blind(x, **common, action_mode="no_op")
        assert torch.equal(unconditioned.belief_states[0], unconditioned.belief_states[1])
        del spec["future_calendar"]
        old = IntegratedFullModelV1(spec=spec, stage1=cfg).eval()
        assert old(x, **common, action_mode="no_op").belief_states.shape[1] == 24
        assert not any("future_to_input" in k for k in old.state_dict())
        with pytest.raises(ValueError, match="calendar-enabled"):
            old(x, **common, action_mode="no_op", future_step_minutes=30)
