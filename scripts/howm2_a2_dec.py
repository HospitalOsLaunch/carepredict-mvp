#!/usr/bin/env python3
"""HOWM-2 A2.DEC (NORM A2 N3, addendum A2-1 s.4, addendum A2-2): decision value of L4-N.

    run --part VAL|HOWM2_REF     (12 establishments x 4 instants each; one JSON per establishment)
    analyse                      (verdict, kappa, pure-min diagnostic)
"""

from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

import json  # noqa: E402
import sys  # noqa: E402
from dataclasses import replace  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "evidence/howm2/a2_dec"
M = 8


def job(arg):
    part, i = arg
    from howm2_decision import sample_world
    from howm_eval import strengthened_rule

    from hospitalos.howm import generator as G
    from hospitalos.howm.controllers import CHOICE_R, EVAL_R, obj_lex, prior_spec, truth_u
    from hospitalos.howm.generator import stationary_regime, true_regime_at
    from hospitalos.howm.rollout import rollout
    from hospitalos.howm.world import candidates
    from hospitalos.howm2 import a2, space

    space.register()
    plans = candidates()
    pre = None
    if part == "VAL":
        pre = {ins["tau"]: ins for ins in json.loads((ROOT / f"evidence/howm1/precheck/VAL_{i:03d}.json").read_text())["instants"]}
    rows = []
    for ins in a2.setup(part, i):
        tau, spec, ep, peng = ins.tau, ins.spec, ins.ep, ins.peng
        true_eng = ep.instants[tau]
        anchor_true = true_regime_at(ep, tau)
        cu_full = np.array([truth_u(true_eng, spec, r, anchor_true, plans) for r in CHOICE_R]).mean(0)
        if pre is not None:
            p = pre[tau]
            eval_u = np.array(p["eval_u"])
            oracle = p["oracle_U_star"]
            vals = {"C_full": p["value"]["C_full"], "C_param": p["value"]["C_param"], "C_pub_snap": p["value"]["C_pub_snap"]}
            assert int(obj_lex(list(cu_full))) == int(np.argmin(np.abs(eval_u.mean(0) - vals["C_full"]))) or abs(eval_u[:, obj_lex(list(cu_full))].mean() - vals["C_full"]) < 1e-9
        else:
            eval_u = np.array([truth_u(true_eng, spec, r, anchor_true, plans) for r in EVAL_R])
            oracle = float(np.mean(eval_u.min(axis=1)))
            cp = np.array([truth_u(peng, spec, r, stationary_regime(spec, r, tau), plans) for r in CHOICE_R]).mean(0)
            ps_ = prior_spec(spec)
            cs = np.array([truth_u(peng, ps_, r, stationary_regime(ps_, r, tau), plans) for r in CHOICE_R]).mean(0)
            vals = {"C_full": float(eval_u[:, obj_lex(list(cu_full))].mean()),
                    "C_param": float(eval_u[:, obj_lex(list(cp))].mean()),
                    "C_pub_snap": float(eval_u[:, obj_lex(list(cs))].mean())}
        seed = int(G.u(spec.ekey, 0, "howm2-dec", tau) * 2**31)
        rng4, rngn = np.random.default_rng(seed), np.random.default_rng(seed)
        u4, un, n_pend, rej, fb = [], [], [], 0, 0
        for m in range(M):
            th, mech, anchor = sample_world(ins.lad, ins.ctx, rng4)
            s2 = replace(spec, theta=th, mech=mech)
            prov = G.TruthProvider(s2, 201 + m, theta=th, regime_anchor=anchor)
            u4.append([rollout(peng, prov, p)["U"] for p in plans])
            thn, mechn, anchorn, s2n, provn, engn, applied = a2.l4n_draw(ins, rngn, 201 + m)
            assert thn == th
            n_pend.append(len(applied))
            fb += provn.fallbacks
            rej += engn.rejected - peng.rejected
            prov2 = G.TruthProvider(s2n, 201 + m, theta=thn, regime_anchor=anchorn)
            res = [rollout(engn, prov2, p) for p in plans]
            rej += sum(r["rejected"] - peng.rejected for r in res) * 0
            un.append([r["U"] for r in res])
        mu4, mun = np.array(u4).mean(0), np.array(un).mean(0)
        c4, cn = obj_lex(list(mu4)), obj_lex(list(mun))
        rule = strengthened_rule(peng)
        ev = lambda c: float(eval_u[:, c].mean())  # noqa: E731
        rows.append({
            "part": part, "index": i, "tau": tau,
            "U_habitual": ev(0), "U_rule": ev(rule), "U_L4": ev(c4), "U_L4N": ev(cn),
            "U_C_full": vals["C_full"], "U_C_param": vals["C_param"], "U_C_pub_snap": vals["C_pub_snap"], "U_oracle": oracle,
            "choice": {"L4": int(c4), "L4N": int(cn), "rule": int(rule), "C_full": int(obj_lex(list(cu_full)))},
            "pure_min": {"L4": ev(int(np.argmin(mu4))), "L4N": ev(int(np.argmin(mun))), "C_full": ev(int(np.argmin(cu_full)))},
            "pending_applied_per_draw": n_pend, "nowcast_fallbacks": fb, "nowcast_rejected": rej,
        })
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{part}_{i:03d}.json").write_text(json.dumps(rows, indent=1) + "\n")
    return len(rows)


def boot(rows, f, seed, B=2000, ratio=None):
    by = {}
    for r in rows:
        by.setdefault((r["part"], r["index"]), []).append(r)
    groups = list(by.values())
    rng = np.random.default_rng(seed)

    def stat(rs):
        if ratio:
            num, den = ratio
            return float(np.mean([num(r) for r in rs]) / np.mean([den(r) for r in rs]))
        return float(np.mean([f(r) for r in rs]))

    reps = [stat([r for j in rng.integers(0, len(groups), len(groups)) for r in groups[j]]) for _ in range(B)]
    return {"estimate": stat(rows), "ci95": [float(np.quantile(reps, 0.025)), float(np.quantile(reps, 0.975))], "n_instants": len(rows), "n_clusters": len(groups)}


def analyse() -> int:
    from hospitalos.howm.keys import key

    rows = [r for f in sorted(OUT.glob("*.json")) for r in json.loads(f.read_text())]
    seed = int(key("HOWM2", "A2", "bootstrap") % (2**31))
    mg = lambda r: r["U_rule"] - r["U_L4N"]  # noqa: E731
    main_ = boot(rows, mg, seed)
    lo, hi = main_["ci95"]
    verdict = "NOWCAST_MARGE_GE_15" if lo >= 15 else ("NOWCAST_MARGE_LT_15" if hi < 15 else "NOWCAST_INDETERMINE")
    a_dec = {(r["index"], r["tau"]): r for r in json.loads((ROOT / "evidence/howm2/DECISION_A.json").read_text())["rows"]}
    repro = [abs(r["U_L4"] - a_dec[(r["index"], r["tau"])]["U_L4"]) < 1e-9 for r in rows if r["part"] == "VAL"]
    out = {
        "verdict": verdict,
        "flag": "L4-N validation: N-o' not passed (test limitation, L5-N fails too; addendum A2-2)",
        "margin_N_rule_minus_L4N": main_,
        "margin_N_VAL": boot([r for r in rows if r["part"] == "VAL"], mg, seed),
        "margin_N_new_REF": boot([r for r in rows if r["part"] == "HOWM2_REF"], mg, seed),
        "margin_A_rule_minus_L4_all96": boot(rows, lambda r: r["U_rule"] - r["U_L4"], seed),
        "L4_minus_L4N_paired": boot(rows, lambda r: r["U_L4"] - r["U_L4N"], seed),
        "L4_minus_C_full": boot(rows, lambda r: r["U_L4"] - r["U_C_full"], seed),
        "kappa": boot(rows, None, seed, ratio=(lambda r: r["U_L4"] - r["U_L4N"], lambda r: r["U_L4"] - r["U_C_full"])),
        "means": {k: float(np.mean([r[k] for r in rows])) for k in ("U_habitual", "U_rule", "U_L4", "U_L4N", "U_C_param", "U_C_pub_snap", "U_C_full", "U_oracle")},
        "means_by_part": {p: {k: float(np.mean([r[k] for r in rows if r["part"] == p])) for k in ("U_habitual", "U_rule", "U_L4", "U_L4N", "U_C_param", "U_C_pub_snap", "U_C_full", "U_oracle")} for p in ("VAL", "HOWM2_REF")},
        "secondary_pure_min": {
            "means": {s: float(np.mean([r["pure_min"][s] for r in rows])) for s in ("L4", "L4N", "C_full")},
            "rule_minus_L4_pure": boot(rows, lambda r: r["U_rule"] - r["pure_min"]["L4"], seed),
            "rule_minus_L4N_pure": boot(rows, lambda r: r["U_rule"] - r["pure_min"]["L4N"], seed),
            "C_full_objlex_minus_pure": boot(rows, lambda r: r["U_C_full"] - r["pure_min"]["C_full"], seed),
            "note": "pre-declared diagnostic, no effect on the verdict; rule unchanged",
        },
        "choices_differ_L4_vs_L4N": int(sum(r["choice"]["L4"] != r["choice"]["L4N"] for r in rows)),
        "pending_events_applied_mean_per_draw": float(np.mean([x for r in rows for x in r["pending_applied_per_draw"]])),
        "nowcast_fallbacks": int(sum(r["nowcast_fallbacks"] for r in rows)),
        "nowcast_rejected": int(sum(r["nowcast_rejected"] for r in rows)),
        "VAL_L4_reproduces_A": {"checked": len(repro), "identical": int(sum(repro))},
    }
    (ROOT / "evidence/howm2/DECISION_A2.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


def main() -> int:
    if sys.argv[1] == "analyse":
        return analyse()
    part = sys.argv[sys.argv.index("--part") + 1]
    todo = [(part, i) for i in range(12) if not (OUT / f"{part}_{i:03d}.json").exists()]
    with get_context("fork").Pool(4) as pool:
        print(sum(pool.map(job, todo)), "instants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
