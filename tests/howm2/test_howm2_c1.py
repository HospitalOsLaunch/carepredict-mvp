"""HOWM-2 C1 palier 1 tests (TEST_MATRIX_C1_AMENDE + proposition_BCD T-C01..T-C16 applicable)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
import torch

from hospitalos.howm import generator as G
from hospitalos.howm import nets
from hospitalos.howm.history import PublicStream
from hospitalos.howm.keys import key
from hospitalos.howm2 import c1, space

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def recs():
    c1.register()
    p = c1.b0()
    return [c1.make_record("HOWM2_CTRAIN", i, p) for i in (0, 1)]


def test_tc01_key_spaces_disjoint_and_generator_unchanged():
    before = (ROOT / "src/hospitalos/howm/generator.py").read_bytes()
    c1.register()
    ks = c1.c1_keys()
    allc = set().union(*ks.values())
    assert sum(len(v) for v in ks.values()) == len(allc) == 10000 + 48 + 200
    assert not allc & space.g0_keys()
    assert not allc & space.new_keys()
    assert (ROOT / "src/hospitalos/howm/generator.py").read_bytes() == before
    assert G.establishment("HOWM2_CEVAL", 3).ekey == key("HOWM1", "HOWM2_CEVAL", 3)


def test_tc02_reserve_sealed():
    c1.register()
    with pytest.raises(G.SealedPartitionError):
        G.establishment("RESERVE_REF", 0)


def test_tc03_shard_order_is_a_permutation_and_consumed_check():
    o = c1.shard_order(1, 0, 4800)
    assert sorted(o.tolist()) == list(range(4800))
    assert not np.array_equal(o, c1.shard_order(2, 0, 4800))
    st = {"step": 160, "consumed": [[*divmod(s * 32, 4800)] for s in range(160)]}
    r = c1.consumed_check(st, 100)
    assert r["exact_no_replay"] and r["planned"] == 150 or r["steps"] == 160
    st["consumed"][5] = st["consumed"][4]
    assert not c1.consumed_check(st, 100)["exact_no_replay"]


def test_tc04_origins(recs):
    assert c1.ORIGINS == list(range(24, 166, 3))
    assert sorted(recs[0]["data"].origins) == c1.ORIGINS
    assert sorted(recs[0]["l2d"]) == c1.ORIGINS


def test_tc05_long_context_no_future_leak(recs):
    r = recs[0]
    H = 60
    b1 = c1.graph_batch_window([(r["data"], H)], cap=None)
    est = r["data"]
    saved = {t: est.nodes[t][H:].copy() for t in est.nodes}
    savedp = {t: est.present[t][H:].copy() for t in est.present}
    try:
        for t in est.nodes:
            est.nodes[t][H:] = 7.0
            est.present[t][H:] = True
        b2 = c1.graph_batch_window([(est, H)], cap=None)
    finally:
        for t in est.nodes:
            est.nodes[t][H:] = saved[t]
            est.present[t][H:] = savedp[t]
    assert b1["n"] == b2["n"] and len(b1["feats"]) == len(b2["feats"]) == H
    for k in range(H):
        for t in b1["feats"][k]:
            assert torch.equal(b1["feats"][k][t], b2["feats"][k][t])
        assert torch.equal(b1["present"][k], b2["present"][k])


def test_tc05b_long_batch_equals_single_origin_batches(recs):
    """Multi-origin long batches (> 8 origins, mixed H) encode each origin as its own batch does."""
    p = c1.b0()
    m = c1.new_model("C.2a", p, 2)
    pairs = [(recs[i % 2], H) for i, H in enumerate((30, 99, 24, 165, 51, 72, 120, 27, 33, 141))]
    with torch.no_grad():
        zb, _ = m.encode(c1.make_batch("C.2a", pairs))
        zs = torch.cat([m.encode(c1.make_batch("C.2a", [pr]))[0] for pr in pairs])
    assert torch.allclose(zb, zs, atol=1e-5)


def test_tc06_c2a_capped_to_24h_reproduces_h1(recs):
    p = c1.b0()
    m1 = c1.new_model("C.1", p, 0)
    m2 = c1.new_model("C.2a", p, 0)
    assert all(torch.equal(a, b) for a, b in zip(m1.state_dict().values(), m2.state_dict().values()))
    pairs = [(recs[i % 2], H) for i, H in enumerate((30, 99, 24, 165, 51, 72, 120, 27, 33, 141, 90))]
    b_ref = nets.make_batch([(r["data"], H) for r, H in pairs], "H1")
    c1.H1Long.cap = 24
    try:
        b_long = c1.make_batch("C.2a", pairs)
    finally:
        c1.H1Long.cap = None
    with torch.no_grad():
        z1, _ = m1.encode(b_ref)
        z2, _ = m2.encode(b_long)
        l1 = nets.forward_losses(m1, b_ref)
        l2 = nets.forward_losses(m2, b_long)
    assert torch.allclose(z1, z2, atol=1e-6)
    assert all(abs(float(l1[f][0]) - float(l2[f][0])) < 1e-4 for f in l1)


def test_tc17_c2b_at_init_reproduces_h1(recs):
    p = c1.b0()
    m1 = c1.new_model("C.1", p, 1)
    m3 = c1.new_model("C.2b", p, 1)
    pairs = [(recs[0], 45), (recs[1], 120)]
    b1 = nets.make_batch([(r["data"], H) for r, H in pairs], "H1")
    b3 = c1.make_batch("C.2b", pairs)
    assert b3["l2d"].shape == (2, 8) and torch.any(b3["l2d"] != 0)
    with torch.no_grad():
        assert torch.allclose(m1.encode(b1)[0], m3.encode(b3)[0], atol=1e-6)


def test_tc18_l2_inputs_equal_l2_predict(recs):
    from hospitalos.howm2.ladder import l2_predict

    p = c1.b0()
    r = recs[1]
    ep = G.generate(G.establishment("HOWM2_CTRAIN", 1))
    ps = PublicStream(ep.observations)
    for H in (24, 87, 165):
        ps.advance(H * 60)
        pr = l2_predict(p, r["data"].origins[H], r["data"], ps)
        d = pr.meta["deltas"]
        for i, f in enumerate(c1.L2D_ORDER):
            if f != "arrivals":
                assert abs(r["l2d"][H][i] - d[f]) < 1e-12
        un = "A"
        d_arr = math.log(pr.arr_mu[0, 0]) - (p.arr_a + math.log(r["data"].n_beds[un]) + p.arr_tod[H % 24])
        assert abs(r["l2d"][H][5] - d_arr) < 1e-9


def test_resume_is_exact_and_one_pass(recs, tmp_path, monkeypatch):
    monkeypatch.setattr(c1, "EV", tmp_path / "ev")
    monkeypatch.setattr(c1, "DATA", tmp_path / "data")
    monkeypatch.setattr(c1, "SHARD", 2)
    entry = c1.write_shard.__wrapped__ if hasattr(c1.write_shard, "__wrapped__") else None
    del entry
    import gzip
    import hashlib
    import pickle

    path = c1.shard_path("HOWM2_CTRAIN", 0)
    path.parent.mkdir(parents=True)
    with gzip.open(path, "wb") as f:
        pickle.dump(recs, f)
    (tmp_path / "ev").mkdir()
    (tmp_path / "ev/DATA_MANIFEST.json").write_text(
        json.dumps({"shards": {"HOWM2_CTRAIN/000": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}})
    )
    cval = recs[:1]
    a = c1.train("C.1", 2, 0, 1e9, cval)
    sa = torch.load(c1.run_dir("C.1", 2, 0) / "last.pt", weights_only=True)["model"]
    import shutil

    shutil.rmtree(c1.run_dir("C.1", 2, 0))
    c1.train("C.1", 2, 0, 1e9, cval, max_steps=1)
    c1.train("C.1", 2, 0, 1e9, cval, max_steps=1)
    b = c1.train("C.1", 2, 0, 1e9, cval)
    sb = torch.load(c1.run_dir("C.1", 2, 0) / "last.pt", weights_only=True)["model"]
    assert a["step"] == 3 and b["step"] == 3 and b["done"]
    assert all(torch.equal(sa[k], sb[k]) for k in sa)
    meta = json.loads((c1.run_dir("C.1", 2, 0) / "state.json").read_text())
    assert c1.consumed_check(meta["state"], 2)["exact_no_replay"]


def test_frozen_code_unchanged():
    from hospitalos.howm import corpus as C
    from hospitalos.howm import g0check

    g0check.check()
    f1 = json.loads((ROOT / "evidence/howm1/F1.json").read_text())
    assert f1["code"] == C.code_hashes()
