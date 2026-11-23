"""B-FRAG 2 validity tests T2-1..T2-9 (PROTOCOLE_BFRAG2 s.12). DEV structures only; run before any comparison."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hospitalos.bfrag import core as K
from hospitalos.bfrag2 import core2 as C
from hospitalos.howm.world import TPD, TPH

ROOT = Path(__file__).resolve().parents[2]
D2 = json.loads((ROOT / "docs/howm2/bfrag/DESIGN_D2.json").read_text())
T0 = 60 * TPH


@pytest.fixture(scope="module")
def epi():
    w = C.structure("BF2_DEV", 0, D2)  # family SF1
    sp = C.episode_spec(w, 0)
    ep, trace = C.generate2(sp, [h * TPH for h in C.ORIGIN_HOURS], w.drop)
    return w, sp, ep, trace


def test_t2_1_as_of_strict(epi):
    _w, _sp, ep, _tr = epi
    pub, _ps, _pe = C.public_state(ep, T0)
    assert pub and all(o[1] < 15 * T0 for o in pub)
    assert any(o[1] >= 15 * T0 for o in ep.observations)  # the future exists and is excluded


def test_t2_2_features_ignore_unpublished_future(epi):
    """Features computed from the full episode equal those computed from an episode truncated at the cut."""
    w, _sp, ep, _tr = epi

    class Trunc:
        observations = [o for o in ep.observations if o[1] < 15 * T0]

    snaps = {h: C.s1_features(C.public_state(ep, h * TPH)[2]) for h in C.SNAP_HOURS if h <= 60}
    snaps_t = {h: C.s1_features(C.public_state(Trunc, h * TPH)[2]) for h in C.SNAP_HOURS if h <= 60}
    assert snaps == snaps_t
    pub, _ps, _pe = C.public_state(ep, T0)
    pub_t, _ps2, _pe2 = C.public_state(Trunc, T0)
    assert C.s2_history(pub, T0, snaps) == C.s2_history(pub_t, T0, snaps_t)
    assert C.public_key2(pub) == C.public_key2(pub_t)


def test_t2_3_no_identifiers_in_views(epi):
    w, _sp, ep, _tr = epi
    pub, _ps, pe = C.public_state(ep, T0)
    names = set(C.s0_features(w, T0)) | set(C.s1_features(pe)) | set(C.s2_history(pub, T0, {T0 // TPH: C.s1_features(pe)}))
    tokens = {t for n in names for t in n.split("_")}
    for bad in ("family", "idx", "part", "ekey", "seed", "theta", "regime", "mech", "episode", "structure", "s", "e"):
        assert bad not in tokens, bad  # whole-token check ('departure' is a public event kind, not 'part')
    # S0 uses only public structure (beds, isolation beds, resources, nominal capacity, public calendar)
    assert set(C.s0_features(w, T0)) == {"nom_A", "nom_B", "beds_A", "beds_B", "iso_A", "iso_B", "c_tr", "c_cl", "buffer",
                                          "hour_sin", "hour_cos", "day", "weekday", "drop_0_24", "drop_24_48", "drop_48_72"}


def test_t2_4_labels_and_censoring():
    runs = {"A": [(100, 120, 5)], "B": []}
    n = 192 * TPH
    lab = C.labels_at(runs, 90, n)
    assert lab["y72"] == 1 and not lab["active"] and not lab["censored"]
    assert C.labels_at(runs, 110, n)["active"]
    assert C.labels_at(runs, 130, n)["y72"] == 0
    cen = C.labels_at({"A": [], "B": []}, n - 10, n)
    assert cen["censored"] and cen["y72"] is None  # censored origins are never labelled negative
    assert all(h * TPH + C.WINDOW_H * TPH <= n for h in C.ORIGIN_HOURS)


def test_t2_5_trace_is_pure_observer_and_matches_clones(epi):
    w, sp, ep, trace = epi
    ep2, trace2 = C.generate2(sp, [h * TPH for h in C.ORIGIN_HOURS], w.drop)
    assert ep2.observations == ep.observations and trace2 == trace
    ep3, _ = C.generate2(sp, [], w.drop)
    assert ep3.observations == ep.observations  # cloning at origins does not change the history
    for h in (36, 60, 120):
        t0 = h * TPH
        inst = ep.instants[t0]
        assert inst.tick == t0
        n24 = {un: sum(1 for r in inst.queue.get(un, []) if (t0 - r.arrival) * 15 >= K.WAIT_LIMIT_MIN) for un in inst.units}
        assert n24 == {un: trace[t0 - 1][un]["n24"] for un in inst.units}  # origin state = trace index t0-1


def test_t2_6_catalogue_and_capacity_override(epi):
    w, sp, ep, _tr = epi
    for h in C.DECISION_HOURS:
        t0 = h * TPH
        wins = C.windows(t0)
        assert len(wins) == 4 and all(a >= t0 + 2 * TPH and b - a == 8 * TPH and (a % TPD) // TPH in (6, 14) for a, b in wins)
        acts = C.catalogue(t0)
        assert len(acts) == 10 and all(a["staff_hours"] <= C.STAFF_HOURS for a in acts)
    t0 = C.DECISION_HOURS[0] * TPH
    eng0 = ep.instants[t0]
    c0 = (eng0.c_cl, eng0.c_tr)
    from hospitalos.howm import generator as G

    anc = G.true_regime_at(ep, t0)
    prov = K.bf_provider(sp, 1, w.nominal, regime_anchor=anc)
    base = C.rollout_sched(eng0, prov, None, w.drop, 24)
    again = C.rollout_sched(eng0, K.bf_provider(sp, 1, w.nominal, regime_anchor=anc), None, w.drop, 24)
    assert base == again and (eng0.c_cl, eng0.c_tr) == c0 and eng0.tick == t0  # pure, no mutation
    far = C.rollout_sched(eng0, K.bf_provider(sp, 1, w.nominal, regime_anchor=anc), None, w.drop, 24,
                          {"cl": (t0 + 100 * TPH, t0 + 108 * TPH)})
    assert far == base  # a reinforcement outside the horizon is a no-op
    assert abs(base["wait_patient_min"] - sum(base["wait_by_unit"].values())) < 1e-6


def test_t2_7_paired_controls_share_arrivals(epi):
    w, sp, ep, _tr = epi
    arr = [o for o in ep.observations if o[2] == "request_arrival"]
    for dep in C.PAIRED_DEPS:
        ep_d, _ = C.generate2(*C.paired_spec(w, 0, dep)[:1], [], C.paired_spec(w, 0, dep)[1])
        assert [o for o in ep_d.observations if o[2] == "request_arrival"][:40] == arr[:40], dep
    assert C.paired_spec(w, 0, "compat")[0].iso_beds == C.paired_spec(w, 0, "compat")[0].beds


def test_t2_10_reference_trajectory_applies_public_calendar():
    """The continuous reference trajectory applies the planned drop exactly like every rollout
    (correction logged before the freeze): during the drop the true cleaning capacity is reduced."""
    w = C.structure("BF2_DEV", 2, D2)  # family SF3 (planned drop)
    assert w.drop
    sp = C.episode_spec(w, 0)
    on = [h * TPH for h in range(0, 192) if K.drop_at(w.drop, h * TPH)]
    assert on
    ep_d, _ = C.generate2(sp, [], w.drop)
    ep_n, _ = C.generate2(sp, [], {})
    assert ep_d.observations != ep_n.observations  # the calendar changes the reference history
    pre = [o for o in ep_d.observations if o[0] < 15 * on[0]]
    assert pre == [o for o in ep_n.observations if o[0] < 15 * on[0]]  # ... and nothing before the drop


def test_t2_8_partitions_disjoint_and_new():
    C.register()
    from hospitalos.howm import generator as G

    keys = {p: {G.establishment(p, s).ekey for s in range(min(n, 40))} for p, n in C.PARTS.items()}
    ps = list(keys)
    for i in range(len(ps)):
        for j in range(i + 1, len(ps)):
            assert not keys[ps[i]] & keys[ps[j]]
    old = json.loads((ROOT / "evidence/howm2_bfrag/MANIFEST_PARTITIONS.json").read_text())["partitions"]
    assert not set(C.PARTS) & set(old)
    new = set().union(*keys.values())
    for p, meta in old.items():  # B-FRAG 1 partitions: no shared structure key
        assert not new & {G.establishment(p, s).ekey for s in range(min(meta["size"], 40))}, p


def test_t2_9_frozen_files_unchanged():
    fr = json.loads((ROOT / "evidence/howm2_bfrag/FREEZE_BFRAG.json").read_text())
    for p, h in fr["files_sha256"].items():
        assert hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h, p
    from hospitalos.howm import corpus as CO
    from hospitalos.howm import g0check

    g0check.check()
    assert json.loads((ROOT / "evidence/howm1/F1.json").read_text())["code"] == CO.code_hashes()
