#!/usr/bin/env python3
"""Decision n.8 s.4: targeted numerical check of the calendar-corrected B-FRAG 2 version on DEV
(panel pre-declared in STAB_PREDECLARED.json). Also lists Mr/Md/E recorded in every B-FRAG 2 run file."""

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import collections  # noqa: E402
import glob  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "evidence/howm2_bfrag2w"


def job(item):
    from hospitalos.bfrag import core as K
    from hospitalos.bfrag2 import core2 as C
    from hospitalos.howm import generator as G
    from hospitalos.howm.b0 import B0Params
    from hospitalos.howm.world import TPH

    t_all = time.time()
    w = C.structure(item["part"], item["structure"], json.loads((ROOT / "docs/howm2/bfrag/DESIGN_D2.json").read_text()))
    e = item["episode"]
    spec_e = C.episode_spec(w, e)
    hd = C.DECISION_HOURS[e % 3]
    assert hd == item["decision_hour"]
    t0 = hd * TPH
    ep, _tr = C.generate2(spec_e, [t0], w.drop)
    pub, ps, pe = C.public_state(ep, t0)
    acts = C.catalogue(t0)
    p = B0Params.from_json(json.loads((ROOT / "evidence/howm1/B0_PARAMS.json").read_text()))
    out = {**item, "actions": [a["id"] for a in acts], "methods": {}}
    for meth in ("F", "R1"):
        reps = {}
        for rep in (0, 1):
            ts = time.time()
            pairs = C.f_pairs(w, pub, ps, pe, t0, 32, rep) if meth == "F" else C.r1_pairs(w, pub, ps, pe, t0, p, 32, rep)
            L = np.array([[C.rollout_sched(en, pv, a["plan"], w.drop, 168, a["extra"])["wait_patient_min"] for a in acts] for en, pv in pairs])
            reps[rep] = {"choice": {M: int(min(range(len(acts)), key=lambda i, M=M: (round(float(L[:M, i].mean()), 6), acts[i]["staff_hours"], i)))
                                    for M in (8, 16, 32)}, "mean_loss_32": L.mean(0).tolist(), "seconds": time.time() - ts}
        out["methods"][meth] = reps
    anchor = G.true_regime_at(ep, t0)
    ev = {}
    for name, rr in (("A", range(1, 9)), ("B", range(9, 17))):
        ev[name] = [float(np.mean([C.rollout_sched(ep.instants[t0], K.bf_provider(spec_e, r, w.nominal, regime_anchor=anchor), a["plan"], w.drop, 168,
                                                   a["extra"])["wait_patient_min"] for r in rr])) for a in acts]
    out["eval"] = ev
    out["seconds"] = time.time() - t_all
    return out


def recorded_params():
    res = {}
    for f in glob.glob(str(ROOT / "evidence/howm2_bfrag2/runs/*/*/s*_e*.json")):
        d = json.loads(Path(f).read_text())
        tag, part = Path(f).parts[-3], Path(f).parts[-2]
        res.setdefault(f"{tag}/{part}", collections.Counter())[(d["mode"], d["Mr"], d["Md"], d["E"])] += 1
    return {k: [{"mode": m, "Mr_risk": a, "Md_decision": b, "E_eval": c, "files": n,
                 "used": {"risk": m in ("full", "val"), "R1_planner": m in ("full", "val"), "F_O_planners": m == "full", "eval": m in ("full", "val")}}
                for (m, a, b, c), n in v.items()] for k, v in sorted(res.items())}


def main() -> int:
    pre = json.loads((OUT / "STAB_PREDECLARED.json").read_text())
    with get_context("fork").Pool(4, maxtasksperchild=1) as pool:
        rows = pool.map(job, pre["panel"])
    summ = {"F": {}, "R1": {}}
    for meth in ("F", "R1"):
        for M in ("8", "16", "32"):
            agree = [r["methods"][meth][0]["choice"][int(M)] == r["methods"][meth][1]["choice"][int(M)] for r in rows]
            reg = [abs(r["eval"]["A"][r["methods"][meth][0]["choice"][int(M)]] - r["eval"]["A"][r["methods"][meth][1]["choice"][int(M)]]) / r["eval"]["A"][0]
                   for r in rows]
            summ[meth][M] = {"choice_agreement": float(np.mean(agree)), "rel_regret_mean": float(np.mean(reg)), "rel_regret_max": float(np.max(reg)),
                             "tolerance_0.005_met": bool(max(reg) <= 0.005)}
    from scipy.stats import spearmanr

    evs = []
    for r in rows:
        A, B = np.array(r["eval"]["A"]), np.array(r["eval"]["B"])
        fc, rc = r["methods"]["F"][0]["choice"][32], r["methods"]["R1"][0]["choice"][32]
        evs.append({"structure": r["structure"], "gain_F_vs_R1_A": float(A[rc] - A[fc]), "gain_F_vs_R1_B": float(B[rc] - B[fc]),
                    "best_A": int(A.argmin()), "best_B": int(B.argmin()), "gain_bestA_vs_none_A": float(A[0] - A.min()),
                    "gain_bestA_vs_none_B": float(B[0] - B[A.argmin()]), "spearman_A_B": float(spearmanr(A, B).statistic),
                    "none_A": float(A[0]), "none_B": float(B[0])})
    keep = all(summ[m]["32"]["tolerance_0.005_met"] for m in ("F", "R1"))
    out = {"predeclared": "STAB_PREDECLARED.json", "panel_results": rows, "decision_stability": summ, "evaluation_stability": evs,
           "rule_outcome": {"keep_Md_32": True, "tolerance_met_at_32": keep,
                            "F_R1_exact_decision_reference": False if not keep else "not claimed (stability only)"},
           "recorded_parameters": recorded_params()}
    (OUT / "VERIF_NUM_DEV.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"decision_stability": summ, "evaluation_stability": evs, "rule_outcome": out["rule_outcome"],
                      "seconds": [round(r["seconds"]) for r in rows]}, indent=1))
    print(json.dumps(out["recorded_parameters"], indent=0)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
