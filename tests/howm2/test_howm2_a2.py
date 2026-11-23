"""HOWM-2 A' tests (addendum A2-1): N-c identity and nowcast unit checks (synthetic only)."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import nbinom

from hospitalos.howm import generator as G
from hospitalos.howm.rollout import rollout
from hospitalos.howm.world import candidates
from hospitalos.howm2 import a2, nowcast as N, space

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def zero_lag_instants():
    spec = G.establishment("VAL", 0)
    spec = replace(spec, theta={**spec.theta, "lag_min": 0.0})
    ep = G.generate(spec, keep_instants=True)
    assert all(o[1] == o[0] for o in ep.observations)
    return a2.setup("VAL", 0, ep=ep)


def _planner_u(ins, eng_of, m_draws=8):
    from howm2_decision import sample_world

    rng = np.random.default_rng(int(G.u(ins.spec.ekey, 0, "howm2-dec", ins.tau) * 2**31))
    us = []
    for m in range(m_draws):
        if eng_of == "L4":
            th, mech, anchor = sample_world(ins.lad, ins.ctx, rng)
            eng = ins.peng
            s2 = replace(ins.spec, theta=th, mech=mech)
        else:
            th, mech, anchor, s2, _prov, eng, applied = a2.l4n_draw(ins, rng, 201 + m)
            assert eng is ins.peng and applied == []
        prov = G.TruthProvider(s2, 201 + m, theta=th, regime_anchor=anchor)
        us.append([rollout(eng, prov, p)["U"] for p in candidates()])
    return np.array(us).mean(0)


def test_nc_identity_zero_lag_world(zero_lag_instants):
    for ins in zero_lag_instants:
        assert a2.truth_state(ins)["totals"] == dict.fromkeys(a2.TYPES, 0)
        u4 = _planner_u(ins, "L4")
        un = _planner_u(ins, "L4N")
        assert u4.tobytes() == un.tobytes()


def test_window_and_survival():
    assert N.window_ticks(0.0) == 0
    assert N.window_ticks(0.49) == 0  # lowest L4 lag node: no pending possible
    for th in (5.0, 30.0, 60.0):
        k = N.window_ticks(th)
        assert N.pending_survival(th, k) >= N.CUTOFF > N.pending_survival(th, k + 1)
    assert N.window_ticks(60.0) <= a2.ARR_WINDOW_H * 4


def test_nb_thinning_posterior_matches_simulation():
    rng = np.random.default_rng(0)
    r, mu, q = 3.0, 2.5, 0.3
    lam = rng.gamma(r, mu / r, 400000)
    pub = rng.poisson(lam * (1 - q))
    unp = rng.poisson(lam * q)
    beta = r / mu
    for n in (0, 2, 5):
        sel = unp[pub == n]
        p = (beta + 1 - q) / (beta + 1)
        assert abs(sel.mean() - nbinom.mean(r + n, p)) < 0.02
        assert abs((sel == 0).mean() - nbinom.pmf(0, r + n, p)) < 0.01


def test_nowcast_engine_does_not_mutate_public_and_respects_preconditions():
    space.register()
    ins = a2.setup("HOWM2_REF", 3)[1]
    before = json.dumps(
        {
            "stays": sorted((s.sid, s.authorised, s.ready, s.tr_accepted) for s in ins.peng.stays.values()),
            "beds": sorted((b.bed_id, b.state) for b in ins.peng.beds.values()),
            "q": sorted((u, len(q)) for u, q in ins.peng.queue.items()),
        }
    )
    rng = np.random.default_rng(5)
    n_applied = 0
    for m in range(16):
        *_x, prov, eng, applied = a2.l4n_draw(ins, rng, 1001 + m)
        n_applied += len(applied)
        assert eng.tick == ins.tau
        assert eng.rejected == ins.peng.rejected
        assert all(e < ins.tau for typ, _r, e in applied if typ != "arrival")
        for typ, ref, _e in applied:
            if typ == "transport":
                assert ref not in eng.tr_service and eng.stays[ref].departed is not None
            if typ == "cleaning":
                assert eng.beds[ref].state == "free"
    after = json.dumps(
        {
            "stays": sorted((s.sid, s.authorised, s.ready, s.tr_accepted) for s in ins.peng.stays.values()),
            "beds": sorted((b.bed_id, b.state) for b in ins.peng.beds.values()),
            "q": sorted((u, len(q)) for u, q in ins.peng.queue.items()),
        }
    )
    assert before == after


def test_l5n_uses_true_lag_and_regimes():
    space.register()
    ins = a2.setup("HOWM2_REF", 3)[2]
    prov, _eng, _ap = a2.l5n_draw(ins, 7)
    assert prov.lag == ins.spec.theta["lag_min"]
    assert prov.K == N.window_ticks(ins.spec.theta["lag_min"])
    if ins.spec.mech["m2"]:
        assert all(prov._reg[("transport", h)] == ins.ep.regimes["transport"][h] for h in range(5))


def test_frozen_code_unchanged():
    from hospitalos.howm import corpus as C
    from hospitalos.howm import g0check

    g0check.check()
    f1 = json.loads((ROOT / "evidence/howm1/F1.json").read_text())
    assert f1["code"] == C.code_hashes()
    assert math.isfinite(N.pending_survival(60.0, 1))
