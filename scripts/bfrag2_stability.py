#!/usr/bin/env python3
"""B-FRAG 2 Monte-Carlo stability on DEV (PROTOCOLE s.7): risk at M = 8, 32, 128 (nested keys, two
independent repetitions) for F, O, R1 at DEV origins; planner choices at M = 8, 32 for F and O at the
decision origins, with true evaluation of the chosen actions. DEV only."""

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
EV = ROOT / "evidence/howm2_bfrag2"


def setup(s, e):
    from hospitalos.bfrag2 import core2 as C
    from hospitalos.howm.world import TPH

    w = C.structure("BF2_DEV", s, json.loads((ROOT / "docs/howm2/bfrag/DESIGN_D2.json").read_text()))
    spec_e = C.episode_spec(w, e)
    ep, trace = C.generate2(spec_e, [h * TPH for h in C.ORIGIN_HOURS])
    return C, w, spec_e, ep, trace


def risk_job(arg):
    s, e, h, method = arg
    from hospitalos.howm.b0 import B0Params
    from hospitalos.howm.world import TPH

    C, w, spec_e, ep, trace = setup(s, e)
    t0 = h * TPH
    pub, ps, pe = C.public_state(ep, t0)
    p = B0Params.from_json(json.loads((ROOT / "evidence/howm1/B0_PARAMS.json").read_text()))
    active = C.labels_at(C.rupture_runs(trace), t0, len(trace))["active"]
    flags = {}
    t = time.time()
    for rep in (0, 1):
        if method == "F":
            pairs = C.f_pairs(w, pub, ps, pe, t0, 128, rep)
        elif method == "O":
            pairs = C.o_pairs(w, spec_e, ep, t0, 128, rep)
        else:
            pairs = C.r1_pairs(w, pub, ps, pe, t0, p, 128, rep)
        flags[rep] = [int(C.rollout_sched(en, pv, None, w.drop, C.WINDOW_H)["rupture"]) for en, pv in pairs]
    return {"s": s, "e": e, "h": h, "method": method, "active": active, "flags": flags, "seconds": time.time() - t}


def dec_job(arg):
    s, e, method = arg
    from hospitalos.howm.world import TPH

    C, w, spec_e, ep, trace = setup(s, e)
    hd = C.DECISION_HOURS[e % 3]
    t0 = hd * TPH
    pub, ps, pe = C.public_state(ep, t0)
    acts = C.catalogue(t0)
    t = time.time()
    res = {}
    for rep in (0, 1):
        pairs = C.f_pairs(w, pub, ps, pe, t0, 32, rep) if method == "F" else C.o_pairs(w, spec_e, ep, t0, 32, rep)
        loss = np.array([[C.rollout_sched(en, pv, a["plan"], w.drop, 168, a["extra"])["wait_patient_min"] for a in acts] for en, pv in pairs])
        res[rep] = {M: int(min(range(len(acts)), key=lambda i, M=M: (round(float(loss[:M, i].mean()), 6), acts[i]["staff_hours"], i))) for M in (8, 32)}
    ev = C.evaluate_actions(w, spec_e, ep, t0, acts, 8)
    evl = [float(np.mean([x["wait_patient_min"] for x in rows])) for rows in ev]
    return {"s": s, "e": e, "method": method, "choices": res, "eval_loss": evl, "seconds": time.time() - t}


def main() -> int:
    risk_args = [(s, 0, h, m) for s in (1, 2) for h in (42, 60, 78, 96, 114) for m in ("F", "O", "R1")]
    dec_args = [(s, e, m) for s, e in ((1, 0), (2, 1)) for m in ("F", "O")]
    with get_context("fork").Pool(4, maxtasksperchild=1) as pool:
        risks = pool.map(risk_job, risk_args)
        decs = pool.map(dec_job, dec_args)
    out = {"risk": {}, "decision": {}, "raw_risk": risks, "raw_decision": decs}
    for m in ("F", "O", "R1"):
        rows = [r for r in risks if r["method"] == m and not r["active"]]
        out["risk"][m] = {}
        for M in (8, 32, 128):
            p0 = np.array([np.mean(r["flags"][0][:M]) for r in rows])
            p1 = np.array([np.mean(r["flags"][1][:M]) for r in rows])
            from scipy.stats import spearmanr

            rho = float(spearmanr(p0, p1).statistic) if len(rows) > 2 and p0.std() > 0 and p1.std() > 0 else None
            out["risk"][m][str(M)] = {"n_origins": len(rows), "mean_abs_diff": float(np.mean(np.abs(p0 - p1))), "spearman": rho,
                                      "rank_agreement_note": "between two independent repetitions"}
        out["risk"][m]["seconds_per_origin_M128_x2"] = float(np.mean([r["seconds"] for r in rows])) if rows else None
    for m in ("F", "O"):
        rows = [d for d in decs if d["method"] == m]
        out["decision"][m] = {}
        for M in ("8", "32"):
            agree = [d["choices"][0][int(M)] == d["choices"][1][int(M)] for d in rows]
            regret = [abs(d["eval_loss"][d["choices"][0][int(M)]] - d["eval_loss"][d["choices"][1][int(M)]]) / d["eval_loss"][0] for d in rows]
            out["decision"][m][M] = {"agreement": float(np.mean(agree)), "mean_rel_regret_between_reps": float(np.mean(regret)), "n": len(rows)}
    (EV / "MC_STABILITY_DEV.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"risk": out["risk"], "decision": out["decision"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
