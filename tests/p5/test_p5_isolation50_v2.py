"""Tests of isolation method v2 (development seeds, injected doubles; no reserved episode)."""

from __future__ import annotations

import json

import pytest

from hospitalos.decision_support.planner import Settings, recommend
from hospitalos.decision_support.reference_forecaster import PrivateOracle
from hospitalos.decision_support.snapshot import load_profile
from hospitalos.p5 import isolation50_v2 as I2
from hospitalos.p5.generator import generate_structure
from hospitalos.p5.isolation50 import IsolationFailure
from hospitalos.p5.p5a import plan_descriptor
from hospitalos.p5.pilot import structure_id


def _episode_with_plans(min_plans=3):
    profile = load_profile()
    for seed in (11, 12, 13, 14):
        valid, _ = generate_structure("TEST_dev", seed, 4, profile, twins=False)
        for c in valid:
            ep = c.episodes["A"]
            if len(ep.plans) >= min_plans:
                return ep, structure_id("TEST_dev", seed), c.parent_index
    raise AssertionError("no development episode with enough plans")


def _record(ep, sid, p):
    chosen = recommend(ep.snapshot, Settings.default()).primary_plan_id
    plans = [plan_descriptor(x, ep.snapshot.as_of) for x in ep.plans]
    return {"structure_id": sid, "parent_index": p, "plans": plans, "universe_fingerprint": ep.universe_fingerprint,
            "chosen_index": [x["plan_id"] for x in plans].index(chosen)}


def test_clean_refusal_missing_unrecorded_changed(tmp_path):
    path = tmp_path / "RESUME_PROCEDURE.json"
    assert I2.require_recorded_procedure(path, [], "k", "m") == (False, "procedure_missing")
    path.write_text(json.dumps({"module_sha256": "m", "x": 1}))
    assert I2.require_recorded_procedure(path, [], "k", "m") == (False, "procedure_not_recorded")
    led = [{"kind": "k", "payload": {"module_sha256": "m", "x": 2}}]
    assert I2.require_recorded_procedure(path, led, "k", "m") == (False, "procedure_differs_from_ledger")
    led = [{"kind": "k", "payload": {"module_sha256": "m", "x": 1}}]
    assert I2.require_recorded_procedure(path, led, "k", "other") == (False, "module_changed_since_procedure")
    assert I2.require_recorded_procedure(path, led, "k", "m") == (True, "ok")


def test_habitual_insensitive_but_other_plan_sensitive_is_detected(monkeypatch):
    ep, sid, p = _episode_with_plans()
    real = I2.oracle_signature

    def habitual_blind(truth, snapshot, plan, cfg):
        return "constant" if plan.plan_id == ep.plans[0].plan_id else real(truth, snapshot, plan, cfg)

    monkeypatch.setattr(I2, "oracle_signature", habitual_blind)
    out = I2.check_episode_v2(ep, _record(ep, sid, p), Settings.default(), "test")
    assert out["T04a"] == "DETECTED" and out["T04a_witness"]["plan_index"] > 0
    assert out["T03b"] == "pass" and out["T03b_plan_truth_pairs_checked"] == len(ep.plans) * 5


def test_all_signatures_insensitive_gives_non_informatif_not_success(monkeypatch):
    ep, sid, p = _episode_with_plans()
    monkeypatch.setattr(I2, "oracle_signature", lambda *a: "constant")
    out = I2.check_episode_v2(ep, _record(ep, sid, p), Settings.default(), "test")
    assert out["T04a"] == "NON_INFORMATIF" and out["T04a_witness"] is None
    assert out["T03a"] == out["T03b"] == out["T04b"] == out["T04c"] == out["T04d"] == "pass"


def test_injected_true_leak_is_detected(monkeypatch):
    ep, sid, p = _episode_with_plans()
    captured = {}

    class Leaky:
        reads_private = False

        def outcome(self, snapshot, plan, config):
            return PrivateOracle(captured["truth"]).outcome(snapshot, plan, config)

    original = I2.check_isolation

    def spying(make_backend, snapshot, plan, config, a, b):
        def factory(truth):
            captured["truth"] = truth
            backend = make_backend(truth)
            return Leaky() if backend.__class__.__name__ == "ReferenceForecaster" else backend
        return original(factory, snapshot, plan, config, a, b)

    monkeypatch.setattr(I2, "check_isolation", spying)
    with pytest.raises(IsolationFailure, match="T03b_product_backend_output_depends_on_truth"):
        I2.check_episode_v2(ep, _record(ep, sid, p), Settings.default(), "test")


def test_false_negative_of_witness_stops(monkeypatch):
    ep, sid, p = _episode_with_plans()
    real_check = I2.check_isolation

    def blind_detector(make_backend, snapshot, plan, config, a, b):
        if make_backend is PrivateOracle:
            return None  # a detector that never fires
        return real_check(make_backend, snapshot, plan, config, a, b)

    monkeypatch.setattr(I2, "check_isolation", blind_detector)
    monkeypatch.setattr(I2, "oracle_signature", lambda truth, *a: str(id(truth)))  # all signatures distinct
    with pytest.raises(IsolationFailure, match="T04a_false_negative"):
        I2.check_episode_v2(ep, _record(ep, sid, p), Settings.default(), "test")
