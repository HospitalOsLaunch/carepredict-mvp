from __future__ import annotations

import numpy as np
import pytest

from rs_jepa.config import RSJEPAConfig, SplitConfig, Stage1Config, SyntheticConfig, TrainingConfig
from rs_jepa.encoder import validate_observable_columns
from rs_jepa.probe import r2_score
from rs_jepa.train import run_stage1_training

pytestmark = pytest.mark.rs_jepa


def tiny_cfg() -> RSJEPAConfig:
    return RSJEPAConfig(
        seed=11,
        stage1=Stage1Config(
            latent_dim=12,
            encoder_model_dim=12,
            encoder_depth=1,
            encoder_heads=2,
            encoder_ff_dim=24,
            encoder_dropout=0.0,
            encoder_max_steps=96,
            rssm_deter_dim=16,
            rssm_stoch_dim=6,
            predictor_hidden_dim=24,
            predictor_depth=1,
            context_steps=24,
            horizons=(6,),
            batch_size=4,
            ema_ramp_steps=20,
            block_mask_min_frac=0.15,
            block_mask_max_frac=0.30,
            channel_mask_prob=0.20,
        ),
        split=SplitConfig(temporal_holdout_weeks=1, cross_site_val_fraction=0.33, seed=11),
        synthetic=SyntheticConfig(n_sites=6, total_days=28, seed=11),
        training=TrainingConfig(
            max_epochs=1,
            steps_per_epoch=2,
            probe_every_epochs=1,
            early_collapse_rank_threshold=1.0,
            probe_stride=24,
            probe_max_samples=200,
        ),
    )


def test_stage1_training_loop_runs_without_nan_and_logs_rank():
    artifacts = run_stage1_training(tiny_cfg(), log=False)
    assert len(artifacts.history) == 1
    row = artifacts.history[0]
    for key in ["loss", "pred", "var", "cov", "effective_rank", "per_dim_std_mean"]:
        assert np.isfinite(row[key])
    assert row["effective_rank"] > 1.0


def test_ema_target_moves_during_training():
    artifacts = run_stage1_training(tiny_cfg(), log=False)
    assert artifacts.initial_target_distance > 0.0
    assert artifacts.target_update_distance > 0.0


def test_probe_harness_returns_finite_r2_and_beats_mean_baseline():
    artifacts = run_stage1_training(tiny_cfg(), log=False)
    result = artifacts.probes["temporal"]
    assert np.isfinite(result.latent_r2)
    assert np.isfinite(result.raw_r2)
    assert np.isfinite(result.mean_baseline_r2)
    assert result.n_train > 0
    assert result.n_eval > 0
    assert result.latent_r2 > result.mean_baseline_r2


def test_probe_r2_metric_sanity_beats_trivial_mean_on_linear_signal():
    y = np.linspace(0.0, 1.0, 50)
    perfect = y.copy()
    mean_pred = np.full_like(y, fill_value=float(y.mean()))
    assert r2_score(y, perfect) > r2_score(y, mean_pred)


def test_encoder_input_contract_guard_still_rejects_hidden_fields():
    with pytest.raises(ValueError, match="Colonnes interdites"):
        validate_observable_columns(["inflow_per_capacity", "criticality"])
