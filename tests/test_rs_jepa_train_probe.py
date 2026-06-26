from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
import torch

from rs_jepa.config import RSJEPAConfig, SplitConfig, Stage1Config, SyntheticConfig, TrainingConfig
from rs_jepa.encoder import validate_observable_columns
from rs_jepa.probe import (
    collect_probe_matrices,
    collect_probe_matrix,
    interpret_static_ablation,
    r2_score,
)
from rs_jepa.splits import TEMPORAL_VAL, TRAIN
from rs_jepa.train import (
    build_phase_a_sites,
    load_encoder_checkpoint,
    load_stage1_checkpoint,
    run_stage1_training,
    save_encoder_checkpoint,
)

pytestmark = pytest.mark.rs_jepa


def tiny_cfg(checkpoint_path: str = "") -> RSJEPAConfig:
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
            probe_rank_threshold=4.0,
            probe_stride=24,
            probe_max_samples=200,
            checkpoint_path=checkpoint_path,
        ),
    )


def test_stage1_training_loop_runs_without_nan_and_logs_rank():
    artifacts = run_stage1_training(tiny_cfg(), log=False)
    assert len(artifacts.history) == 1
    row = artifacts.history[0]
    for key in ["loss", "pred", "var", "cov", "effective_rank", "per_dim_std_mean"]:
        assert np.isfinite(row[key])
    assert row["effective_rank"] > 1.0


def test_stage1_training_with_interventions_drives_action_gru_gradients():
    cfg = tiny_cfg()
    cfg = replace(
        cfg,
        synthetic=replace(
            cfg.synthetic,
            interventions_enabled=True,
            p_intervention=1.0,
        ),
    )
    artifacts = run_stage1_training(cfg, log=False)
    assert len(artifacts.history) == 1
    assert artifacts.history[0]["action_grad_norm"] > 0.0


def test_ema_target_moves_during_training():
    artifacts = run_stage1_training(tiny_cfg(), log=False)
    assert artifacts.initial_target_distance > 0.0
    assert artifacts.target_update_distance > 0.0


def test_probe_harness_returns_finite_r2_and_beats_mean_baseline():
    artifacts = run_stage1_training(tiny_cfg(), log=False)
    result = artifacts.probes["temporal"]
    assert np.isfinite(result.latent_r2)
    assert np.isfinite(result.latent_r2_without_static)
    assert np.isfinite(result.raw_r2)
    assert np.isfinite(result.mean_baseline_r2)
    assert np.isfinite(result.per_timestep_r2_with_static)
    assert np.isfinite(result.per_timestep_r2_without_static)
    assert np.isfinite(result.per_timestep_raw_r2)
    assert np.isfinite(result.per_timestep_mean_baseline_r2)
    assert np.isfinite(result.effective_rank_with_static)
    assert np.isfinite(result.effective_rank_without_static)
    assert result.n_train > 0
    assert result.n_eval > 0
    assert result.per_timestep_n_train > result.n_train
    assert result.per_timestep_n_eval > result.n_eval
    assert result.latent_r2 > result.mean_baseline_r2


def test_probe_without_static_path_preserves_shapes_and_reuses_encoder():
    cfg = tiny_cfg()
    artifacts = run_stage1_training(cfg, log=False)
    _sites, train_sites, _cross_site_sites = build_phase_a_sites(cfg)
    before = [param.detach().clone() for param in artifacts.encoder.parameters()]
    with_static, raw, y = collect_probe_matrix(
        artifacts.encoder,
        train_sites,
        cfg,
        TEMPORAL_VAL,
        device=torch.device("cpu"),
        zero_static=False,
    )
    without_static, raw_zeroed, y_zeroed = collect_probe_matrix(
        artifacts.encoder,
        train_sites,
        cfg,
        TEMPORAL_VAL,
        device=torch.device("cpu"),
        zero_static=True,
    )
    assert with_static.shape == without_static.shape
    assert raw.shape == raw_zeroed.shape
    assert y.shape == y_zeroed.shape
    assert np.isfinite(without_static).all()
    assert not np.allclose(with_static, without_static)
    for old_param, new_param in zip(before, artifacts.encoder.parameters(), strict=True):
        assert torch.equal(old_param, new_param.detach())


def test_both_probe_variants_use_same_frozen_encoder_instance():
    cfg = tiny_cfg()
    artifacts = run_stage1_training(cfg, log=False)
    _sites, train_sites, _cross_site_sites = build_phase_a_sites(cfg)
    before = [param.detach().clone() for param in artifacts.encoder.parameters()]
    collect_probe_matrix(
        artifacts.encoder,
        train_sites,
        cfg,
        TRAIN,
        device=torch.device("cpu"),
        zero_static=False,
    )
    collect_probe_matrix(
        artifacts.encoder,
        train_sites,
        cfg,
        TRAIN,
        device=torch.device("cpu"),
        zero_static=True,
    )
    for old_param, new_param in zip(before, artifacts.encoder.parameters(), strict=True):
        assert torch.equal(old_param, new_param.detach())


def test_per_timestep_probe_aligns_each_latent_to_matching_kappa_t():
    cfg = tiny_cfg()
    artifacts = run_stage1_training(cfg, log=False)
    _sites, train_sites, _cross_site_sites = build_phase_a_sites(cfg)
    matrices = collect_probe_matrices(
        artifacts.encoder,
        train_sites,
        cfg,
        TEMPORAL_VAL,
        device=torch.device("cpu"),
    )
    assert matrices.full_latents.shape[0] == matrices.y_full.shape[0]
    assert matrices.raw_full.shape[0] == matrices.y_full.shape[0]
    assert matrices.full_latents.shape[0] == matrices.y_last.shape[0] * cfg.stage1.context_steps
    assert matrices.raw_full.shape[1] == matrices.raw_last.shape[1]


def test_probe_interpretation_refuses_collapsed_rank():
    artifacts = run_stage1_training(tiny_cfg(), log=False)
    result = artifacts.probes["temporal"]
    message = interpret_static_ablation(result, rank_threshold=10_000.0)
    assert "LATENT COLLAPSED" in message
    assert "NOT interpretable" in message


def test_encoder_checkpoint_roundtrip(tmp_path):
    checkpoint = tmp_path / "encoder.pt"
    artifacts = run_stage1_training(tiny_cfg(checkpoint_path=str(checkpoint)), log=False)
    loaded = load_encoder_checkpoint(checkpoint, device=torch.device("cpu"))
    assert loaded.n_obs == artifacts.encoder.n_obs
    assert loaded.n_static == artifacts.encoder.n_static
    old_params = list(artifacts.encoder.parameters())
    new_params = list(loaded.encoder.parameters())
    assert len(old_params) == len(new_params)
    for old_param, new_param in zip(old_params, new_params, strict=True):
        assert torch.allclose(old_param.detach().cpu(), new_param.detach().cpu())


def test_full_stage1_checkpoint_roundtrip_includes_dynamic_chain(tmp_path):
    checkpoint = tmp_path / "stage1_full.pt"
    artifacts = run_stage1_training(tiny_cfg(checkpoint_path=str(checkpoint)), log=False)
    loaded = load_stage1_checkpoint(checkpoint, device=torch.device("cpu"))

    assert loaded.n_obs == artifacts.encoder.n_obs
    assert loaded.n_static == artifacts.encoder.n_static
    for old_param, new_param in zip(
        artifacts.encoder.parameters(),
        loaded.encoder.parameters(),
        strict=True,
    ):
        assert torch.allclose(old_param.detach().cpu(), new_param.detach().cpu())
    for old_param, new_param in zip(
        artifacts.rssm.parameters(),
        loaded.rssm.parameters(),
        strict=True,
    ):
        assert torch.allclose(old_param.detach().cpu(), new_param.detach().cpu())
    for old_param, new_param in zip(
        artifacts.predictor.parameters(),
        loaded.predictor.parameters(),
        strict=True,
    ):
        assert torch.allclose(old_param.detach().cpu(), new_param.detach().cpu())


def test_old_encoder_only_checkpoint_reports_missing_dynamic_chain(tmp_path):
    checkpoint = tmp_path / "encoder_only.pt"
    artifacts = run_stage1_training(tiny_cfg(), log=False)
    save_encoder_checkpoint(
        checkpoint,
        artifacts.encoder,
        tiny_cfg(),
        n_obs=artifacts.encoder.n_obs,
        n_static=artifacts.encoder.n_static,
    )

    loaded = load_encoder_checkpoint(checkpoint, device=torch.device("cpu"))
    assert loaded.n_obs == artifacts.encoder.n_obs
    with pytest.raises(ValueError, match="Checkpoint Stage 1 incomplet"):
        load_stage1_checkpoint(checkpoint, device=torch.device("cpu"))


def test_probe_r2_metric_sanity_beats_trivial_mean_on_linear_signal():
    y = np.linspace(0.0, 1.0, 50)
    perfect = y.copy()
    mean_pred = np.full_like(y, fill_value=float(y.mean()))
    assert r2_score(y, perfect) > r2_score(y, mean_pred)


def test_encoder_input_contract_guard_still_rejects_hidden_fields():
    with pytest.raises(ValueError, match="Colonnes interdites"):
        validate_observable_columns(["inflow_per_capacity", "criticality"])
