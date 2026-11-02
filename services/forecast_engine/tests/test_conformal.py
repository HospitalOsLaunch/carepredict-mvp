"""Split conformal intervals and adaptive conformal inference (ACI)."""

from __future__ import annotations

import numpy as np
import pytest

from services.forecast_engine.conformal import adaptive_conformal, conformal_offsets


def test_offsets_use_the_finite_sample_ranks() -> None:
    # Arrange: residuals 0..99, a two-sided 80 % interval.
    residuals = list(range(100))

    # Act
    lo, hi = conformal_offsets(residuals, 0.2)

    # Assert: ranks floor(101 * 0.1) = 10 and ceil(101 * 0.9) = 91 (1-based).
    assert (lo, hi) == (9.0, 90.0)


def test_offsets_cover_about_eighty_percent_of_exchangeable_residuals() -> None:
    # The guarantee is marginal: averaged over calibration draws.
    rng = np.random.default_rng(1)
    hits = []
    for _ in range(1_000):
        calibration = rng.normal(0, 1, 100)
        test = rng.normal(0, 1, 50)
        lo, hi = conformal_offsets(calibration, 0.2)
        hits.append(np.mean((test >= lo) & (test <= hi)))

    assert 0.785 <= np.mean(hits) <= 0.82


def test_offsets_are_asymmetric_for_skewed_residuals() -> None:
    rng = np.random.default_rng(2)
    residuals = rng.exponential(2.0, 500) - 2.0

    lo, hi = conformal_offsets(residuals, 0.2)

    assert hi > abs(lo)


def test_level_at_or_below_zero_gives_the_full_range() -> None:
    assert conformal_offsets([3.0, -1.0, 2.0], -0.1) == (-1.0, 3.0)


def test_level_at_or_above_one_gives_an_empty_width_interval() -> None:
    lo, hi = conformal_offsets([3.0, -1.0, 2.0], 1.2)

    assert lo == hi == 2.0


def test_offsets_need_residuals() -> None:
    with pytest.raises(ValueError):
        conformal_offsets([], 0.2)


def test_aci_keeps_the_target_coverage_on_stationary_residuals() -> None:
    rng = np.random.default_rng(3)
    residuals = rng.standard_t(5, 3_000)

    trace = adaptive_conformal(residuals, alpha=0.2, gamma=0.05, window=56, lag=1)

    evaluated = [c for c in trace.covered if c is not None]
    assert len(evaluated) > 2_900
    assert abs(np.mean(evaluated) - 0.8) < 0.02


def test_aci_widens_after_a_shift_while_a_frozen_interval_breaks() -> None:
    # Arrange: residuals centred on 0, then shifted by +2.5 standard deviations.
    rng = np.random.default_rng(4)
    before = rng.normal(0, 1, 300)
    after = rng.normal(2.5, 1, 300)
    residuals = np.concatenate([before, after])

    # Act
    trace = adaptive_conformal(residuals, alpha=0.2, gamma=0.05, window=56, lag=1)
    lo, hi = conformal_offsets(before[-56:], 0.2)

    # Assert
    static = np.mean((after >= lo) & (after <= hi))
    adaptive = np.mean([c for c in trace.covered[300:] if c is not None])
    assert static < 0.3
    assert abs(adaptive - 0.8) < 0.05


def test_aci_feedback_waits_for_the_lag() -> None:
    # Arrange: 20 steps of zeros (covered), then misses from step 20 on.
    residuals = [0.0] * 20 + [10.0] * 40

    # Act
    trace = adaptive_conformal(residuals, alpha=0.2, gamma=0.1, window=20, lag=3)

    # Assert: the level used at step i only reflects the outcome of step i - 3.
    used = trace.alpha_used
    assert used[22] - used[21] == pytest.approx(0.1 * 0.2)  # step 19, covered
    assert used[23] - used[22] == pytest.approx(0.1 * (0.2 - 1))  # step 20, missed


def test_aci_next_interval_uses_the_latest_window_and_level() -> None:
    residuals = list(np.linspace(-1, 1, 100))

    trace = adaptive_conformal(residuals, alpha=0.2, gamma=0.0, window=50, lag=1)

    assert trace.next_alpha == pytest.approx(0.2)
    assert trace.next_offsets == conformal_offsets(residuals[-50:], 0.2)


def test_aci_skips_steps_without_enough_calibration() -> None:
    trace = adaptive_conformal([0.0] * 12, alpha=0.2, gamma=0.05, window=56, lag=1)

    assert trace.covered[:10] == [None] * 10
    assert trace.covered[10] is not None
