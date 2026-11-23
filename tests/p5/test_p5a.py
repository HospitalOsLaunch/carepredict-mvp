"""P5a executor and analysis tests (synthetic records and development seeds; no reserved data)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from hospitalos.decision_support.planner import Settings
from hospitalos.decision_support.snapshot import CONFIG_DIR, load_json, load_profile
from hospitalos.p5 import p5a as X
from hospitalos.p5 import p5a_analysis as A
from hospitalos.p5.eval_adapter import Outcome
from hospitalos.p5.pilot import PilotStop, run_identity


def plans4():
    return [
        {"plan_id": "h", "coord": [], "reinf": [], "class": "H", "planned_hours": 0, "interventions": 0},
        {"plan_id": "c", "coord": ["c1"], "reinf": [], "class": "C", "planned_hours": 0, "interventions": 1},
        {"plan_id": "r", "coord": [], "reinf": ["r1"], "class": "R", "planned_hours": 6, "interventions": 1},
        {"plan_id": "cr", "coord": ["c1"], "reinf": ["r1"], "class": "CR", "planned_hours": 6, "interventions": 2},
    ]


def rec(U, chosen=3, abst=False, sid="s0", p=0):
    k = len(U)
    z = [[0] * 4 for _ in range(k)]
    return {"structure_id": sid, "structure_index": 0, "parent_index": p, "plans": plans4(), "chosen_index": chosen,
            "abstention_as_habitual": abst,
            "outcomes": {r: {"U": U, "realised_hours": z, "lent_hours": z, "waiting": z, "beds": z,
                             "peak": [[None] * 4] * k, "above": [[None] * 4] * k} for r in ("R1", "R2")}}


def test_lex_index_tolerance_then_hours_then_interventions():
    assert A.lex_index([100, 90, 80, 95], [0, 0, 6, 0], [0, 1, 1, 2]) == 1  # 90 within 15 of 80, 0 h
    assert A.lex_index([200, 90, 80, 50], [0, 0, 6, 6], [0, 1, 1, 2]) == 3


def test_parent_stats_metrics_and_interaction():
    U = [[150, 120, 130, 90], [150, 120, 130, 90], [150, 120, 130, 90]]
    st = A.parent_stats(rec(U), "R1")
    assert st["gain"] == 60 and st["headroom"] == 60 and st["regret_plan"] == 0
    assert st["res_only"] == 20 and st["coord_at_equal_res"] == 40
    assert st["coord_only"] == 30 and st["res_given_coord"] == 30
    assert st["interaction"] == 120 + 130 - 90 - 150 == 10
    assert st["interaction"] == st["coord_at_equal_res"] - st["coord_only"]
    assert st["U_lex"] == 90 and st["harm"] == 0 and st["planned_hours"] == 6
    h = A.parent_stats(rec(U, chosen=0, abst=True), "R1")
    assert h["gain"] == 0 and h["interaction"] == 0 and h["abstention"] == 1


def test_harm_event_uses_mean_over_k():
    U = [[100, 100, 100, 140], [100, 100, 100, 100], [100, 100, 100, 100]]  # mean excess 13.3 < 15
    assert A.parent_stats(rec(U), "R1")["harm"] == 0
    U2 = [[100, 100, 100, 160], [100, 100, 100, 100], [100, 100, 100, 100]]  # 20 > 15
    assert A.parent_stats(rec(U2), "R1")["harm"] == 1


def _records(gains_by_structure, headroom=None):
    out = []
    for si, gains in enumerate(gains_by_structure):
        for pi, g in enumerate(gains):
            star = 100 - (headroom if headroom is not None else max(g, 0))
            U = [[100, 100, 100, 100 - g]] * 3
            U = [[100, 100, max(star, 0) if star < 100 - g else 100, 100 - g] for _ in range(3)]
            r = rec(U, sid=f"s{si}", p=pi)
            r["structure_index"] = si
            out.append(r)
    return out


def test_analyse_verdicts_capture_and_harm():
    meta = [{"candidates": 10, "exclusions": {}}] * 30
    big = _records([[40] * 10 for _ in range(30)])
    res = A.analyse(big, meta, "R1", 7, 200, True, primary=True)
    assert res["verdict"] == "demonstrated_in_this_synthetic_protocol"
    assert res["guardrails"]["harm"]["harmed_structures"] == 0 and res["guardrails"]["harm"]["ok"]
    small = _records([[2] * 10 for _ in range(30)])
    res2 = A.analyse(small, meta, "R1", 7, 200, True, primary=True)
    assert res2["verdict"] == "insufficient"
    assert res2["capture"]["defined"] is False and res2["capture"]["point"] is None
    assert res2["capture"]["clipped"] is False
    r2 = A.analyse(big, meta, "R2", 7, 200, True, primary=False)
    assert "robustness" in r2["verdict"] and r2["role"].startswith("robustness")
    excl = A.analyse(big, [{"candidates": 10, "exclusions": {"universe_incomplete": 1}}] * 30, "R1", 7, 200, True, True)
    assert not excl["guardrails"]["exclusion_ok"] and excl["verdict"] == "inconclusive"
    expl = A.analyse(big, meta, "R1", 7, 200, False, True)
    assert expl["verdict"] == "exploratory"


def test_bootstrap_deterministic_and_structure_level():
    s = [np.array([[0.0, 1.0]] * 3), np.array([[10.0, 1.0]])]
    a = A.bootstrap(s, 300, 5)
    assert (a == A.bootstrap(s, 300, 5)).all()
    assert A.ci(a[:, 0]) == [0.0, 10.0]
    assert A.weighted_means(s)[0] == 5.0


def test_precision_projection_formula():
    gi = A.STATS.index("gain")
    structs = []
    for m in (0.0, 10.0, 20.0, 30.0):
        arr = np.zeros((2, len(A.STATS)))
        arr[:, gi] = m
        structs.append(arr)
    p = A.precision_projection(structs, 30)
    sd = np.std([0, 10, 20, 30], ddof=1)
    assert math.isclose(p["projected_half_width"], A.Z * sd / math.sqrt(30))
    assert p["precision_sufficient"] == (p["projected_half_width"] <= 7.5)


def test_require_freeze():
    with pytest.raises(X.FreezeMissing):
        X.require_freeze([{"kind": "commitment"}], {})
    recs = [{"kind": "freeze_F_a", "payload": {"files_sha256": {"a": "1", "b": "2"}}}]
    assert X.require_freeze(recs, {"a": "1", "b": "2"})["files_sha256"]["a"] == "1"
    with pytest.raises(X.FreezeMissing, match="files changed since F_a"):
        X.require_freeze(recs, {"a": "1", "b": "3"})


def _identity(k=1):
    c = {"stage": "TEST", "commitment_id": "test", "code_sha256": {"x": "y"}}
    env = {"python": "3.11.18", "freeze_sha256": "f"}
    return run_identity(c, "TEST_dev", [11], 2, k, ("R1",), env, "p5a-test")


def test_run_segment_records_complete_universe_and_resume(tmp_path):
    profile, settings = load_profile(), Settings.default()
    score = load_json(CONFIG_DIR / "PRESSURE_SCORE_CONFIG.json")
    ident = _identity()
    out = X.run_segment(out_dir=tmp_path, identity=ident, seeds=[11], indices=[0], profile=profile,
                        settings=settings, score=score)
    assert out["new_parents"] == 2
    run = tmp_path / "runs" / ident["run_id"]
    recs = [json.loads(x) for x in (run / "pilot_parents.jsonl").read_text().splitlines()]
    for r in recs:
        assert r["plans"][0]["class"] == "H" and len(r["outcomes"]["R1"]["U"][0]) == r["n_plans"]
        assert 0 <= r["chosen_index"] < r["n_plans"]
        assert r["outcomes"]["R1"]["peak"][0][0] is not None
        A.parent_stats(r, "R1")
    meta = [json.loads(x) for x in (run / "structures.jsonl").read_text().splitlines()]
    assert meta[0]["valid"] == 2
    again = X.run_segment(out_dir=tmp_path, identity=ident, seeds=[11], indices=[0], profile=profile,
                          settings=settings, score=score)
    assert again["new_parents"] == 0 and len((run / "pilot_parents.jsonl").read_text().splitlines()) == 2


def test_run_segment_stops_on_violation(tmp_path):
    def bad(*a, **k):
        return Outcome(0, 0, 0, 0, 0, 0, 0, ("injected",))

    with pytest.raises(PilotStop):
        X.run_segment(out_dir=tmp_path, identity=_identity(), seeds=[11], indices=[0], profile=load_profile(),
                      settings=Settings.default(), score=None, outcome_fn=bad)
