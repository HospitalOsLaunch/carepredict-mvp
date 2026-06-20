from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rs_jepa.config import SyntheticConfig
from rs_jepa.synthetic import (
    ABSOLUTE_FORBIDDEN_LABEL_INPUTS,
    SyntheticHospitalData,
    SyntheticHospitalSimulator,
    assert_criticality_is_unitless,
)


def small_cfg(seed: int = 7) -> SyntheticConfig:
    return SyntheticConfig(n_sites=6, total_days=21, seed=seed)


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
