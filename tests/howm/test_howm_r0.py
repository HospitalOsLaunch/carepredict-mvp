"""HOWM-1 R0/R1 blocking tests (TEST_MATRIX_HOWM1 + NORM v1.2 additions). Synthetic only."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import random
import subprocess
from pathlib import Path

import numpy as np
import pytest
import torch

from hospitalos.howm import ckpt, heads, keys
from hospitalos.howm.controllers import CHOICE_R, EVAL_R, evaluate_instant, obj_lex
from hospitalos.howm.dataset import build
from hospitalos.howm.galt import simulate_queue
from hospitalos.howm.generator import (
    EVAL_DAY,
    PARTITION_SIZES,
    SEALED,
    SealedPartitionError,
    TruthProvider,
    establishment,
    generate,
    refresh_private,
)
from hospitalos.howm.history import PublicStream, assert_no_private, hourly_tables
from hospitalos.howm.manual import Hypothesis, Locks, manual_universe, simulate_hypothesis
from hospitalos.howm.nets import B2, H1, NetConfig, forward_losses, make_batch, n_params, predict
from hospitalos.howm.predict import b0_predict, item_set_fingerprint, member_logscores
from hospitalos.howm.rollout import ModelProvider, NewProfileFreq, rollout, rollout_key
from hospitalos.howm.verify import check, initial_from_engine
from hospitalos.howm.world import A3_OPTIONS, candidates

ROOT = Path(__file__).resolve().parents[2]
FREQ = NewProfileFreq(0.15, (0.4, 0.4, 0.2), 0.6)


# ----------------------------------------------------------------------------- helpers
def future_perturbed(obs, t):
    """Drop every observation available after t (a different private future, same public past)."""
    return [o for o in obs if o[1] <= t]


def rename(obs):
    names: dict[str, str] = {}

    def nm(x):
        if x not in names:
            names[x] = "E" + hashlib.sha256(("salt" + x).encode()).hexdigest()[:10]
        return names[x]

    out = []
    for ev, av, kind, subj, un, v in obs:
        v = dict(v)
        if kind == "static":
            v = json.loads(json.dumps(v))
            for d in v["units"].values():
                d["beds"] = [[nm(b), iso] for b, iso in d["beds"]]
        for f in ("bed", "rid"):
            if f in v:
                v[f] = nm(v[f])
        out.append((ev, av, kind, nm(subj) if kind not in ("static", "plan") else subj, un, v))
    return out, names


def preds_all(b0p, est, H):
    torch.manual_seed(0)
    b2, h1 = B2(b0p), H1(b0p)
    od = est.origins[H]
    return {
        "B0-pool": b0_predict(b0p, od, est, False),
        "B0-local": b0_predict(b0p, od, est, True),
        "B2": predict(b2, est, H),
        "H1": predict(h1, est, H),
    }


def by_ref(pred, od):
    out = {}
    for fam, arr in pred.delta_items.items():
        for it, d in zip(od.items.get(fam, []), arr, strict=True):
            out[(fam, it["ref"])] = float(d)
    for i, sid in enumerate(od.care_ref):
        out[("care", sid)] = pred.care_mu[i].round(6).tolist()
    return out


# ----------------------------------------------------------------------------- T-INF
def test_T_INF_01_available_at_filter(val_ep):
    t = 100 * 60
    extra = (t - 30, t + 1, "departure", "SAinit_BA00", "A", {"bed": "BA00", "unit": "A"})
    a = PublicStream(val_ep.observations)
    b = PublicStream(val_ep.observations + [extra])
    a.advance(t), b.advance(t)
    assert a.cohort(t) == b.cohort(t)
    assert sorted(a.present_stays()) == sorted(b.present_stays())
    ta = hourly_tables(val_ep.observations, 100)
    tb = hourly_tables(val_ep.observations + [extra], 100)
    assert np.array_equal(ta.b2, tb.b2)


def test_T_INF_02_no_private_in_public_state(val_ep):
    ps = PublicStream(val_ep.observations)
    ps.advance(100 * 60)
    assert_no_private(
        {
            "stays": ps.stays,
            "requests": ps.requests,
            "offers": ps.offers,
            "cohort": ps.cohort(100 * 60),
        }
    )
    with pytest.raises(AssertionError):
        assert_no_private({"x": {"theta": 1}})


def test_T_INF_03_same_public_past_same_outputs(val_ep, b0p):
    H = 100
    e1 = build(val_ep, [H])
    ep2 = type(val_ep)(
        **{**val_ep.__dict__, "observations": future_perturbed(val_ep.observations, H * 60)}
    )
    e2 = build(ep2, [H])
    p1, p2 = preds_all(b0p, e1, H), preds_all(b0p, e2, H)
    for name in p1:
        assert by_ref(p1[name], e1.origins[H]) == by_ref(p2[name], e2.origins[H]), name
        assert np.allclose(p1[name].arr_mu, p2[name].arr_mu)
    # labels / masks differ (truth side only) — T-MASK-01
    assert not np.array_equal(e1.origins[H].care_mask, e2.origins[H].care_mask)


def test_T_INF_04_week_shift_invariance(val_ep):
    ep2 = type(val_ep)(
        **{
            **val_ep.__dict__,
            "spec": type(val_ep.spec)(
                **{**val_ep.spec.__dict__, "start_utc": "2027-03-08T23:00:00+00:00"}
            ),
        }
    )
    assert np.array_equal(build(val_ep, [60]).b2, build(ep2, [60]).b2)


def test_T_INF_05_T_EQV_01_renaming(val_ep, b0p):
    H = 100
    obs2, names = rename(val_ep.observations)
    e1 = build(val_ep, [H])
    e2 = build(type(val_ep)(**{**val_ep.__dict__, "observations": obs2}), [H])
    assert np.array_equal(e1.b2, e2.b2)
    inv = {v: k for k, v in names.items()}
    p1, p2 = preds_all(b0p, e1, H), preds_all(b0p, e2, H)
    for name in p1:
        r1 = by_ref(p1[name], e1.origins[H])
        r2 = {}
        for (fam, ref), v in by_ref(p2[name], e2.origins[H]).items():
            back = (
                ref.split(":", 1)[0] + ":" + inv[ref.split(":", 1)[1]] if ":" in ref else inv[ref]
            )
            r2[(fam, back)] = v
        assert r1.keys() == r2.keys()
        for k in r1:
            assert np.allclose(np.asarray(r1[k]), np.asarray(r2[k]), atol=1e-5), (name, k)


def test_T_INF_09_private_backends_refused():
    with pytest.raises(ckpt.CheckpointRefused):
        ckpt.load_verified(ROOT / "artifacts" / "v1_full" / "rssm_checkpoint.pt", "0" * 64)


def test_T_EQV_02_same_time_order(val_ep):
    obs = list(val_ep.observations)
    random.Random(3).shuffle(obs)
    assert np.array_equal(hourly_tables(obs, 60).b2, hourly_tables(val_ep.observations, 60).b2)


# ----------------------------------------------------------------------------- T-OP / T-LIFE
def test_T_OP_01_12_verifier_on_truth(train_eps):
    for ep in train_eps:
        assert check(ep.truth_log, ep.static, ep.capacity) == []
        assert set(ep.rejections) <= {
            "lender_minimum",
            "duplicate_offer",
        }  # refused planner requests only


@pytest.mark.parametrize(
    "mutation,needle",
    [
        (lambda L: [(0, "cleaning_start", "BA00", {})] + L, "cleaning_not_after_departure"),
        (
            lambda L: (
                L
                + [
                    (
                        5,
                        "placed",
                        "SX",
                        {
                            "bed": next(e[3]["bed"] for e in L if e[1] == "placed"),
                            "unit": "A",
                            "iso": False,
                        },
                    )
                ]
            ),
            "double_occupancy",
        ),
        (lambda L: L + [(3, "offer_present", "OZ", {})], "present_without_confirmation"),
        (
            lambda L: L + [(9, "departure", "SAinit_never", {"bed": "BA00"})],
            "departure_without_authorisation",
        ),
        (lambda L: L + [(9, "transport_start", "Snot", {})], "executed_without_acceptance"),
    ],
)
def test_T_OP_03_adversarial_logs_detected(train_eps, mutation, needle):
    ep = train_eps[0]
    bad = sorted(mutation(list(ep.truth_log)), key=lambda e: e[0])
    assert any(needle in p for p in check(bad, ep.static, ep.capacity))


def test_T_OP_04_capacity_overrun_detected(train_eps):
    ep = train_eps[0]
    extra = [(400, "transport_start", f"S{i}", {}) for i in range(ep.static["c_tr"] + 1)]
    extra += [(401, "transport_accepted", f"S{i}", {}) for i in range(4)]
    assert any(
        "transport_over_capacity" in p
        for p in check(sorted(ep.truth_log + extra, key=lambda e: e[0]), ep.static)
    )


def test_T_OP_06_07_08_operator_refusals(val_ep):
    eng = val_ep.instants[EVAL_DAY * 96 + 11 * 4].clone()
    prov = TruthProvider(val_ep.spec, 1)
    st = next(s for s in eng.stays.values() if not s.authorised and s.departed is None)
    before = eng.rejected
    assert eng.request_transport(st, prov) is False  # T-OP-06: never for an unauthorised stay
    eng.depart(st)  # T-OP-08: precondition violated -> rejected, state unchanged
    assert st.departed is None and eng.rejected == before + 2
    eng.request_reinforcement("pool_IDE_A", prov)
    assert eng.request_reinforcement("pool_IDE_A", prov) is False  # unique offer_key
    assert eng.rejections.get("duplicate_offer") == 1


def test_T_OP_10_catalogue():
    c = candidates()
    assert len(c) == 16 and c[0].cid == "0|fifo|none"
    assert {p.reinforcement for p in c} == set(A3_OPTIONS)
    assert {p.cleaning for p in c} == {"fifo", "compat"}


def _rollout_log(engine0, prov, plan):
    eng = engine0.clone()
    refresh_private(eng, prov)
    init = initial_from_engine(eng)
    eng.emit_log = True
    t0 = eng.tick
    eng.apply_plan(plan, prov)
    eng.run(prov, t0 + 96)
    return eng, init, t0


def test_T_OP_01_09_11_rollouts_respect_invariants(val_ep, val_est, b0p):
    H = 100
    ps = PublicStream(val_ep.observations)
    ps.advance(H * 60)
    eng0 = ps.to_engine(H * 60)
    preds = preds_all(b0p, val_est, H)
    for name in ("B0-local", "H1"):
        for m in range(2):
            prov = ModelProvider(
                preds[name], val_est.origins[H], 4 * H, m, rollout_key("VAL", 1, H), FREQ
            )
            for plan in (candidates()[0], candidates()[15]):
                eng, init, t0 = _rollout_log(eng0, prov, plan)
                cap = {k: v for k, v in eng.capacity.items() if k[2] >= t0 // 4}
                assert check(eng.log, val_ep.static, cap, start_tick=t0, initial=init) == [], (
                    name,
                    plan.cid,
                )
                assert all(v >= 0 for v in eng.waiting_ticks.values())


def test_T_LIFE_04_05_manual_mode(val_ep):
    u = manual_universe(Locks(reinforcement="pool_IDE_A"))
    assert len(u) == 4 and all(p.reinforcement == "pool_IDE_A" for p in u)
    eng = val_ep.instants[EVAL_DAY * 96 + 11 * 4]
    sid = next(s for s, st in eng.stays.items() if not st.authorised and st.departed is None)
    res = simulate_hypothesis(
        eng, candidates()[0], Hypothesis([sid]), TruthProvider(val_ep.spec, 2)
    )
    assert res["approvable"] is False and res["hypothetical"] is True
    assert not eng.stays[sid].authorised  # real state untouched


# ----------------------------------------------------------------------------- T-GEN
def test_T_GEN_01_keyed_draws():
    a = [keys.u(1, "x", i) for i in range(50)]
    b = [keys.u(1, "x", i) for i in reversed(range(50))][::-1]
    assert a == b and all(0 < x < 1 for x in a)


def test_T_GEN_02_paired_branches_share_innovations(val_ep):
    eng = val_ep.instants[EVAL_DAY * 96 + 7 * 4]
    calls = {}

    class Rec(TruthProvider):
        def care(self, e, st, hour):
            v = super().care(e, st, hour)
            calls.setdefault(self._tag, {})[(st.sid, hour)] = v
            return v

    for tag, plan in (("a", candidates()[0]), ("b", candidates()[9])):
        p = Rec(val_ep.spec, 3)
        p._tag = tag
        rollout(eng, p, plan)
    common = set(calls["a"]) & set(calls["b"])
    assert len(common) > 100 and all(calls["a"][k] == calls["b"][k] for k in common)


def test_T_GEN_03_04_05_partitions_and_seals():
    seen = {}
    for p, n in PARTITION_SIZES.items():
        for i in range(n):
            k = keys.key("HOWM1", p, i)
            assert k not in seen
            seen[k] = (p, i)
    p5 = json.loads((ROOT / "evidence/decision_support/p5/SEEDS_SEALED.json").read_text())
    p5_ints = {int(x) for part in p5.get("partitions", {}).values() for x in part}
    assert not (p5_ints & set(seen))
    for p in SEALED:
        with pytest.raises(SealedPartitionError):
            establishment(p, 0)


def test_T_GEN_07_regeneration_identical():
    a = generate(establishment("TRAIN", 5)).observations
    b = generate(establishment("TRAIN", 5)).observations
    assert (
        hashlib.sha256(repr(a).encode()).hexdigest() == hashlib.sha256(repr(b).encode()).hexdigest()
    )


def test_T_GEN_08_galt_informative():
    """Informative (non-blocking) KS of service durations, G_alt vs G_main mechanism (m0+m1)."""
    from scipy.stats import ks_2samp

    alt = simulate_queue(400, 2, 50.0, 0.35, 40.0, seed=7)["duration"]
    spec = establishment("TRAIN", 1)
    prov = TruthProvider(
        type(spec)(
            **{
                **spec.__dict__,
                "theta": {**spec.theta, "cl_min": 50.0},
                "mech": {**spec.mech, "m2": False},
            }
        ),
        9,
    )
    from hospitalos.howm.world import Bed

    main = []
    for i in range(400):
        b = Bed(f"b{i}", "A", False, state="cleaning", dirty_tick=i, clean_start=0)
        main.append(prov.cleaning_end(type("E", (), {"tick": 0})(), b) * 15)
    res = ks_2samp(alt, main)
    assert res.statistic < 0.2  # informative threshold; the value is reported by the R0 receipt


def test_T_GEN_09_generator_reads_no_model():
    tree = ast.parse((ROOT / "src/hospitalos/howm/generator.py").read_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not mods & {"nets", "predict", "train", "b0", "rollout", "controllers"}


# ----------------------------------------------------------------------------- T-DIST / T-NORM / T-BIN
def test_T_DIST_01_02_hazard_valid_and_exact():
    rng = np.random.default_rng(0)
    logits = rng.normal(-2, 1, (5, heads.NB))
    lp = np.stack(
        [
            heads.hazard_logprob(logits, np.zeros(5, int), np.full(5, b), np.ones(5, bool))
            for b in range(heads.NB)
        ]
    )
    tail = heads.hazard_logprob(logits, np.zeros(5, int), np.full(5, heads.NB), np.zeros(5, bool))
    assert np.allclose(np.exp(lp).sum(0) + np.exp(tail), 1.0)
    h = 0.1
    lg = np.full((1, heads.NB), math.log(h / (1 - h)))
    for b in (3, 10):
        got = heads.hazard_logprob(lg, np.array([2]), np.array([b]), np.array([True]))[0]
        assert abs(got - (math.log(h) + (b - 2) * math.log(1 - h))) < 1e-9
    t = heads.t_hazard_logprob(
        torch.tensor(logits),
        torch.zeros(5, dtype=torch.long),
        torch.full((5,), 7),
        torch.ones(5, dtype=torch.bool),
    )
    assert np.allclose(
        t.numpy(), heads.hazard_logprob(logits, np.zeros(5, int), np.full(5, 7), np.ones(5, bool))
    )


def test_T_BIN_01_care_bins_partition():
    mids = np.array([2.5 + 5 * k for k in range(121)])
    p = np.exp(heads.care_logprob(mids, np.full(121, 2.4), np.full(121, 0.5)))
    assert abs(p.sum() - 1.0) < 1e-9 and (p > 0).all()
    t = heads.t_care_logprob(
        torch.tensor(mids),
        torch.full((121,), 2.4, dtype=torch.float64),
        torch.full((121,), 0.5, dtype=torch.float64),
    )
    assert np.allclose(t.numpy(), np.log(p))
    assert heads.care_bin(np.array([0, 4.9, 5, 600, 10**6])).tolist() == [0, 0, 1, 120, 120]


def test_T_NORM_01_04_scales():
    for bad in (-0.5, 0.0, 1e-9, float("nan"), float("inf")):
        with pytest.raises(heads.ScaleError):
            heads.check_scales({"f": bad})
    s = {"f": 2.0}
    assert heads.normalised_loss({"f": 1.0}, s) < heads.normalised_loss({"f": 1.5}, s)
    y = np.array([True, False, True, True])
    assert (
        -heads.bernoulli_logprob(y, np.array([0.7] * 4)).mean()
        < -heads.bernoulli_logprob(y, np.array([0.3] * 4)).mean()
    )
    assert (-heads.nb_logpmf(np.arange(10.0), np.full(10, 3.0), 2.0) >= 0).all()


def test_T_DIST_03_coverage_from_realisations():
    y = np.zeros(200)
    samples = np.random.default_rng(1).normal(5.0, 0.1, (16, 200))  # confident and wrong
    lo, hi = np.quantile(samples, 0.05, axis=0), np.quantile(samples, 0.95, axis=0)
    assert np.mean((y >= lo) & (y <= hi)) == 0.0


# ----------------------------------------------------------------------------- T-PLAN / T-CFG / T-CKPT
def test_T_PLAN_03b_disjoint_and_oracle(val_ep):
    assert not set(EVAL_R) & set(CHOICE_R)
    tau = EVAL_DAY * 96 + 15 * 4
    ps = PublicStream(val_ep.observations)
    ps.advance(tau * 15)
    out = evaluate_instant(val_ep, tau, ps.to_engine(tau * 15), {}, controllers=())
    ev = np.array(out["eval_u"])
    assert abs(out["oracle_U_star"] - ev.min(axis=1).mean()) < 1e-9
    assert out["oracle_U_star"] <= out["value"]["habitual"]
    assert obj_lex([10.0] * 16) == 0


def test_T_PLAN_07_same_item_set(val_est, b0p):
    od = val_est.origins[100]
    preds = preds_all(b0p, val_est, 100)
    fp = item_set_fingerprint(od)
    for p in preds.values():
        sc = member_logscores(p, od, 24)
        assert len(sc["care"]) == 2 * int(od.care_mask.sum())  # two skills per masked stay-hour
        assert all(len(p.delta_items[f]) == len(od.items[f]) for f in p.delta_items)
    assert fp == item_set_fingerprint(od)


def test_T_CFG_01_05(b0p, val_est):
    with pytest.raises(ValueError):
        NetConfig("H1", context="on")
    with pytest.raises(ValueError):
        NetConfig("B2", jepa="on")
    for M in (B2, H1):
        m = M(b0p)
        names = [n for n, _ in m.named_parameters()]
        assert not any(k in n for n in names for k in ("context", "jepa", "contrast", "stoch"))
        assert n_params(m)["total"] == sum(p.numel() for p in m.parameters())
        batch = make_batch([(val_est, 100)], "B2" if M is B2 else "H1")
        a = forward_losses(m, batch)
        b = forward_losses(m, batch)
        assert all(float(a[f][0]) == float(b[f][0]) for f in a)  # deterministic (T-CFG-04)


def test_T_CKPT_01_02_03_resume_equals_continuous(tmp_path, monkeypatch, val_est, b0p):
    from hospitalos.howm import train as T

    monkeypatch.setattr(T, "RUNS", tmp_path / "evidence" / "howm1" / "train")
    pairs = [(val_est, H) for H in (40, 60, 100, 120)] * 16
    scales = dict.fromkeys(
        ("auth", "ready", "transport", "cleaning", "confirmation", "presence", "arrivals", "care"),
        1.0,
    )
    T.train("B2", 1e-3, 0, 10**6, pairs, pairs[:4], b0p, scales, max_steps=4)
    full = torch.load(T.run_dir("B2", 1e-3, 0) / "last.pt", weights_only=True)
    monkeypatch.setattr(T, "RUNS", tmp_path / "evidence" / "howm1" / "train2")
    T.train("B2", 1e-3, 0, 10**6, pairs, pairs[:4], b0p, scales, max_steps=2)
    T.train("B2", 1e-3, 0, 10**6, pairs, pairs[:4], b0p, scales, max_steps=2)
    resumed = torch.load(T.run_dir("B2", 1e-3, 0) / "last.pt", weights_only=True)
    assert set(full) >= {
        "model",
        "optimizer",
        "scheduler",
        "rng",
        "position",
        "state_json",
        "config_json",
    }
    for k in full["model"]:
        assert torch.allclose(full["model"][k], resumed["model"][k], atol=1e-6), k
    meta = json.loads((T.run_dir("B2", 1e-3, 0) / "state.json").read_text())
    meta["config"]["code"] = {"changed": "x"}
    (T.run_dir("B2", 1e-3, 0) / "state.json").write_text(json.dumps(meta))
    with pytest.raises(ckpt.CheckpointRefused):
        T.train("B2", 1e-3, 0, 10**6, pairs, pairs[:4], b0p, scales, max_steps=1)


def test_T_V0_01_v6_unchanged():
    out = subprocess.run(
        ["git", "diff", "--stat", "856a57c", "--", "src/hospitalos/decision_support"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0 and out.stdout.strip() == ""


def test_T_V0_05_checkpoint_policy(tmp_path):
    p = tmp_path / "x.pt"
    torch.save({"a": torch.zeros(1)}, p)
    with pytest.raises(ckpt.CheckpointRefused):
        ckpt.load_verified(p, hashlib.sha256(p.read_bytes()).hexdigest())  # outside evidence/howm1
    q = tmp_path / "evidence" / "howm1" / "y.pt"
    q.parent.mkdir(parents=True)
    torch.save({"a": torch.zeros(1)}, q)
    with pytest.raises(ckpt.CheckpointRefused):
        ckpt.load_verified(q, "0" * 64)
    assert "a" in ckpt.load_verified(q, hashlib.sha256(q.read_bytes()).hexdigest())


def test_T_RUN_01_02_runner_refusals(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("hbr", ROOT / "scripts" / "howm_budget_run.py")
    hbr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hbr)
    monkeypatch.setattr(hbr, "LEDGER", tmp_path / "L.jsonl")
    monkeypatch.setattr(hbr, "LOGS", tmp_path / "logs")
    hbr.genesis()
    assert hbr.run(["/usr/bin/true"], "RESERVE", "x", False) == 4
    assert hbr.run(["/usr/bin/true"], "R1.B2", "x", False) == 5  # interpreter not authorised
    recs = [json.loads(x) for x in (tmp_path / "L.jsonl").read_text().splitlines()]
    assert [r["kind"] for r in recs] == ["genesis", "refused", "refused"]
    lines = (tmp_path / "L.jsonl").read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["reason"] = "edited"
    (tmp_path / "L.jsonl").write_text("\n".join([lines[0], json.dumps(tampered), lines[2]]) + "\n")
    with pytest.raises(hbr.base.LedgerError):
        hbr.run(["/usr/bin/true"], "R1.B2", "x", False)


def test_T_V0_03_p5b_regression_one_parent(tmp_path):
    """Known P5b reserved parent (already read): v6 planner choice and U reproduced (regression only)."""
    from hospitalos.decision_support.planner import Settings
    from hospitalos.decision_support.snapshot import load_json, load_profile
    from hospitalos.p5 import p5b as B
    from hospitalos.p5.generator import generate_structure

    ex = ROOT / "evidence/decision_support/p5/p5b/P5b_eval/executions/e4f4c728a2faaa044e6b"
    ident = json.loads((ex / "RUN_IDENTITY.json").read_text())
    rec = json.loads((ex / "parents.jsonl").read_text().splitlines()[0])
    seeds = json.loads((ROOT / "evidence/decision_support/p5/SEEDS_SEALED.json").read_text())[
        "partitions"
    ]["P5b_eval"]
    profile = load_profile()
    valid, _ = generate_structure(
        "P5b_eval", seeds[rec["structure_index"]], int(ident["n_parents"]), profile, twins=True
    )
    cand = next(c for c in valid if c.parent_index == rec["parent_index"])
    out = B.evaluate_twin(
        cand.episodes["A"],
        run_dir=tmp_path,
        identity=ident,
        where={},
        profile=profile,
        score=load_json(ROOT / "configs/decision_support/PRESSURE_SCORE_CONFIG.json"),
        with_planner=True,
        settings=Settings.default(),
    )
    assert out["planner"] == rec["twins"]["A"]["planner"]
    assert out["outcomes"]["R1"]["U"] == rec["twins"]["A"]["outcomes"]["R1"]["U"]


def test_predict_many_equals_one_by_one(val_est, b0p):
    from hospitalos.howm.nets import predict_many

    torch.manual_seed(1)
    for M in (B2, H1):
        m = M(b0p)
        many = predict_many(m, val_est, [40, 60, 100, 120])
        for H, pm in zip([40, 60, 100, 120], many, strict=True):
            p1 = predict(m, val_est, H)
            assert np.allclose(p1.arr_mu, pm.arr_mu, atol=1e-6)
            assert np.allclose(p1.care_mu, pm.care_mu, atol=1e-6)
            for f in p1.delta_items:
                assert np.allclose(p1.delta_items[f], pm.delta_items[f], atol=1e-6)
            for f in p1.delta_entity:
                assert p1.delta_entity[f].keys() == pm.delta_entity[f].keys()
                assert all(
                    abs(p1.delta_entity[f][k] - pm.delta_entity[f][k]) < 1e-5
                    for k in p1.delta_entity[f]
                )


def test_h1_grouped_message_passing_equals_reference(val_est, b0p):
    torch.manual_seed(2)
    m = H1(b0p)
    with torch.no_grad():
        for p_ in (m.bf, m.br):
            p_.normal_()
    g = make_batch([(val_est, 100), (val_est, 60)], "H1")["graph"]
    h = torch.randn(g["n"], 48)
    w = m._w()
    for k in (0, 12, 23):
        assert torch.allclose(
            m._mp(h, g["edges"][k], w), m._mp_reference(h, g["edges"][k]), atol=1e-5
        )
