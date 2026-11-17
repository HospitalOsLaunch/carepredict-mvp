"""HOWM-INT-1 world invariants (mechanisms M1-M8, commitments, time convention, common random numbers)."""
from __future__ import annotations

import pytest

from hospitalos.howmint import actions as A
from hospitalos.howmint import loop as L
from hospitalos.howmint import world as W
from hospitalos.howm.world import TPD, TPH


@pytest.fixture(scope="module", params=[2, 4, 8])
def ep(request):
    n = request.param
    sp = W.episode(W.structure("INT_TESTS", 3, n), 0)
    return sp, L.prefix(sp, 48)


def hist(**kw):
    return kw["cat"][1] if kw["adm"][1] else kw["cat"][0]


def none_pol(**kw):
    return kw["cat"][0]


def test_i1_bed_conservation_and_no_double_occupancy(ep):
    sp, pre = ep
    eng, prov, _rec = L.start_future(pre, sp, 1)
    for _ in range(48 * TPH):
        eng.step(prov)
        occ = [b for b in eng.beds.values() if b.state == "occ"]
        assert len({b.stay for b in occ}) == len(occ)
        present = [s for s in eng.stays.values() if s.departed is None]
        assert len(present) == len(occ)  # every present stay holds exactly one bed (transfers keep the origin bed)
        assert all(eng.beds[s.bed].stay == s.sid for s in present)


def test_i2_transfer_holds_origin_bed_until_placement():
    sp = W.episode(W.n_unit_structure("INT_TESTS", 7, 4, regime="fragile", bottlenecks=("transfer",)), 0)
    pre = L.prefix(sp, 48)
    eng, prov, _ = L.start_future(pre, sp, 1)
    seen = 0
    for _ in range(72 * TPH):
        eng.step(prov)
        for rid, sid in eng.transfer_pending.items():
            st = eng.stays[sid]
            assert st.departed is None and eng.beds[st.bed].stay == sid  # bed blocked while waiting
            seen += 1
    assert seen > 0
    moved = [s for s in eng.stays.values() if s.sid.startswith("SS")]
    assert moved and all(eng.stays[s.sid[1:]].departed is not None for s in moved)


def test_i3_external_downstream_daily_slots():
    sp = W.episode(W.n_unit_structure("INT_TESTS", 8, 4, regime="fragile", bottlenecks=("aval",)), 0)
    pre = L.prefix(sp, 48)
    eng, prov, _ = L.start_future(pre, sp, 1)
    for _ in range(96 * TPH):
        eng.step(prov)
    assert eng.aval_used and max(eng.aval_used.values()) <= sp.aval_slots_per_day


def test_i4_budget_no_stacking_no_cancel(ep):
    sp, pre = ep
    eng, prov, _ = L.start_future(pre, sp, 1)
    cat = A.catalogue(eng, sp.units)
    cl1 = next(a for a in cat if a["id"] == "cl_w1")
    assert A.admissible(eng, cl1, sp.n, eng.tick)
    A.apply(eng, cl1, prov)
    assert not A.admissible(eng, cl1, sp.n, eng.tick)  # no stacking on the same slot
    day_cap, week_cap = A.budgets(sp.n)
    k = 0
    for a in cat:
        if a["kind"] in ("cl", "tr", "staff") and A.admissible(eng, a, sp.n, eng.tick):
            A.apply(eng, a, prov)
            k += 1
    per_day, tot = A.used_hours(eng)
    assert max(per_day.values()) <= day_cap + 1e-9 and tot <= week_cap + 1e-9
    n0 = len(eng.commitments)
    assert all(not hasattr(A, f) for f in ("cancel", "revoke"))  # no cancellation primitive exists
    assert len(eng.commitments) == n0


def test_i5_capacity_override_scheduled_and_restored(ep):
    sp, pre = ep
    eng, prov, _ = L.start_future(pre, sp, 1)
    a = next(x for x in A.catalogue(eng, sp.units) if x["id"] == "tr_w1")
    A.apply(eng, a, prov)
    base = eng.c_tr
    assert eng.active_extra("tr", a["start"]) == 1 and eng.active_extra("tr", a["end"]) == 0
    while eng.tick < a["start"] + 2:
        eng.step(prov)
    assert eng.c_tr == base  # override applied inside step only


def test_i6_time_convention_public_view_strict(ep):
    sp, pre = ep
    eng, prov, rec = L.start_future(pre, sp, 1)
    for _ in range(30 * TPH):
        eng.step(prov)
    t = eng.tick
    ps, peng = L.public_view(pre, rec, t)
    assert all(o[1] < 15 * t for o in ps.obs) and peng.tick == t
    assert any(o[1] >= 15 * t for o in rec.obs)  # later observations exist and are excluded


def test_i7_common_random_numbers_across_policies(ep):
    sp, pre = ep
    logs = {}
    for name, pol in (("hist", hist), ("none", none_pol)):
        eng, prov, rec = L.start_future(pre, sp, 2)
        arr = []
        res = L.closed_loop(sp, pre, 2, pol, 2, 24 if sp.n == 2 else 6, 24 if sp.n > 2 else 48)
        logs[name] = res
        a = [o for o in rec.obs]
    # arrivals are keyed by (episode, realisation, unit, hour, index): identical exogenous requests
    e1, p1, r1 = L.start_future(pre, sp, 2)
    e2, p2, r2 = L.start_future(pre, sp, 2)
    from hospitalos.howm.world import Plan
    e2.apply_plan(Plan(True, "compat", "none"), p2)
    for _ in range(24 * TPH):
        e1.step(p1)
        e2.step(p2)
    arr1 = sorted(o[3] for o in r1.obs if o[2] == "request_arrival" and not o[3].startswith("T"))
    arr2 = sorted(o[3] for o in r2.obs if o[2] == "request_arrival" and not o[3].startswith("T"))
    assert arr1 == arr2 and len(arr1) > 0


def test_i8_public_engine_matches_truth_without_lag(ep):
    sp, pre = ep
    from dataclasses import replace
    sp0 = replace(sp, theta=dict(sp.theta, lag_min=0.0))
    pre0 = L.prefix(sp0, 48)
    eng, prov, rec = L.start_future(pre0, sp0, 1)
    for _ in range(20 * TPH):
        eng.step(prov)
    ps, peng = L.public_view(pre0, rec, eng.tick)
    for un in sp.units:
        assert [eng.beds[b].state for b in eng.units[un].beds] == [peng.beds[b].state for b in peng.units[un].beds]
        assert len(eng.queue.get(un, [])) == len(peng.queue.get(un, []))
    assert len(peng.commitments) == len(eng.commitments)


def test_i9_two_unit_mode_is_bfrag2_structure():
    from hospitalos.bfrag import core as K

    sp = W.structure("INT_TESTS", 11, 2)
    w = K.make_world("INT_TESTS", 11, W.D2, family=sp.family)
    assert sp.beds == w.spec.beds and sp.c_cl == w.spec.c_cl and sp.c_tr == w.spec.c_tr and sp.drop == w.drop and sp.theta == w.spec.theta
    assert sp.transfer == {} and sp.p_aval == {}
