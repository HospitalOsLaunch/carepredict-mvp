"""P5.1 tests (P5-PROTO-2): generator, private realisation, evaluation adapter, features, analysis.

Development seeds only (small fixed integers, disjoint from the committed random 62-bit seeds);
no reserved partition is generated here.
"""

from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

from hospitalos.decision_support.planner import Settings, recommend
from hospitalos.decision_support.reference_forecaster import ForecastConfig, PrivateOracle
from hospitalos.decision_support.snapshot import load_profile
from hospitalos.p5 import features as F
from hospitalos.p5 import truth as T
from hospitalos.p5.analysis import (
    capture,
    clopper_pearson_upper,
    harm_bound,
    hierarchical_bootstrap,
    percentile_interval,
    structure_weighted_mean,
    theta_term,
    verdict,
)
from hospitalos.p5.eval_adapter import offer_key, outcome
from hospitalos.p5.generator import (
    EXCLUSION_REASONS,
    EpisodeSpec,
    OfferSpec,
    StaySpec,
    generate_candidate,
    generate_structure,
    make_twin,
    realise_episode,
    u01,
)

DEV_SEEDS = (11, 12, 13)
COMMIT = "test-commitment"


@pytest.fixture(scope="module")
def profile():
    return load_profile()


@pytest.fixture(scope="module")
def structures(profile):
    out = {}
    for seed in DEV_SEEDS:
        out[seed] = generate_structure("TEST_dev", seed, 4, profile, twins=True)
    return out


@pytest.fixture(scope="module")
def episodes(structures):
    return [c.episodes[t] for valid, _ in structures.values() for c in valid for t in ("A", "B")]


# ---------------------------------------------------------------- generator


def test_generator_deterministic(profile):
    a = generate_candidate("TEST_dev", 11, 0, profile, twins=True)
    b = generate_candidate("TEST_dev", 11, 0, profile, twins=True)
    assert a.excluded == b.excluded
    for t in a.episodes:
        assert a.episodes[t].snapshot.fingerprint == b.episodes[t].snapshot.fingerprint
        assert [p.plan_id for p in a.episodes[t].plans] == [p.plan_id for p in b.episodes[t].plans]


def test_exclusions_counted_before_filtering_with_public_reasons(structures):
    for valid, every in structures.values():
        assert len(valid) == 4
        assert [c for c in every if c.excluded is None] == valid
        assert all(c.excluded in EXCLUSION_REASONS for c in every if c.excluded is not None)
        assert [c.parent_index for c in every] == list(range(len(every)))


def test_universe_complete_bounded_with_habitual(episodes):
    for ep in episodes:
        assert ep.report.complete and 1 <= len(ep.plans) <= 16
        assert ep.plans[0].is_baseline
        assert len(ep.snapshot.stays) <= 8 and len(ep.snapshot.reinforcements) <= 4
        assert len(ep.snapshot.admissions) <= 4 and not ep.snapshot.issues


def test_twins_same_aggregates_same_universe_size_moved_logistics(structures, profile):
    for valid, _ in structures.values():
        for c in valid:
            a, b = c.episodes["A"], c.episodes["B"]
            fa, fb = F.SnapshotFeatures(a.snapshot, a.sidecar, profile), F.SnapshotFeatures(b.snapshot, b.sidecar, profile)
            assert fa.b0 == fb.b0  # F5: identical B0 block
            assert len(a.plans) == len(b.plans)
            moved = [
                (sa.logistics != sb.logistics)
                for sa, sb in zip(a.spec.stays, b.spec.stays, strict=True)
            ]
            assert sum(moved) >= 2
            assert [s.care_day for s in a.spec.stays] == [s.care_day for s in b.spec.stays]


def test_twin_degenerate_when_logistics_identical(structures):
    valid, _ = structures[11]
    spec = valid[0].episodes["A"].spec
    same = next(s.logistics for s in spec.stays if s.authorized)
    stays = tuple(replace(s, logistics=same) if s.authorized else s for s in spec.stays)
    assert make_twin(replace(spec, stays=stays)) is None


# ---------------------------------------------------------------- realisation and adapter


def test_realisation_deterministic_and_universe_invariant(episodes):
    ep = episodes[0]
    r1 = T.realise(ep, "R1", 1, COMMIT)
    assert T.realise(ep, "R1", 1, COMMIT) == r1
    assert T.realise(ep, "R2", 1, COMMIT).truth.values["readiness"] == r1.truth.values["readiness"]
    before = ep.universe_fingerprint
    T.realisations(ep, ("R1", "R2"), 3, COMMIT)
    assert ep.universe_fingerprint == before


def test_adapter_equals_v6_private_oracle_when_all_offers_present(episodes, profile):
    config = ForecastConfig(profile=profile, score=None, seeds=(), start=episodes[0].snapshot.as_of, hours=24)
    for ep in episodes[:6]:
        real = T.realise(ep, "R1", 1, COMMIT)
        all_present = replace(real, presence={k: 1 for k in real.presence})
        for plan in ep.plans:
            out = outcome(ep.snapshot, plan, all_present, profile)
            run = PrivateOracle(real.truth).outcome(ep.snapshot, plan, config)
            assert out.U == sum(run.uncovered_unit) + sum(run.uncovered_waiting)
            assert out.violations == ()


def _requested_selected(ep):
    for plan in ep.plans:
        for a in plan.actions:
            if a.type == "reinforcement" and a.conditional:
                return plan, next(o for o in ep.snapshot.reinforcements if o.option_id == a.target)
    return None


def test_t_p5_r1_presence_changes_realised_coverage_not_recommendation(episodes, profile):
    settings = Settings.default()
    strict = 0
    checked = 0
    for ep in episodes:
        found = _requested_selected(ep)
        if found is None:
            continue
        plan, option = found
        real = T.realise(ep, "R1", 1, COMMIT)
        key = offer_key(option)
        present = outcome(ep.snapshot, plan, replace(real, presence={**real.presence, key: 1}), profile)
        absent = outcome(ep.snapshot, plan, replace(real, presence={**real.presence, key: 0}), profile)
        assert absent.U >= present.U
        assert absent.realised_reinforcement_hours == present.realised_reinforcement_hours - option.hours
        assert absent.planned_reinforcement_hours == present.planned_reinforcement_hours
        strict += absent.U > present.U
        checked += 1
        if checked == 1:
            reco_a = recommend(ep.snapshot, settings)
            reco_b = recommend(ep.snapshot, settings)
            assert reco_a.recommendation_id == reco_b.recommendation_id
            assert "truth" not in inspect.signature(recommend).parameters
    assert checked >= 1 and strict >= 1


def _renamed(spec: EpisodeSpec) -> EpisodeSpec:
    offers = tuple(
        OfferSpec(**{**o.__dict__, "option_id": "Q" + o.option_id[::-1]}) for o in reversed(spec.offers)
    )
    return replace(spec, offers=offers)


def test_t_p5_r2_presence_keyed_by_offer_not_order_or_id(episodes):
    ep = next(e for e in episodes if len(e.spec.offers) >= 2)
    renamed = realise_episode(_renamed(ep.spec), load_profile())
    for regime in ("R1", "R2"):
        a = T.realise(ep, regime, 2, COMMIT).presence
        b = T.realise(renamed, regime, 2, COMMIT).presence
        assert a == b
    # call order does not matter
    first = [T.realise(ep, r, 1, COMMIT).presence for r in ("R2", "R1")]
    assert first[::-1] == [T.realise(ep, r, 1, COMMIT).presence for r in ("R1", "R2")]


def test_presence_marginals_r1_r2_and_confirmed():
    n = 4000
    r1 = sum(T.presence_draw("R1", 0.7, False, u01("t", i, "o"), u01("t", i, "p")) for i in range(n)) / n
    r2 = sum(T.presence_draw("R2", 0.9, False, u01("t", i, "o"), u01("t", i, "p")) for i in range(n)) / n
    assert abs(r1 - 0.7) < 0.03 and abs(r2 - 0.5) < 0.03
    assert all(T.presence_draw(r, 1.0, True, 0.999, 0.999) == 1 for r in ("R1", "R2"))
    # R2 within-pool correlation: two offers of the same pool agree more often than independent
    agree = sum(
        T.presence_draw("R2", 0.5, False, u01("a", i), u01("pool", i))
        == T.presence_draw("R2", 0.5, False, u01("b", i), u01("pool", i))
        for i in range(n)
    ) / n
    assert agree > 0.6


# ---------------------------------------------------------------- features


def test_f1_features_do_not_read_private_truth(episodes, profile):
    src = inspect.getsource(F)
    assert "PrivateTruth" not in src and "Realisation" not in src and "from .truth" not in src
    ep = episodes[0]
    before = [F.SnapshotFeatures(ep.snapshot, ep.sidecar, profile).row(p, "M_ent")[1] for p in ep.plans]
    T.realisations(ep, ("R1", "R2"), 3, COMMIT)
    after = [F.SnapshotFeatures(ep.snapshot, ep.sidecar, profile).row(p, "M_ent")[1] for p in ep.plans]
    assert before == after


def _rename_all(spec: EpisodeSpec) -> tuple[EpisodeSpec, dict[str, str]]:
    m = {s.stay_id: f"ZZ{i:02d}" for i, s in enumerate(reversed(spec.stays))}
    beds = {b[0]: f"BED{i:02d}" for i, b in enumerate(reversed(spec.beds))}
    stays = tuple(replace(s, stay_id=m[s.stay_id], bed_id=beds[s.bed_id]) for s in spec.stays)
    bed_rows = tuple((beds[b[0]], *b[1:]) for b in spec.beds)
    adms = tuple({**a, "request_id": "RQ" + a["request_id"]} for a in spec.admissions)
    offers = tuple(
        OfferSpec(**{**o.__dict__, "option_id": "OPT" + o.option_id,
                     "lending_unit": ("LND-" + o.lending_unit) if o.lending_unit else None})
        for o in spec.offers
    )
    m.update({o.option_id: "OPT" + o.option_id for o in spec.offers})
    return replace(spec, stays=stays, beds=bed_rows, admissions=adms, offers=offers), m


def _plan_signature(plan, mapping=None):
    mapping = mapping or {}
    return tuple(sorted((a.type, mapping.get(a.target, a.target), a.window_start.isoformat()) for a in plan.actions))


def test_f2_renaming_invariance_and_same_choice(episodes, profile):
    for ep in episodes[:4]:
        spec2, mapping = _rename_all(ep.spec)
        ep2 = realise_episode(spec2, profile)
        f1 = F.SnapshotFeatures(ep.snapshot, ep.sidecar, profile)
        f2 = F.SnapshotFeatures(ep2.snapshot, ep2.sidecar, profile)
        rows1 = {_plan_signature(p, mapping): f1.row(p, "M_ent")[1] for p in ep.plans}
        rows2 = {_plan_signature(p): f2.row(p, "M_ent")[1] for p in ep2.plans}
        assert rows1 == rows2
        score = lambda v: sum((i % 7 + 1) * x for i, x in enumerate(v))  # noqa: E731 fixed stand-in model
        assert min(rows1, key=lambda k: (score(rows1[k]), k)) == min(rows2, key=lambda k: (score(rows2[k]), k))


def test_f3_input_permutation_invariance(episodes, profile):
    ep = episodes[1]
    snap = ep.snapshot
    shuffled = snap.model_copy(
        update={
            "stays": tuple(reversed(snap.stays)),
            "beds": tuple(reversed(snap.beds)),
            "admissions": tuple(reversed(snap.admissions)),
            "reinforcements": tuple(reversed(snap.reinforcements)),
            "shifts": tuple(reversed(snap.shifts)),
            "teams": tuple(reversed(snap.teams)),
        }
    )
    f1, f2 = F.SnapshotFeatures(snap, ep.sidecar, profile), F.SnapshotFeatures(shuffled, ep.sidecar, profile)
    for p in ep.plans:
        assert f1.row(p, "M_ent") == f2.row(p, "M_ent")


def test_f4_distinguishability_ment_not_magg(episodes, profile):
    found = 0
    for ep in episodes:
        f = F.SnapshotFeatures(ep.snapshot, ep.sidecar, profile)
        singles = [p for p in ep.plans if len(p.actions) == 1 and p.actions[0].type == "coordinate_discharge"]
        for i, p in enumerate(singles):
            for q in singles[i + 1 :]:
                if p.actions[0].window_start != q.actions[0].window_start:
                    continue
                if f.stay_public[p.actions[0].target] == f.stay_public[q.actions[0].target]:
                    continue
                assert f.row(p, "M_agg") == f.row(q, "M_agg")
                assert f.row(p, "M_ent")[1] != f.row(q, "M_ent")[1]
                found += 1
    assert found >= 1


def test_f6_schema_static_and_stable(episodes, profile):
    ep = episodes[0]
    f = F.SnapshotFeatures(ep.snapshot, ep.sidecar, profile)
    for fam in ("M_agg", "M_ent"):
        names, vals = f.row(ep.plans[-1], fam)
        assert names == F.static_names(fam) and len(vals) == len(names)
    assert F.schema_fingerprint() == F.schema_fingerprint()


def test_out_of_vocabulary_obstacle_stops(episodes, profile):
    ep = episodes[0]
    stay = ep.snapshot.stays[0]
    bad = ep.snapshot.model_copy(update={"stays": (stay.model_copy(update={"obstacles": ("inconnu",)}), *ep.snapshot.stays[1:])})
    with pytest.raises(F.FeatureError):
        F.SnapshotFeatures(bad, ep.sidecar, profile)


# ---------------------------------------------------------------- analysis


def test_clopper_pearson_reference_table():
    ref = {8: (0.3123, 0.4707, 0.5997), 29: (0.0981, 0.1534, 0.2016), 30: (0.0950, 0.1486, 0.1953), 40: (0.0722, 0.1132, 0.1492)}
    for n, values in ref.items():
        for x, v in enumerate(values):
            assert round(clopper_pearson_upper(x, n), 4) == v
    hb = harm_bound([False] * 30)
    assert hb["harmed_structures"] == 0 and 0.09 < hb["upper_one_sided"] < 0.1


def test_capture_no_clipping_and_undefined_headroom():
    s = [[{"gain": -5.0, "headroom": 20.0}], [{"gain": 10.0, "headroom": 30.0}]]
    c = capture(s)
    assert c["defined"] and abs(c["capture"] - 2.5 / 25.0) < 1e-12 and not c["clipped"]
    neg = capture([[{"gain": -30.0, "headroom": 20.0}]])
    assert neg["capture"] < 0
    low = capture([[{"gain": 3.0, "headroom": 10.0}]])
    assert low["capture"] is None and not low["defined"]


def test_structure_weighting_and_bootstrap():
    s = [[{"v": 0.0}, {"v": 0.0}, {"v": 0.0}], [{"v": 10.0}]]
    assert structure_weighted_mean(s, "v") == 5.0
    stat = lambda d: structure_weighted_mean(d, "v")  # noqa: E731
    a = hierarchical_bootstrap(s, stat, 200, 7)
    assert (a == hierarchical_bootstrap(s, stat, 200, 7)).all()
    lo, hi = percentile_interval(a)
    assert lo == 0.0 and hi == 10.0  # structure-level resampling, parents carried together


def test_theta_term_unsigned_and_unbiased_example():
    assert theta_term([3.0, 3.0, 3.0]) == 9.0
    assert theta_term([-3.0, -3.0, -3.0]) == 9.0
    assert abs(theta_term([1.0, 2.0, 3.0]) - (4.0 - 1.0 / 3)) < 1e-12


def test_verdicts():
    assert verdict(-1, 10, 15, True, True) == "insufficient"
    assert verdict(16, 40, 15, True, True) == "demonstrated_in_this_synthetic_protocol"
    assert verdict(16, 40, 15, False, True) == "inconclusive"
    assert verdict(5, 40, 15, True, False) == "exploratory"


def test_stay_spec_has_no_private_field():
    names = set(StaySpec.__dataclass_fields__)
    assert not names & {"ready_h", "dis_h", "realised", "truth"}


def test_t_p5_r1_detects_an_adapter_that_ignores_presence(episodes, profile, monkeypatch):
    """Mutation check: if the adapter kept absent offers, coverage would never change."""
    import hospitalos.p5.eval_adapter as A

    original = A.evaluation_decisions

    def ignoring(snapshot, plan, presence):
        return original(snapshot, plan, {k: 1 for k in presence})

    monkeypatch.setattr(A, "evaluation_decisions", ignoring)
    diffs = 0
    for ep in episodes:
        found = _requested_selected(ep)
        if found is None:
            continue
        plan, option = found
        real = T.realise(ep, "R1", 1, COMMIT)
        key = offer_key(option)
        present = A.outcome(ep.snapshot, plan, replace(real, presence={**real.presence, key: 1}), profile)
        absent = A.outcome(ep.snapshot, plan, replace(real, presence={**real.presence, key: 0}), profile)
        diffs += absent.U != present.U
    assert diffs == 0  # the mutated adapter is blind: T-P5-R1 (strict >= 1) would fail on it


def test_v6_engine_untouched():
    import subprocess

    r = subprocess.run(
        ["git", "diff", "--quiet", "856a57c65fb0d55190addf6c39a45c57913eac07", "--",
         "src/hospitalos/decision_support", "configs/decision_support"]
    )
    assert r.returncode == 0
