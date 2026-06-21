from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rs_jepa.config import SyntheticConfig, load_config
from rs_jepa.diagnostics import run_diagnostic_for_seed, summarize_rows
from rs_jepa.synthetic import (
    ABSOLUTE_FORBIDDEN_LABEL_INPUTS,
    SyntheticHospitalData,
    SyntheticHospitalSimulator,
    assert_criticality_is_unitless,
)

pytestmark = pytest.mark.rs_jepa


def small_cfg(seed: int = 7) -> SyntheticConfig:
    return SyntheticConfig(n_sites=6, total_days=21, seed=seed)


@pytest.fixture(scope="module")
def phase_a_honesty_rows():
    cfg = load_config("configs/phaseA.yaml")
    return {seed: run_diagnostic_for_seed(cfg, seed) for seed in range(5)}


def test_synthetic_simulator_is_deterministic_and_heterogeneous():
    first = SyntheticHospitalSimulator(small_cfg()).generate()
    second = SyntheticHospitalSimulator(small_cfg()).generate()
    pd.testing.assert_frame_equal(first.temporal, second.temporal)
    assert first.static["capacity_norm"].nunique() > 1
    assert first.static["base_saturation"].nunique() > 1


def test_synthetic_outputs_have_known_criticality_and_levels():
    data = SyntheticHospitalSimulator(small_cfg()).generate()
    assert set(data.temporal_feature_columns).issubset(data.temporal.columns)
    assert set(data.static_feature_columns).issubset(data.static.columns)
    assert data.temporal["criticality"].between(0.0, 1.0).all()
    assert set(data.temporal["criticality_level"].unique()).issubset({0, 1, 2, 3})
    assert data.temporal["criticality"].std() > 0.05
    assert data.temporal.groupby("site_id")["criticality"].mean().std() > 0.008


def test_criticality_label_metadata_is_unitless():
    data = SyntheticHospitalSimulator(small_cfg()).generate()
    assert not (set(data.criticality_inputs) & ABSOLUTE_FORBIDDEN_LABEL_INPUTS)
    assert_criticality_is_unitless(data)


def test_criticality_label_rejects_absolute_threshold_inputs():
    data = SyntheticHospitalData(
        temporal=pd.DataFrame(),
        static=pd.DataFrame(),
        temporal_feature_columns=(),
        static_feature_columns=(),
        criticality_inputs=("occupancy_ratio", "capacity"),
    )
    with pytest.raises(ValueError, match="seuils absolus interdits"):
        assert_criticality_is_unitless(data)


def test_phase_a_features_do_not_include_care_load_label_as_feature():
    data = SyntheticHospitalSimulator(small_cfg()).generate()
    assert "criticality" not in data.temporal_feature_columns
    assert "criticality_level" not in data.temporal_feature_columns
    matrix = data.temporal.loc[:, data.temporal_feature_columns].to_numpy(dtype=float)
    assert np.isfinite(matrix).all()


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_phase_a_honesty_gates_hold_per_seed(seed: int, phase_a_honesty_rows):
    row = phase_a_honesty_rows[seed]
    assert row["t1_frac"] >= 0.82
    assert row["t2"] >= 0.10
    assert 0.55 <= row["t3a_mean_r2"] <= 0.88
    assert row["t3a_bulk_fraction"] >= 0.85
    assert bool(row["t3a_low_mae_ok"])
    assert 0.12 <= row["hidden_share"] <= 0.45
    assert 0.30 <= row["struct_ratio"] <= 0.55
    print(
        "T3b research result "
        f"seed={seed} gain={row['t3b_gain']:.3f} "
        f"naive={row['t3b_naive_r2']:.3f} cond={row['t3b_cond_r2']:.3f}"
    )


def test_phase_a_honesty_gates_hold_across_five_seeds(phase_a_honesty_rows):
    rows = [phase_a_honesty_rows[seed] for seed in range(5)]
    summary = summarize_rows(rows)
    assert summary["all_gates"]
    assert summary["min_t2"] >= 0.10
    print(
        "T3b gains are reported, not gated: "
        + ", ".join(f"{row['t3b_gain']:.3f}" for row in rows)
    )
