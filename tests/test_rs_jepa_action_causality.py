from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
import torch

from rs_jepa.config import RSJEPAConfig, SplitConfig, Stage1Config, SyntheticConfig, TrainingConfig
from rs_jepa.synthetic import ACTION_COLUMNS, ACTION_DELTA_COLUMNS, SyntheticHospitalSimulator
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

    generated_columns = set(ACTION_COLUMNS) | set(ACTION_DELTA_COLUMNS)
    core_columns = [column for column in base.columns if column not in generated_columns]
    pd.testing.assert_frame_equal(base.loc[:, core_columns], off.loc[:, core_columns])
    assert float(base.loc[:, list(ACTION_COLUMNS)].abs().to_numpy().sum()) == 0.0
    assert float(off.loc[:, list(ACTION_COLUMNS)].abs().to_numpy().sum()) == 0.0
    assert float(base.loc[:, list(ACTION_DELTA_COLUMNS)].abs().to_numpy().sum()) == 0.0
    assert float(off.loc[:, list(ACTION_DELTA_COLUMNS)].abs().to_numpy().sum()) == 0.0


def test_interventions_are_exposed_and_windowed_without_model_consumption() -> None:
    cfg = tiny_cfg(interventions_enabled=True)
    sites, train_sites, _cross_site_sites = build_phase_a_sites(cfg)
    assert sites[0].actions.shape[1] == len(ACTION_COLUMNS)
    assert sites[0].action_deltas.shape[1] == len(ACTION_DELTA_COLUMNS)
    assert np.any(np.abs(np.concatenate([site.actions for site in sites], axis=0)) > 0.0)

    x_window, static, action_window, action_delta_window, horizon = _sample_windows(
        train_sites,
        cfg,
        generator=torch.Generator().manual_seed(123),
    )

    assert x_window.shape[:2] == action_window.shape[:2]
    assert action_delta_window.shape[:2] == action_window.shape[:2]
    assert action_window.shape[2] == len(ACTION_COLUMNS)
    assert action_delta_window.shape[2] == len(ACTION_DELTA_COLUMNS)
    assert static.shape[0] == x_window.shape[0]
    assert horizon == 6
    context = cfg.stage1.context_steps
    assert action_window[:, context:].shape[1] == horizon
    assert action_delta_window[:, context:].shape[1] == horizon


def test_delta_criticality_staffing_matches_manual_sigmoid_recalculation() -> None:
    cfg = SyntheticConfig(n_sites=3, total_days=14, seed=321, interventions_enabled=True)
    temporal = SyntheticHospitalSimulator(cfg).generate().temporal
    occupancy_ratio = temporal["occupancy_ratio"].to_numpy()
    inflow_surge = temporal["inflow_surge"].to_numpy()
    base_staffing_ratio = temporal["staffing"].to_numpy() / temporal["capacity"].to_numpy()
    no_staffing = 1.0 / (
        1.0
        + np.exp(
            -(
                1.60 * (occupancy_ratio - 0.90)
                + 4.80 * (inflow_surge - 1.0)
                + 0.80 * (np.clip(occupancy_ratio / base_staffing_ratio, 0.0, 3.0) - 1.0)
            )
        )
    )
    manual_delta = temporal["criticality"].to_numpy() - no_staffing
    np.testing.assert_allclose(
        temporal["delta_criticality_staffing"].to_numpy(),
        manual_delta,
        rtol=0,
        atol=1e-12,
    )


def test_delta_criticality_discharge_zero_when_discharge_action_is_zero() -> None:
    cfg = SyntheticConfig(
        n_sites=3,
        total_days=14,
        seed=654,
        interventions_enabled=True,
        p_intervention=1.0,
        max_discharge_delta_per_capacity=0.0,
    )
    temporal = SyntheticHospitalSimulator(cfg).generate().temporal
    assert np.allclose(temporal["discharge_delta"].to_numpy(), 0.0, atol=0.0)
    np.testing.assert_allclose(
        temporal["delta_criticality_discharge"].to_numpy(),
        0.0,
        rtol=0,
        atol=1e-12,
    )


def test_discharge_counterfactual_replay_reuses_paired_noise() -> None:
    n = 12
    capacity = 100
    base_saturation = 0.70
    discharge_rate = 0.01
    inflow = np.linspace(0.5, 2.0, n)
    discharge_noise = np.linspace(0.88, 1.12, n - 1)
    occupancy, discharges = SyntheticHospitalSimulator._replay_without_discharge_delta(
        n=n,
        capacity=capacity,
        base_saturation=base_saturation,
        discharge_rate=discharge_rate,
        inflow=inflow,
        discharge_noise=discharge_noise,
    )

    manual_occupancy = np.empty(n, dtype=float)
    manual_discharges = np.empty(n, dtype=float)
    manual_occupancy[0] = capacity * base_saturation
    for t in range(n - 1):
        pressure_slowdown = np.clip(1.15 - manual_occupancy[t] / capacity, 0.45, 1.15)
        manual_discharges[t] = (
            discharge_rate * manual_occupancy[t] * pressure_slowdown * discharge_noise[t]
        )
        manual_occupancy[t + 1] = np.clip(
            manual_occupancy[t] + inflow[t] - manual_discharges[t],
            0.0,
            capacity * 1.35,
        )
    manual_discharges[-1] = discharge_rate * manual_occupancy[-1]

    np.testing.assert_allclose(occupancy, manual_occupancy, rtol=0, atol=1e-12)
    np.testing.assert_allclose(discharges, manual_discharges, rtol=0, atol=1e-12)


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
