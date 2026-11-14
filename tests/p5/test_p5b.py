"""P5b logic tests: synthetic records, development seeds, fake models (no HGB fit)."""

from __future__ import annotations

import numpy as np
import pytest

from hospitalos.decision_support.planner import Settings
from hospitalos.decision_support.snapshot import CONFIG_DIR, load_json, load_profile
from hospitalos.p5 import p5b as B
from hospitalos.p5 import p5b_analysis as BA
from hospitalos.p5 import p5b_isolation as BI
from hospitalos.p5.isolation50 import IsolationFailure
from hospitalos.p5.pilot import PilotStop, run_identity, structure_id


def _plans():
    return [
        {"plan_id": "h", "key": [], "coord": [], "reinf": [], "class": "H", "planned_hours": 0, "interventions": 0},
        {"plan_id": "c", "key": ["coord:X1"], "coord": ["coord:X1"], "reinf": [], "class": "C", "planned_hours": 0, "interventions": 1},
        {"plan_id": "r", "key": ["renfort:O"], "coord": [], "reinf": ["renfort:O"], "class": "R", "planned_hours": 6, "interventions": 1},
        {"plan_id": "cr", "key": ["coord:X1", "renfort:O"], "coord": ["coord:X1"], "reinf": ["renfort:O"], "class": "CR", "planned_hours": 6, "interventions": 2},
    ]


def _twin(U, planner=0):
    k = len(U)
    z = [[0] * 4 for _ in range(k)]
    out = {r: {"U": U, "realised_hours": z, "lent_hours": z, "waiting": z, "beds": z, "peak": z, "above": z} for r in ("R1", "R2")}
    return {"n_plans": 4, "universe_fingerprint": "f", "plans": _plans(), "outcomes": out, "planner": {"chosen_index": planner}}


def _rec(UA, UB, sid="s", p=0, si=0):
    return {"structure_id": sid, "structure_index": si, "parent_index": p, "twins": {"A": _twin(UA), "B": _twin(UB)}}


def test_precheck_terms_unsigned_and_informative():
    UA = [[100, 50, 100, 100]] * 3          # coordinating X1 helps a lot in A
    UB = [[100, 100, 100, 100]] * 3         # not in B
    assert B.precheck_terms(_rec(UA, UB))[0] == pytest.approx(2500.0)
    assert B.precheck_terms(_rec(UB, UA))[0] == pytest.approx(2500.0)  # opposite sign, same contribution
    recs = [_rec(UA, UB, f"s{i}", p, i) for i in range(4) for p in range(3)]
    res = B.precheck(recs, seed=1, resamples=200)
    assert res["informative"] and res["rate_best_homologous_plan_changes"] == 1.0
    flat = [_rec(UB, UB, f"s{i}", p, i) for i in range(4) for p in range(3)]
    assert not B.precheck(flat, seed=1, resamples=200)["informative"]


def test_choose_obj_lex_ties():
    plans = _plans()
    assert B.choose([100, 90, 80, 95], plans) == 1      # 90 within 15 of 80, 0 h
    assert B.choose([200, 90, 80, 50], plans) == 3
    idx = [("s", 0, "A", i) for i in range(4)] + [("s", 0, "B", i) for i in range(4)]
    recs = [_rec([[100, 50, 100, 100]] * 3, [[100, 100, 100, 100]] * 3)]
    ch = B.choices(np.array([100, 50, 100, 100, 100, 100, 100, 100.0]), idx, recs)
    assert ch == {("s", 0, "A"): 1, ("s", 0, "B"): 0}
    assert B.realised_choice_value(ch, recs) == pytest.approx(75.0)


def test_analysis_delta_rep_harm_and_verdicts():
    good = [_rec([[100, 50, 100, 100]] * 3, [[100, 50, 100, 100]] * 3, f"s{i}", p, i) for i in range(30) for p in range(4)]
    ca = {(r["structure_id"], r["parent_index"], t): 0 for r in good for t in "AB"}   # M_agg keeps habitual
    ce = {(r["structure_id"], r["parent_index"], t): 1 for r in good for t in "AB"}   # M_ent coordinates
    meta = [{"candidates": 4, "exclusions": {}}] * 30
    res = BA.analyse(good, meta, ca, ce, "R1", 3, 200, True, True, True)
    assert res["point"]["delta_rep"] == 50 and res["verdict"] == "demonstrated_in_this_synthetic_protocol"
    assert res["guardrails"]["harm_M_ent"]["harmed_structures"] == 0
    bad = BA.analyse(good, meta, ce, ca, "R1", 3, 200, True, True, True)   # swapped: M_ent keeps habitual
    assert bad["verdict"] == "insufficient" and bad["guardrails"]["harm_M_ent"]["harmed_structures"] == 0
    harmful = [_rec([[100, 50, 100, 130]] * 3, [[100, 50, 100, 100]] * 3, f"s{i}", p, i) for i in range(30) for p in range(4)]
    ce3 = {(r["structure_id"], r["parent_index"], t): 3 for r in harmful for t in "AB"}
    hres = BA.analyse(harmful, meta, ca, ce3, "R1", 3, 200, True, True, True)
    assert hres["guardrails"]["harm_M_ent"]["harmed_structures"] == 30 and not hres["guardrails"]["harm_M_ent"]["ok"]
    assert BA.analyse(good, meta, ca, ce, "R1", 3, 200, False, True, True)["verdict"] == "exploratory"
    assert BA.analyse(good, meta, ca, ce, "R1", 3, 200, True, False, True)["verdict"] == "inconclusive"
    st = BA.parent_stats(good[0], ca, ce, "R1")
    assert st["ent_coord_at_equal_res"] == 50 and st["ent_res_only"] == 0 and st["same_choice"] == 0


def _identity(k=1, n=2):
    c = {"stage": "TEST", "commitment_id": "test", "code_sha256": {"x": "y"}}
    return run_identity(c, "TEST_dev", [11], n, k, ("R1",), {"python": "3.11.18", "freeze_sha256": "f"}, "p5b-test")


def test_run_segment_twins_and_matrices(tmp_path):
    profile = load_profile()
    ident = _identity()
    out = B.run_segment(out_dir=tmp_path, identity=ident, seeds=[11], indices=[0], profile=profile,
                        score=load_json(CONFIG_DIR / "PRESSURE_SCORE_CONFIG.json"), with_planner=False)
    assert out["new_parents"] == 2
    d = tmp_path / "executions" / ident["run_id"]
    import json
    recs = [json.loads(x) for x in (d / "parents.jsonl").read_text().splitlines()]
    assert all(set(r["twins"]) == {"A", "B"} for r in recs)
    m = B.build_matrices(recs, {structure_id("TEST_dev", 11): 11}, "TEST_dev", profile, 2)
    n_rows = sum(r["twins"][t]["n_plans"] for r in recs for t in "AB")
    assert m["M_agg"].shape == (n_rows, 290) and m["M_ent"].shape == (n_rows, 718)
    assert np.isclose(m["w"].sum(), 4.0)  # one unit of weight per twin episode
    again = B.run_segment(out_dir=tmp_path, identity=ident, seeds=[11], indices=[0], profile=profile, score=None, with_planner=False)
    assert again["new_parents"] == 0


def test_run_segment_stops_on_violation(tmp_path):
    from hospitalos.p5.eval_adapter import Outcome

    with pytest.raises(PilotStop):
        B.run_segment(out_dir=tmp_path, identity=_identity(), seeds=[11], indices=[0], profile=load_profile(), score=None,
                      with_planner=False, outcome_fn=lambda *a: Outcome(0, 0, 0, 0, 0, 0, 0, ("injected",)))


class FakeModel:
    def predict(self, X):
        return np.asarray(X, float).sum(axis=1)


def _dev_twin_episode():
    from hospitalos.p5.generator import generate_structure

    valid, _ = generate_structure("TEST_dev", 12, 2, load_profile(), twins=True)
    return valid[0].episodes["A"]


def test_isolation_check_passes_with_public_only_model():
    ep = _dev_twin_episode()
    out = BI.check_episode(ep, {"M_agg": FakeModel(), "M_ent": FakeModel()}, load_profile(), Settings.default(), "test")
    assert out["F1_T03"] == "pass" and out["T04a"] in {"DETECTED", "NON_INFORMATIF"}


def test_isolation_detects_a_model_reading_the_truth(monkeypatch):
    ep = _dev_twin_episode()
    state = {"n": 0}
    real = BI.T.realise

    def spying(*a, **k):
        state["n"] += 1
        return real(*a, **k)

    class Leaky(FakeModel):
        def predict(self, X):
            return super().predict(X) + state["n"]

    monkeypatch.setattr(BI.T, "realise", spying)
    with pytest.raises(IsolationFailure, match="F1_T03_model_input_or_choice_changed|T03"):
        BI.check_episode(ep, {"M_agg": Leaky(), "M_ent": FakeModel()}, load_profile(), Settings.default(), "test")


def test_isolation_select_and_freeze_guard():
    eps = [(f"s{i}", p, t) for i in range(8) for p in range(15) for t in "AB"]
    s = BI.select(eps, "c")
    assert len(s) == 50 and len({e[0] for e in s[:8]}) == 8 and s == BI.select(list(reversed(eps)), "c")
    with pytest.raises(BI.FreezeMissing):
        BI.require_freeze([{"kind": "freeze_F_a"}], {})
    led = [{"kind": "freeze_F_b", "payload": {"files_sha256": {"a": "1"}}}]
    assert BI.require_freeze(led, {"a": "1"})
    with pytest.raises(BI.FreezeMissing, match="changed"):
        BI.require_freeze(led, {"a": "2"})
