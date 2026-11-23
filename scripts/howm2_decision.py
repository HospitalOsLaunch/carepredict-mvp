#!/usr/bin/env python3
"""HOWM-2 A4 decision margin on the 48 VAL instants (NORM A4).

The R1 planner (16 candidates, OBJ-LEX-1) is fed by the L4 posterior: each of M = 8 trajectories
draws (theta, mechanism, regime at tau) from L4 and simulates with the generator structure from the
PUBLIC engine (choice keys r = 201..208, disjoint from evaluation). Evaluation reuses the HOWM-1
precheck evaluation U (4 realisations x 16 candidates). Margin = U(strengthened rule) - U(L4 planner).
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
M = 8
INSTANTS = (7, 11, 15, 19)


def sample_world(lad, ctx, rng):
    """One draw of (theta, mech, regime anchor at tau) from the L4 posterior."""
    from hospitalos.howm2.filter import mech_types

    types = ctx["types"]
    ti = int(rng.choice(len(types), p=ctx["type_w"]))
    name, _p, m2, kap = types[ti]
    g = lad.g
    th = {}

    def pick(w):
        w = np.asarray(w, float)
        return int(rng.choice(len(w), p=w / w.sum()))

    reg = ctx["reg"]
    H = None
    anchor = {}
    if lad.pop == "DIAG":
        J = reg["joint"]
        n1, n2 = J["shape"]
        lz = J["logZ"]
        w = np.exp(lz - lz.max())
        k = pick(w)
        i1, i2 = divmod(k, n2)
        th["tr_min"], th["cl_min"] = float(g["tr"][i1]), float(g["cl"][i2])
        H = J["post_slow"].shape[0] - 1
        anchor["common"] = (H, int(rng.random() < J["post_slow"][H, k]))
    else:
        for f, key, gk in (("transport", "tr_min", "tr"), ("cleaning", "cl_min", "cl")):
            lz = reg[f]["on" if m2 else "off"]
            i = pick(np.exp(lz - lz.max()))
            th[key] = float(g[gk][i])
            H = reg[f]["post_slow"].shape[0] - 1
            anchor[f] = (H, int(rng.random() < reg[f]["post_slow"][H, i]) if m2 else 0)
    th["ready_h"] = float(g["ready"][pick(ctx["ready_post"][lad.kappas.index(kap)])])
    th["conf_tr_min"] = float(g["conf_tr"][pick(ctx["conf_post"]["conf_tr"])])
    th["conf_off_min"] = float(g["conf_off"][pick(ctx["conf_post"]["conf_off"])])
    th["care_mult"] = float(g["care"][pick(ctx["care_post"])])
    th["noshow"] = float(g["noshow"][pick(ctx["pres_post"])])
    th["lag_min"] = float(g["lag"][pick(ctx["lag_w"])])
    w, L, A = ctx["arr_post"]
    k = pick(w.reshape(-1))
    th["los_days"], th["arr_mult"] = float(L.reshape(-1)[k]), float(A.reshape(-1)[k])
    mech = {
        "m2": bool(m2),
        "m2_common": lad.pop == "DIAG",
        "slow": 1.8 if lad.pop == "REF" else 2.5,
        "m3_kappa": float(kap),
        "m5_drop": lad.pop == "DIAG",
        "simple": name == "simple",
    }
    _ = mech_types
    return th, mech, anchor


def job(i):
    from howm_eval import strengthened_rule

    from hospitalos.howm import generator as G
    from hospitalos.howm.controllers import obj_lex
    from hospitalos.howm.history import PublicStream
    from hospitalos.howm.rollout import rollout
    from hospitalos.howm.world import candidates
    from hospitalos.howm2.filter import Ladder, PublicState

    spec = G.establishment("VAL", i)
    ep = G.generate(spec)
    pre = json.loads((ROOT / f"evidence/howm1/precheck/VAL_{i:03d}.json").read_text())
    static = next(o[5] for o in ep.observations if o[2] == "static")
    plans = candidates()
    rows = []
    for ins in pre["instants"]:
        tau = ins["tau"]
        t = tau * 15
        ps = PublicStream(ep.observations)
        ps.advance(t)
        peng = ps.to_engine(t)
        lad = Ladder(spec.population, static, dict(spec.beds), None)
        pub = PublicState(spec.population, dict(spec.beds))
        pub.ingest(ps.obs[: ps.i])
        ctx = lad.context(pub, ps, t)
        rng = np.random.default_rng(int(G.u(spec.ekey, 0, "howm2-dec", tau) * 2**31))
        us = []
        for m in range(M):
            th, mech, anchor = sample_world(lad, ctx, rng)
            s2 = replace(spec, theta=th, mech=mech)
            prov = G.TruthProvider(s2, 201 + m, theta=th, regime_anchor=anchor)
            us.append([rollout(peng, prov, p)["U"] for p in plans])
        us = np.array(us)
        mean_u = us.mean(0)
        choice = obj_lex(list(mean_u))
        ev = np.array(ins["eval_u"])
        rule = strengthened_rule(peng)
        order = np.argsort(mean_u)
        a, b = order[0], order[1]
        diff = us[:, b] - us[:, a]
        se_pair = diff.std(ddof=1) / np.sqrt(M)
        rows.append(
            {
                "index": i,
                "tau": tau,
                "L4_choice": int(choice),
                "rule_choice": int(rule),
                "U_L4": float(ev[:, choice].mean()),
                "U_rule": float(ev[:, rule].mean()),
                "U_C_full": ins["value"]["C_full"],
                "U_habitual": ins["value"]["habitual"],
                "U_oracle": ins["oracle_U_star"],
                "top2_gap": float(mean_u[b] - mean_u[a]),
                "paired_se": float(se_pair),
                "dnk_old": bool(mean_u[b] - mean_u[a] < us[:, a].std() / np.sqrt(M)),
                "dnk_new": bool(mean_u[b] - mean_u[a] < 1.96 * se_pair),
            }
        )
    return rows


def main() -> int:
    from hospitalos.howm.keys import key

    with get_context("fork").Pool(4) as pool:
        rows = [r for rs in pool.map(job, range(12)) for r in rs]
    seed = int(key("HOWM2", "bootstrap") % (2**31))
    rng = np.random.default_rng(seed)
    by = {}
    for r in rows:
        by.setdefault(r["index"], []).append(r["U_rule"] - r["U_L4"])
    est = np.array([np.mean(v) for v in by.values()])
    bs = [est[rng.integers(0, len(est), len(est))].mean() for _ in range(2000)]
    margin = float(np.mean([r["U_rule"] - r["U_L4"] for r in rows]))
    out = {
        "n_instants": len(rows),
        "margin_rule_minus_L4": margin,
        "ci95": [float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))],
        "verdict": "MARGE_DECISIONNELLE_GE_15" if margin >= 15 else "MARGE_DECISIONNELLE_LT_15",
        "means": {
            k: float(np.mean([r[k] for r in rows]))
            for k in ("U_L4", "U_rule", "U_C_full", "U_habitual", "U_oracle")
        },
        "gain_vs_habitual": {
            k: float(np.mean([r["U_habitual"] - r[k] for r in rows]))
            for k in ("U_L4", "U_rule", "U_C_full", "U_oracle")
        },
        "does_not_know": {
            "old_definition_rate": float(np.mean([r["dnk_old"] for r in rows])),
            "proposed_paired_definition_rate": float(np.mean([r["dnk_new"] for r in rows])),
            "note": "proposed: top-2 gap < 1.96 x SE of the PAIRED difference (CRN); not applied to delivered R1 results",
        },
        "rows": rows,
    }
    (ROOT / "evidence/howm2/DECISION_A.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
