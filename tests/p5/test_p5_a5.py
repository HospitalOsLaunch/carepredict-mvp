"""A5 benchmark logic tests (no HistGradientBoosting fit: fake estimators only).

Uses development seeds (not committed partitions) and synthetic pilot-like records.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hospitalos.decision_support.snapshot import load_profile
from hospitalos.p5 import a5
from hospitalos.p5.generator import generate_structure

ROOT = Path(__file__).resolve().parents[2]
V31 = json.loads((ROOT / "docs/decision_support/P5_PROTOCOL_PARAMS_v3_1.json").read_text())


def test_params_match_protocol_fixed_and_a5_config():
    fixed = V31["P5b_design"]["models"]["fixed"]
    p = a5.hgb_params(1)
    for k, v in fixed.items():
        if isinstance(v, str) and v.startswith("default"):
            assert k not in p  # left at default: no effect without early stopping
        else:
            assert p[k] == v, k
    cfg = V31["budget"]["fit_timing_benchmark_A5"]["fits"]["config"]
    assert {k: p[k] for k in cfg} == cfg and p["random_state"] == 1 and p["early_stopping"] is False
    assert a5.SEEDS == tuple(V31["budget"]["fit_timing_benchmark_A5"]["fits"]["random_state"])
    assert a5.N_ROWS == V31["budget"]["fit_timing_benchmark_A5"]["matrix"]["rows"] == 1440
    with pytest.raises(a5.A5Error):
        a5.hgb_params(3)


def test_threads_must_be_one():
    with pytest.raises(a5.A5Error):
        a5.check_threads({})
    with pytest.raises(a5.A5Error):
        a5.check_threads({"OMP_NUM_THREADS": "4"})
    a5.check_threads({"OMP_NUM_THREADS": "1"})


def _fake_records(seed, profile, n=3, wrong=False):
    valid, _ = generate_structure("TEST_dev", seed, n, profile, twins=False)
    recs = []
    for c in valid:
        k = len(c.episodes["A"].plans) + (1 if wrong else 0)
        recs.append({"structure": 0, "parent_index": c.parent_index, "n_plans": k,
                     "U_dev_only": {"R1": [[10 * i + r for i in range(k)] for r in range(3)]}})
    return recs


def test_development_rows_join_and_tiling():
    profile = load_profile()
    recs = _fake_records(11, profile)
    data = a5.development_rows(recs, [11], profile, partition="TEST_dev", n_parents=3)
    n = len(data["y"])
    assert data["M_agg"].shape == (n, 290) and data["M_ent"].shape == (n, 718)
    assert data["y"][0] == pytest.approx(1.0)  # mean of [0, 1, 2]
    X, y = a5.tile(data["M_ent"], data["y"])
    assert X.shape == (1440, 718) and y.shape == (1440,)
    assert (X[n] == X[0]).all() and y[n] == y[0]
    assert a5.fingerprint(X, y) == a5.fingerprint(*a5.tile(data["M_ent"], data["y"]))


def test_development_rows_refuse_mismatch():
    profile = load_profile()
    with pytest.raises(a5.A5Error, match="plan count differs"):
        a5.development_rows(_fake_records(11, profile, wrong=True), [11], profile, partition="TEST_dev", n_parents=3)
    recs = _fake_records(11, profile)[:-1]
    with pytest.raises(a5.A5Error):
        a5.development_rows(recs, [11], profile, partition="TEST_dev", n_parents=3)


class FakeEstimator:
    noise = 0.0
    fit_time = 0.0

    def __init__(self, params):
        self.params = params
        self.n_iter_ = params["max_iter"]

    def fit(self, X, y):
        FakeClock.now += self.fit_time
        self.mean = float(np.mean(y))
        return self

    def predict(self, X):
        return np.full(len(X), self.mean) + self.noise * self.params["random_state"]


class FakeClock:
    now = 0.0

    @classmethod
    def __call__(cls):
        return cls.now


def test_run_family_identity_and_discard():
    X, y = np.ones((10, 3)), np.arange(10.0)
    seen = []
    out = a5.run_family("M_agg", X, y, FakeEstimator, budget_s=100.0, progress=seen.append, clock=FakeClock())
    assert out["complete"] and out["seed_identity_within_tolerance"] and len(seen) == 3
    assert [r["seed"] for r in out["results"]] == [0, 1, 2] and out["stop"] is None


def test_run_family_detects_seed_differences():
    class Noisy(FakeEstimator):
        noise = 1e-6

    out = a5.run_family("M_ent", np.ones((5, 2)), np.arange(5.0), Noisy, budget_s=100.0, clock=FakeClock())
    assert out["complete"] and not out["seed_identity_within_tolerance"]
    assert out["results"][2]["max_abs_diff_vs_seed0"] == pytest.approx(2e-6)


def test_budget_rule_stops_before_next_seed():
    class Slow(FakeEstimator):
        fit_time = 8.0

    out = a5.run_family("M_ent", np.ones((5, 2)), np.arange(5.0), Slow, budget_s=12.0, clock=FakeClock())
    assert not out["complete"] and len(out["results"]) == 1
    assert out["stop"]["reason"] == "budget_rule_before_seed" and out["stop"]["seed"] == 1
    assert not out["seed_identity_within_tolerance"]


def test_output_guard_refuses_rerun(tmp_path):
    p = tmp_path / "A5_M_agg.json"
    a5.output_guard(p)
    p.write_text("{}")
    with pytest.raises(a5.A5Error):
        a5.output_guard(p)
