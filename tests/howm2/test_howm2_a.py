"""HOWM-2 tranche A tests (synthetic only, no training)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from hospitalos.howm import generator as G
from hospitalos.howm import heads
from hospitalos.howm.dataset import build
from hospitalos.howm.keys import key
from hospitalos.howm2 import data as D
from hospitalos.howm2 import laws as Lw
from hospitalos.howm2 import space
from hospitalos.howm2.filter import Ladder, PublicState, truth_info

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def val_ep():
    return G.generate(G.establishment("VAL", 2))


def test_light_origins_equal_dataset_build(val_ep):
    hs = [24, 60, 99, 143]
    est = build(val_ep, hs)
    for H, od, _ps in D.origins(val_ep, hs):
        ref = est.origins[H]
        assert od.items == ref.items
        assert np.array_equal(od.arrivals, ref.arrivals)
        assert od.care_ref == ref.care_ref
        assert np.array_equal(od.care, ref.care) and np.array_equal(od.care_mask, ref.care_mask)
        assert np.array_equal(od.care_x, ref.care_x)
        assert json.dumps(od.window, default=str, sort_keys=True) == json.dumps(ref.window, default=str, sort_keys=True)


def test_key_space_disjoint_and_registration_runtime_only():
    before = (ROOT / "src/hospitalos/howm/generator.py").read_bytes()
    space.register()
    assert not space.g0_keys() & space.new_keys()
    assert len(space.new_keys()) == 300
    assert (ROOT / "src/hospitalos/howm/generator.py").read_bytes() == before
    spec = G.establishment("HOWM2_REF", 5)
    assert spec.population == "REF" and spec.ekey == key("HOWM1", "HOWM2_REF", 5)
    with pytest.raises(G.SealedPartitionError):
        G.establishment("RESERVE_REF", 0)


def test_laws_normalised():
    p, tail = Lw.k_pmf(np.array([30.0, 60.0, 400.0]), 0.4)
    assert np.allclose(p.sum(1) + tail, 1.0)
    q = Lw.lag_q(np.array([0.0, 30.0]))
    pl, tl = Lw.add_lag(p[1], float(tail[1]), q, np.array([0.5, 0.5]))
    assert abs(pl.sum() + tl - 1.0) < 1e-12
    for a in (0, 30, 80):
        M = Lw.snap_matrix(a, "ready")
        assert np.allclose(M.sum(1), 1.0)
    cb = Lw.care_bin_probs(np.array([5.0, 20.0, 300.0]))
    assert np.allclose(cb.sum(1), 1.0)


def test_chain_prior_matches_generator_chain():
    spec = G.establishment("TRAIN", 3)
    spec = type(spec)(**{**spec.__dict__, "mech": {**spec.mech, "m2": True, "m2_common": False}})
    hits = np.zeros(60)
    n = 3000
    for r in range(n):
        prov = G.TruthProvider(spec, 1000 + r)
        hits += [prov.regime("transport", h) for h in range(60)]
    assert np.max(np.abs(hits / n - Lw.chain_prior(60))) < 0.03


def test_service_law_matches_generator_draws():
    spec = G.establishment("TRAIN", 4)
    spec = type(spec)(**{**spec.__dict__, "mech": {**spec.mech, "m2": False}})
    prov = G.TruthProvider(spec, 7)

    class E:
        tick = 0

    from hospitalos.howm.world import Stay
    ks = []
    for i in range(20000):
        st = Stay(f"s{i}", "A", "b", 1, False, True, 0)
        st.tr_start = 0
        ks.append(prov.transport_end(E(), st))
    emp = np.bincount(ks, minlength=Lw.KM)[: Lw.KM] / len(ks)
    p, _ = Lw.k_pmf(np.array([spec.theta["tr_min"]]), 0.4)
    assert np.max(np.abs(emp - p[0])) < 0.01


def test_hazard_score_equals_r1_protocol():
    rng = np.random.default_rng(0)
    logits = rng.normal(-2.5, 1, heads.NB)
    h = 1 / (1 + np.exp(-logits))
    S = np.concatenate([[1.0], np.cumprod(1 - h)])
    p = h * S[:-1]
    tail = S[-1]
    for e, b, ev in ((0, 5, True), (3, 10, False), (2, 192, False), (4, 4, True)):
        r1 = heads.hazard_logprob(logits[None, :], np.array([e]), np.array([b]), np.array([ev]))[0]
        assert abs(Lw.hazard_score(p, tail, e, b, ev) - r1) < 1e-9


def test_public_state_reads_public_only(val_ep):
    pub = PublicState("REF", dict(val_ep.spec.beds))
    pub.ingest([o for o in val_ep.observations if o[1] <= 3000])
    assert all(a >= 0 for _, a in pub.lags)
    lad = Ladder("REF", next(o[5] for o in val_ep.observations if o[2] == "static"), dict(val_ep.spec.beds), None)
    w = lad.lag_post(pub, 3000)
    assert abs(w.sum() - 1) < 1e-9
    assert truth_info(val_ep)["theta"] == val_ep.spec.theta


def test_g0_and_f1_frozen_code_unchanged():
    from hospitalos.howm import corpus as C
    from hospitalos.howm import g0check

    g0check.check()
    f1 = json.loads((ROOT / "evidence/howm1/F1.json").read_text())
    assert f1["code"] == C.code_hashes()
