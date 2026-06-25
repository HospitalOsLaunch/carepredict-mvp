from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
import torch

from rs_jepa.config import RSJEPAConfig, SplitConfig, Stage1Config, SyntheticConfig, TrainingConfig
from rs_jepa.synthetic import ACTION_COLUMNS, SyntheticHospitalSimulator
from rs_jepa.train import _sample_windows, build_phase_a_sites
from scripts.diagnose_action_causality import config_with_interventions, run_causal_diagnostic

pytestmark = pytest.mark.rs_jepa


def tiny_cfg(*, interventions_enabled: bool = False) -> RSJEPAConfig:
    return RSJEPAConfig(
        seed=17,
        stage1=Stage1Config(
            context_steps=24,
            horizons=(6,),
            batch_size=4,
            encoder_max_steps=96,
        ),
        split=SplitConfig(temporal_holdout_weeks=1, cross_site_val_fraction=0.33, seed=17),
        synthetic=SyntheticConfig(
            n_sites=8,
            total_days=70,
            seed=17,
            interventions_enabled=interventions_enabled,
            p_intervention=0.20,
        ),
        training=TrainingConfig(max_epochs=1, steps_per_epoch=1, checkpoint_path=""),
    )


def test_interventions_disabled_preserves_seed_fixed_core_sequences() -> None:
    base_cfg = SyntheticConfig(n_sites=6, total_days=21, seed=123)
    perturbed_but_off = replace(
        base_cfg,
        interventions_enabled=False,
        p_intervention=0.95,
        max_staffing_delta=0.40,
        max_discharge_delta_per_capacity=0.10,
    )

    base = SyntheticHospitalSimulator(base_cfg).generate().temporal
    off = SyntheticHospitalSimulator(perturbed_but_off).generate().temporal

    core_columns = [column for column in base.columns if column not in ACTION_COLUMNS]
    pd.testing.assert_frame_equal(base.loc[:, core_columns], off.loc[:, core_columns])
    assert float(base.loc[:, list(ACTION_COLUMNS)].abs().to_numpy().sum()) == 0.0
    assert float(off.loc[:, list(ACTION_COLUMNS)].abs().to_numpy().sum()) == 0.0


def test_interventions_are_exposed_and_windowed_without_model_consumption() -> None:
    cfg = tiny_cfg(interventions_enabled=True)
    sites, train_sites, _cross_site_sites = build_phase_a_sites(cfg)
    assert sites[0].actions.shape[1] == len(ACTION_COLUMNS)
    assert np.any(np.abs(np.concatenate([site.actions for site in sites], axis=0)) > 0.0)

    x_window, static, action_window, horizon = _sample_windows(
        train_sites,
        cfg,
        generator=torch.Generator().manual_seed(123),
    )

    assert x_window.shape[:2] == action_window.shape[:2]
    assert action_window.shape[2] == len(ACTION_COLUMNS)
    assert static.shape[0] == x_window.shape[0]
    assert horizon == 6


def test_exogenous_actions_have_causal_effects_and_low_state_correlation() -> None:
    cfg = config_with_interventions(tiny_cfg())
    report = run_causal_diagnostic(cfg)

    assert report.staffing_effect.coefficient < 0.0
    assert report.staffing_effect.t_stat < -2.0
    assert report.discharge_occupancy_effect.coefficient < 0.0
    assert report.discharge_occupancy_effect.t_stat < -2.0
    assert report.discharge_criticality_effect.coefficient < 0.0
    assert report.discharge_criticality_effect.t_stat < -2.0
    assert abs(report.corr_staffing_surge) < 0.05
    assert abs(report.corr_staffing_occupancy) < 0.05
    assert abs(report.corr_discharge_surge) < 0.05
    assert abs(report.corr_discharge_occupancy) < 0.05
    assert report.verdict_green
