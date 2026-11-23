"""Decision n.8 pilot tests (PROTOCOLE_PILOTE_W s.11). DEV structures and the 4 cost-pilot TRAIN files only."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from hospitalos.bfrag import core as K  # noqa: E402
from hospitalos.bfrag2 import core2 as C  # noqa: E402
from hospitalos.bfrag2w import core_w as W  # noqa: E402
from hospitalos.howm import generator as G  # noqa: E402
from hospitalos.howm.world import TPH  # noqa: E402

HIST = {  # B-FRAG 2 historical deliverables (commit 9d4490e)
    "evidence/howm2_bfrag2/RESULTS_BFRAG2_CONF.json": "48ac53fb2a469ad827a09353c527097920184ddcdbe093411b91e055d7cdd93c",
    "evidence/howm2_bfrag2/SELECTION_VAL.json": "0686a79138c25315272dc461a5c6314437e2afd95372c0521b5918c0a3e5a71a",
    "docs/howm2/bfrag/RAPPORT_BFRAG2.md": "bcc161adc5ceeb80c2e1ecdb1c8d8509a027d8848570c1637c8b352d7c0f212b",
    "docs/howm2/bfrag/PROTOCOLE_BFRAG2.md": "2f01e6e1f459109737b8b43b5c283082bf9b2188c97b8e4431ceee79e7c8aa58",
}


@pytest.fixture(scope="module")
def sf3():
    w = W.structure("BF2_DEV", 2)  # SF3 planned drop
    sp = C.episode_spec(w, 2)
    t0 = C.DECISION_HOURS[2] * TPH
    ep, _ = C.generate2(sp, [t0 - 24 * TPH, t0 - 6 * TPH, t0], w.drop)
    return w, sp, ep, t0


def test_w1_partitions_new_and_disjoint():
    K.register()
    W.register()
    new = {G.establishment("BF2W_CONF", s).ekey for s in range(60)}
    for p in list(C.PARTS) + ["BFRAG_DEV", "BFRAG_TUNE", "BFRAG_CONF"]:
        assert not new & {G.establishment(p, s).ekey for s in range(min(60, G.PARTITION_SIZES[p]))}, p


def test_w2_public_inputs_match_bfrag2_driver_and_no_private_names(sf3):
    w, sp, ep, t0 = sf3
    x = W.public_inputs(w, ep, t0)
    rec = json.loads((ROOT / "evidence/howm2_bfrag2/runs/F/BF2_TRAIN/s000_e0.json").read_text())
    ww = W.structure("BF2_TRAIN", 0)
    ep0, _ = C.generate2(C.episode_spec(ww, 0), [], ww.drop)
    o = next(o for o in rec["origins"] if o["hour"] == 42)
    xx = W.public_inputs(ww, ep0, 42 * TPH)
    assert xx == {"S0": o["S0"], "S1": o["S1"], "S2": o["S2"]}  # identical to the B-FRAG 2 driver
    names = {n for v in x.values() for n in v} | set(W.calendar_descriptor(w.drop, t0)) | set(W.action_descriptor(C.catalogue(t0)[3], t0))
    tokens = {t for n in names for t in n.split("_")}
    for bad in ("theta", "seed", "ekey", "family", "regime", "mech", "idx", "F", "future"):
        assert bad not in tokens, bad


def test_w3_calendar_corrected_and_schedule(sf3):
    w, sp, ep, t0 = sf3
    cd = W.calendar_descriptor(w.drop, t0)
    assert cd["c_has_drop"] == 1.0 and cd["c_drop_start_h"] == 78 - 66 and cd["c_drop_end_h"] == 94 - 66
    a_none = C.catalogue(t0)[0]
    U = W.step_schedule(W.action_descriptor(a_none, t0), cd, t0)
    assert U[:, 2].sum() * W.STEP_H == (94 - 78) * w.drop["minus"]
    anc = G.true_regime_at(ep, t0)
    r1 = W.rollout_traj(ep.instants[t0], K.bf_provider(sp, 1, w.nominal, regime_anchor=anc), None, w.drop)
    r2 = W.rollout_traj(ep.instants[t0], K.bf_provider(sp, 1, w.nominal, regime_anchor=anc), None, {})
    assert r1["states"] != r2["states"]  # the public calendar acts in the trajectory


def test_w4_common_origin_paired_keys_and_cumulative_cost(sf3):
    w, sp, ep, t0 = sf3
    anc = G.true_regime_at(ep, t0)
    for a in C.catalogue(t0)[:4]:
        tr = W.rollout_traj(ep.instants[t0], K.bf_provider(sp, 3, w.nominal, regime_anchor=anc), a["plan"], w.drop, a["extra"])
        ref = C.rollout_sched(ep.instants[t0], K.bf_provider(sp, 3, w.nominal, regime_anchor=anc), a["plan"], w.drop, 168, a["extra"])
        for k in ("wait_patient_min", "uncovered_care_min", "rejected_total", "rupture_minutes", "terminal_queue", "terminal_max_wait_min"):
            assert tr[k] == ref[k], k
        assert abs(np.array(tr["step_costs"]).sum() - tr["wait_patient_min"]) < 1e-6
        assert len(tr["states"]) == W.N_STEPS == 84
    assert ep.instants[t0].tick == t0


def test_w5_slots_inaction_and_coordination(sf3):
    w, sp, ep, t0 = sf3
    cd = W.calendar_descriptor(w.drop, t0)
    acts = C.catalogue(t0)
    U0 = W.step_schedule(W.action_descriptor(acts[0], t0), cd, t0)
    assert U0[:, [0, 1, 3, 4]].sum() == 0  # inaction: no action input at any step
    Uh = W.step_schedule(W.action_descriptor(acts[1], t0), cd, t0)
    assert Uh[0, 4] == 1 and Uh[1:, 4].sum() == 0 and Uh[:, 3].sum() * W.STEP_H == W.COMPAT_H
    for a in acts[2:]:
        d = W.action_descriptor(a, t0)
        U = W.step_schedule(d, cd, t0)
        res = 0 if d["a_res_cl"] else 1
        assert U[:, res].sum() * W.STEP_H == 8 and U[:, 1 - res].sum() == 0
        start = next(iter(a["extra"].values()))[0]
        assert d["a_start_h"] == (start - t0) / TPH and U[int(d["a_start_h"] // 2), res] > 0
    # a boundary inside a step is represented by a fraction (no silent truncation)
    d = dict(W.action_descriptor(acts[2], t0), a_start_h=3.0)
    U = W.step_schedule(d, cd, t0)
    assert U[1, 0] == 0.5 and U[5, 0] == 0.5 and U[:, 0].sum() * W.STEP_H == 8


def test_w6_w_rollout_uses_no_future_state_and_reloads():
    import torch

    import bf2w_models as M

    net = M.make_w(88)
    x0 = torch.zeros(3, 88)
    U = torch.rand(3, 84, 8)
    s1, c1 = net(x0, U)
    U2 = U.clone()
    U2[:, 40:] += 1.0
    s2, c2 = net(x0, U2)
    assert torch.equal(s1[:, :40], s2[:, :40]) and torch.equal(c1[:, :40], c2[:, :40])  # causal in the schedule only
    import inspect

    assert list(inspect.signature(net.forward).parameters) == ["x0", "sched"]  # no state / target input
    path = ROOT / "evidence/howm2_bfrag2w/_test_ck.pt"
    torch.save({"state": net.state_dict()}, path)
    net2 = M.make_w(88)
    net2.load_state_dict(torch.load(path, weights_only=False)["state"])
    path.unlink()
    assert torch.equal(net2(x0, U)[1], c1)
    assert sum(p.numel() for p in net.parameters()) < 1_000_000


def test_w7_historical_sources_and_results_unchanged():
    # latest frozen version of every file: B-FRAG 1 freeze, then B-FRAG 2 freeze 1 overridden by freeze 2
    # (freeze 2 records the files legitimately changed between the two freezes: driver slot scheduler, lot caps)
    latest: dict = {}
    for fr in ("evidence/howm2_bfrag/FREEZE_BFRAG.json", "evidence/howm2_bfrag2/FREEZE1_PROTOCOL.json", "evidence/howm2_bfrag2/FREEZE2_BFRAG2.json"):
        latest.update(json.loads((ROOT / fr).read_text())["files_sha256"])
    for p, h in latest.items():
        assert hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h, p
    for p, h in HIST.items():
        assert hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h, p
    from hospitalos.howm import corpus as CO
    from hospitalos.howm import g0check

    g0check.check()
    assert json.loads((ROOT / "evidence/howm1/F1.json").read_text())["code"] == CO.code_hashes()
