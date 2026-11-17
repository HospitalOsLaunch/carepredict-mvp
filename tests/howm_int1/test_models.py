"""HOWM-INT-1 tests on partitions, inputs, models and frozen history (M1-M7)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/int1"))

from hospitalos.howmint import data as DA  # noqa: E402
from hospitalos.howmint import features as F  # noqa: E402
from hospitalos.howmint import models as MO  # noqa: E402
from hospitalos.howmint import world as W  # noqa: E402


def test_m1_partitions_distinct_and_heldout_combos_excluded():
    import corpus as CO
    from hospitalos.howm.keys import key

    parts = ("INT_TRAIN", "INT_VAL", "INT_DEV", "INT_TEST_MAIN", "INT_TEST_EXT", "INT_TEST_COMBO", "INT_TEST_12")
    keys = {p: {key("INT-struct", p, s) for s in range(300)} for p in parts}
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            assert not keys[a] & keys[b]
    for part in ("INT_TRAIN", "INT_VAL"):
        for s in range(400):
            n = CO.size_of(part, s)
            if n > 2:
                sp = CO.train_structure(part, s, n)
                assert not any(p <= set(sp.bottlenecks) for p in CO.HELDOUT_PAIRS), (part, s, sp.bottlenecks)


def test_m2_public_input_names_have_no_private_fields():
    names = set(F.UNIT_F) | set(F.HIST_KEYS) | set(F.RES_F) | set(F.GLOB_F)
    toks = {t for n in names for t in n.split("_")}
    for bad in ("theta", "seed", "ekey", "regime", "mech", "family", "future", "true", "slow", "noshow", "lag"):
        assert bad not in toks, bad
    assert F.UNIT_DIM == MO.UNIT_IN and F.RES_DIM == MO.RES_IN and F.GLOB_DIM == MO.GLOB_IN


def _batch(n=3, T=10, B=2):
    g = torch.Generator().manual_seed(0)
    r = lambda *s: torch.randn(*s, generator=g)  # noqa: E731
    return {"unit": r(B, n, 54), "res": r(B, 3, 10), "glob": r(B, 8), "ur_mask": torch.ones(B, n, 3), "uu": torch.rand(B, n, n, generator=g),
            "U": r(B, T, n, 3), "R": r(B, T, 3, 3), "C": r(B, T, 3), "beds": torch.full((B, n), 20.0)}


@pytest.mark.parametrize("ablate", ["", "no_msg", "no_hist"])
def test_m3_w_rollout_causal_in_schedule_and_no_target_input(ablate):
    torch.manual_seed(0)
    m = MO.GraphWM(32, use_messages=ablate != "no_msg", use_history=ablate != "no_hist").eval()
    b = _batch()
    with torch.no_grad():
        s1, c1, r1 = m(**b)
        b2 = dict(b)
        b2["U"] = b["U"].clone()
        b2["U"][:, 6:] += 3.0
        s2, c2, r2 = m(**b2)
    assert torch.allclose(s1[:, :6], s2[:, :6]) and torch.allclose(c1[:, :6], c2[:, :6]) and not torch.allclose(c1[:, 6:], c2[:, 6:])
    import inspect

    assert "states" not in inspect.signature(m.forward).parameters and "costs" not in inspect.signature(m.forward).parameters


def test_m4_constraints_by_construction():
    m = MO.GraphWM(32).eval()
    with torch.no_grad():
        s, c, _r = m(**_batch())
    assert torch.allclose(s[..., :3].sum(-1), torch.ones_like(s[..., 0]))  # bed-state fractions sum to 1
    assert (s[..., 3:] >= 0).all() and (c >= 0).all()
    assert (s[..., 4] <= s[..., 3] + 1e-6).all() and (s[..., 5] <= s[..., 4] + 1e-6).all()  # q24 <= q12 <= queue


def test_m5_checkpoint_reload_reproduces_predictions(tmp_path):
    m = MO.GraphWM(32).eval()
    b = _batch()
    torch.save({"model": m.state_dict()}, tmp_path / "x.pt")
    m2 = MO.GraphWM(32).eval()
    m2.load_state_dict(torch.load(tmp_path / "x.pt", weights_only=False)["model"])
    with torch.no_grad():
        assert torch.equal(m(**b)[1], m2(**b)[1])


def test_m6_pack_roundtrip(tmp_path):
    S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad/int1_corpus")
    if not (S / "INT_TRAIN").exists():
        pytest.skip("corpus not present")
    DA.pack(S, "INT_TRAIN", [0, 1, 3], tmp_path)
    ps = DA.packed_situations(tmp_path)
    ref = DA.situations(DA.load(S, "INT_TRAIN", [0, 1, 3]))
    assert len(ps) == len(ref)
    key = lambda x: (x["structure"], x["n"], float(x["desc"].sum()))  # noqa: E731
    for a, b in zip(sorted(ps, key=key), sorted(ref, key=key)):
        assert np.allclose(a["unit"], b["unit"]) and np.allclose(a["costs"], b["costs"][:, :2])


def test_m7_historical_sources_and_results_unchanged():
    latest: dict = {}
    for fr in ("evidence/howm2_bfrag/FREEZE_BFRAG.json", "evidence/howm2_bfrag2/FREEZE1_PROTOCOL.json", "evidence/howm2_bfrag2/FREEZE2_BFRAG2.json",
               "evidence/howm2_bfrag2w/FREEZE_PILOT.json"):
        latest.update(json.loads((ROOT / fr).read_text())["files_sha256"])
    for p, h in latest.items():
        assert hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h, p
    for p in ("evidence/howm2_bfrag2/RESULTS_BFRAG2_CONF.json", "evidence/howm2_bfrag2w/RESULTS_PILOT_W.json"):
        assert (ROOT / p).exists()
