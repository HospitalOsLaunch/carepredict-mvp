"""B-FRAG validity tests T-B1..T-B10 (PROTOCOLE_BFRAG s.11). Synthetic only; run before any comparison."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from hospitalos.bfrag import core as K
from hospitalos.howm import generator as G
from hospitalos.howm.generator import refresh_private
from hospitalos.howm.world import TPH, candidates

ROOT = Path(__file__).resolve().parents[2]
D2 = json.loads((ROOT / "docs/howm2/bfrag/DESIGN_D2.json").read_text())


def _anchor(inst):
    return G.true_regime_at(inst.ep, K.T0)


@pytest.fixture(scope="module")
def inst_sf3():
    return K.build_instant(K.make_world("BFRAG_DEV", 2, D2))  # idx 2 -> SF3 (planned drop)


def test_tb1_same_instant_zero_lag():
    w = K.make_world("BFRAG_DEV", 0, D2)
    w = replace(w, spec=replace(w.spec, theta={**w.spec.theta, "lag_min": 0.0}))
    inst = K.build_instant(w)
    pe, te = inst.peng, inst.true_eng
    assert pe.tick == te.tick == K.T0
    assert {b: x.state for b, x in pe.beds.items()} == {b: x.state for b, x in te.beds.items()}
    assert {b: x.stay for b, x in pe.beds.items()} == {b: x.stay for b, x in te.beds.items()}
    assert {u: [r.rid for r in q] for u, q in pe.queue.items() if q} == {u: [r.rid for r in q] for u, q in te.queue.items() if q}
    live_t = {s.sid: (s.authorised, s.ready, s.tr_req is not None) for s in te.stays.values() if s.departed is None}
    live_p = {s.sid: (s.authorised, s.ready, s.tr_req is not None) for s in pe.stays.values() if s.departed is None}
    assert live_t == live_p


def test_tb2_no_publication_at_or_after_t0(inst_sf3):
    cut = 15 * K.T0
    assert max(o[1] for o in inst_sf3.public_obs) < cut
    assert inst_sf3.true_eng.tick == K.T0
    assert not any(o[0] >= cut for o in inst_sf3.public_obs)


def test_tb2b_public_methods_do_not_depend_on_world_identity(inst_sf3):
    from hospitalos.howm.b0 import B0Params

    p = B0Params.from_json(json.loads((ROOT / "evidence/howm1/B0_PARAMS.json").read_text()))
    w2 = replace(inst_sf3.world, part="X", idx=999, family="?", spec=replace(inst_sf3.world.spec, ekey=12345, partition="X", index=999))
    inst2 = replace(inst_sf3, world=w2)
    assert K.public_key(inst_sf3) == K.public_key(inst2)
    a = K.plan_and_scores(K.f_samples(inst_sf3, 2), inst_sf3.world.drop)
    b = K.plan_and_scores(K.f_samples(inst2, 2), inst2.world.drop)
    assert a == b
    a = K.plan_and_scores([(inst_sf3.peng, pr) for pr in K.r1_providers(inst_sf3, p, 2)], inst_sf3.world.drop)
    b = K.plan_and_scores([(inst2.peng, pr) for pr in K.r1_providers(inst2, p, 2)], inst2.world.drop)
    assert a == b


def _stepper(inst, plan=None, r=1):
    eng = inst.true_eng.clone()
    eng.emit_log = False
    prov = K.WithCalendar(K.bf_provider(inst.world.spec, r, inst.world.nominal, regime_anchor=_anchor(inst)), inst.world.drop)
    refresh_private(eng, prov)
    if plan is not None:
        eng.apply_plan(plan, prov)
    return eng, prov


def test_tb3_continuity_and_request_conservation(inst_sf3):
    eng, prov = _stepper(inst_sf3)
    q0 = {r.rid for q in eng.queue.values() for r in q}
    s0 = set(eng.stays)
    arrivals = 0
    for _ in range(K.HORIZON_H * TPH):
        if eng.tick % TPH == 0:
            arrivals += sum(len(prov.arrivals(eng, un, eng.tick // TPH)) for un in sorted(eng.units))
        eng.step(prov)
    assert eng.tick == K.T0 + K.HORIZON_H * TPH
    assert s0 <= set(eng.stays)  # identities persist (departed stays are kept, not reset)
    new_placed = len(set(eng.stays) - s0)
    q_end = {r.rid for q in eng.queue.values() for r in q}
    assert new_placed + len(q_end) == len(q0) + arrivals


def test_tb4_bed_conservation_hourly(inst_sf3):
    eng, prov = _stepper(inst_sf3, candidates()[5])
    n = len(eng.beds)
    for _ in range(K.HORIZON_H * TPH):
        eng.step(prov)
        if eng.tick % TPH == 0:
            states = [b.state for b in eng.beds.values()]
            assert len(states) == n and all(s in ("occ", "free", "dirty", "cleaning") for s in states)
            for b in eng.beds.values():
                if b.state == "occ":
                    assert b.stay in eng.stays and eng.stays[b.stay].departed is None


def test_tb5_stable_rng_paired_controls():
    for idx in (0, 1, 2):
        wb = K.make_world("BFRAG_DEV", idx, D2)
        wr = K.make_world("BFRAG_DEV", idx, D2, variant="relaxed")
        assert wb.spec.ekey == wr.spec.ekey and wb.spec.beds == wr.spec.beds and wb.spec.theta == wr.spec.theta
        eb, er = K.build_instant(wb).ep, K.build_instant(wr).ep
        arr_b = [(o[0], o[3]) for o in eb.observations if o[2] == "request_arrival"]
        arr_r = [(o[0], o[3]) for o in er.observations if o[2] == "request_arrival"]
        assert arr_b == arr_r
        init_b = [(o[3], o[5].get("bed")) for o in eb.observations if o[2] == "placed" and o[0] == 0]
        init_r = [(o[3], o[5].get("bed")) for o in er.observations if o[2] == "placed" and o[0] == 0]
        assert init_b == init_r


def test_tb6_planned_drop_respected(inst_sf3):
    assert inst_sf3.world.drop
    eng, prov = _stepper(inst_sf3)
    for _ in range(K.HORIZON_H * TPH):
        t = eng.tick
        eng.step(prov)
        started = [b for b in eng.beds.values() if b.state == "cleaning" and b.clean_start == t]
        if started:
            busy = sum(1 for b in eng.beds.values() if b.state == "cleaning")
            assert busy <= eng.c_cl - K.drop_at(inst_sf3.world.drop, t)


def test_tb7_rupture_detector():
    k = K.K_MIN
    assert K.episodes([0] * 10) == []
    assert K.episodes([k] * 3 + [0] * 20) == []  # shorter than 1 h
    assert K.episodes([0, k, k, k, k, 0]) == [(1, 5, 4 * k)]
    s = [k] * 4 + [0] * 5 + [k] * 4  # gap 5 < 8 ticks -> merged
    assert K.episodes(s) == [(0, 13, 8 * k)]
    s = [k] * 4 + [0] * 9 + [k] * 4  # gap 9 >= 8 -> two episodes
    assert len(K.episodes(s)) == 2
    assert K.episodes([k - 1] * 50) == []


def test_tb8_derived_generator_equals_frozen_without_buffer():
    spec = G.establishment("BFRAG_DEV", 3) if "BFRAG_DEV" in G.PARTITION_SIZES else None
    K.register()
    spec = G.establishment("BFRAG_DEV", 3)
    K.NOMINAL[spec.ekey] = dict(spec.beds)
    gen = K._derive_generate()
    a, b = gen(spec), G.generate(spec)
    assert a.observations == b.observations


def test_tb9_frozen_files_unchanged():
    from hospitalos.howm import corpus as C
    from hospitalos.howm import g0check

    g0check.check()
    assert json.loads((ROOT / "evidence/howm1/F1.json").read_text())["code"] == C.code_hashes()
    f_c1 = hashlib.sha256((ROOT / "evidence/howm2_c1/F_C1.json").read_bytes()).hexdigest()
    assert f_c1 == json.loads((ROOT / "evidence/howm2_c1/RESULTS_C1_P1.json").read_text())["f_c1_sha256"]


def test_tb10_plan_applied_once_no_background_plan(inst_sf3):
    plan = next(c for c in candidates() if c.reinforcement == "pool_IDE_A" and not c.coordinate and c.cleaning == "fifo")
    for p, n_expected in ((plan, 1), (candidates()[0], 0)):
        eng, prov = _stepper(inst_sf3, p)
        for _ in range(K.HORIZON_H * TPH):
            eng.step(prov)
        assert sum(1 for o in eng.offers.values() if o.req >= K.T0) == n_expected
