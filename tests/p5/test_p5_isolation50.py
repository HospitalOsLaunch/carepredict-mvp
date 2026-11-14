"""Tests of the 50-episode isolation check logic (development seeds; no reserved episode)."""

from __future__ import annotations

import pytest

from hospitalos.decision_support.planner import Settings
from hospitalos.decision_support.snapshot import load_profile
from hospitalos.p5 import isolation50 as I
from hospitalos.p5.generator import generate_structure
from hospitalos.p5.p5a import plan_descriptor
from hospitalos.p5.pilot import structure_id


def test_select_is_deterministic_round_robin_and_reads_ids_only():
    parents = [(f"s{i:02d}", p) for i in range(30) for p in range(10)]
    a = I.select(parents, "c")
    assert a == I.select(list(reversed(parents)), "c") and len(a) == 50
    assert len({s for s, _ in a[:30]}) == 30  # one per structure first
    assert len(set(a)) == 50
    assert a != I.select(parents, "other-commitment")


def _dev_episode():
    profile = load_profile()
    valid, _ = generate_structure("TEST_dev", 11, 3, profile, twins=False)
    sid = structure_id("TEST_dev", 11)
    eps = {(sid, c.parent_index): c.episodes["A"] for c in valid}
    return profile, sid, eps


def _record(ep, sid, p, chosen_plan_id):
    plans = [plan_descriptor(x, ep.snapshot.as_of) for x in ep.plans]
    return {"structure_id": sid, "parent_index": p, "plans": plans, "universe_fingerprint": ep.universe_fingerprint,
            "chosen_index": [x["plan_id"] for x in plans].index(chosen_plan_id)}


def test_check_episode_passes_on_development_episode():
    from hospitalos.decision_support.planner import recommend

    profile, sid, eps = _dev_episode()
    settings = Settings.default()
    (key, ep), = list(eps.items())[:1]
    rec = _record(ep, sid, key[1], recommend(ep.snapshot, settings).primary_plan_id)
    out = I.check_episode(ep, rec, settings, "test")
    assert out["T03b_plans_checked"] == len(ep.plans) and out["T04a_detector_fired_on_plans"] >= 1
    rebuilt = I.reconstruct([key], {sid: 11}, {key: rec}, profile, partition="TEST_dev", n_parents=3)
    assert rebuilt[key].universe_fingerprint == ep.universe_fingerprint


def test_reconstruction_mismatch_stops():
    profile, sid, eps = _dev_episode()
    (key, ep), = list(eps.items())[:1]
    rec = _record(ep, sid, key[1], ep.plans[0].plan_id)
    rec["universe_fingerprint"] = "0" * 64
    with pytest.raises(I.IsolationFailure, match="reconstruction_universe_mismatch"):
        I.reconstruct([key], {sid: 11}, {key: rec}, profile, partition="TEST_dev", n_parents=3)


def test_choice_differing_from_record_stops():
    profile, sid, eps = _dev_episode()
    settings = Settings.default()
    (key, ep), = list(eps.items())[:1]
    from hospitalos.decision_support.planner import recommend

    chosen = recommend(ep.snapshot, settings).primary_plan_id
    other = next(p.plan_id for p in ep.plans if p.plan_id != chosen) if len(ep.plans) > 1 else None
    if other is None:
        pytest.skip("single-plan universe")
    with pytest.raises(I.IsolationFailure, match="T03a_choice_differs_from_record"):
        I.check_episode(ep, _record(ep, sid, key[1], other), settings, "test")


def test_leaking_product_backend_is_detected(monkeypatch):
    """Mutation: a 'product' backend that reads the truth must make T03-b fail."""
    from hospitalos.decision_support.planner import recommend
    from hospitalos.decision_support.reference_forecaster import PrivateOracle

    profile, sid, eps = _dev_episode()
    settings = Settings.default()
    (key, ep), = list(eps.items())[:1]
    rec = _record(ep, sid, key[1], recommend(ep.snapshot, settings).primary_plan_id)
    captured = {}

    class Leaky:
        reads_private = False

        def __init__(self):
            captured.setdefault("n", 0)
            captured["n"] += 1

        def outcome(self, snapshot, plan, config):
            return PrivateOracle(captured["truth"]).outcome(snapshot, plan, config)

    original = I.check_isolation

    def spying(make_backend, snapshot, plan, config, a, b):
        def factory(truth):
            captured["truth"] = truth
            backend = make_backend(truth)
            return Leaky() if backend.__class__.__name__ == "ReferenceForecaster" else backend
        return original(factory, snapshot, plan, config, a, b)

    monkeypatch.setattr(I, "check_isolation", spying)
    with pytest.raises(I.IsolationFailure, match="T03b_product_backend_output_depends_on_truth"):
        I.check_episode(ep, rec, settings, "test")
