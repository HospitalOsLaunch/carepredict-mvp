#!/usr/bin/env python3
"""Decision n.8 pilot: analysis of the single final evaluation campaign (frozen in FREEZE_PILOT.json before
the campaign). Primary: W - D decision gain (paired 95 % CI, cluster bootstrap over structures). Everything
else descriptive. Writes evidence/howm2_bfrag2w/RESULTS_PILOT_W.json."""

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import glob  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import bf2w_models as M  # noqa: E402
import bfrag2_lib as L  # noqa: E402

EV = ROOT / "evidence/howm2_bfrag2w"
GUARD = ("uncovered_care_min", "rejected_total", "rupture_minutes", "terminal_queue", "terminal_max_wait_min")
MIN_STRUCT = 10


def feasible(recs, n_planned):
    by = {}
    for r in recs:
        by.setdefault(r["structure"], []).append(r)
    keep = []
    for s in range(n_planned):
        if len(by.get(s, [])) == 3:
            keep.append(s)
        else:
            break
    return [r for r in recs if r["structure"] in keep], keep


def per_struct(recs, fn):
    by = {}
    for r in recs:
        by.setdefault(r["structure"], []).append(fn(r))
    return {s: float(np.mean(v)) for s, v in by.items()}


def main() -> int:
    from scipy.stats import spearmanr

    fr = json.loads((EV / "FREEZE_PILOT.json").read_text())
    recs_all = [json.loads(Path(f).read_text()) for f in sorted(glob.glob(str(EV / "runs/eval/*.json")))]
    recs, kept = feasible(recs_all, fr["eval_structures"])
    res = {"planned_structures": fr["eval_structures"], "kept_structures": kept, "decisions": len(recs), "E": fr["E"], "Md": fr["Md"]}
    if len(kept) < MIN_STRUCT:
        res["status"] = "VALIDATION_FINALE_NON_EXECUTEE"
        (EV / "RESULTS_PILOT_W.json").write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps(res))
        return 0
    res["status"] = "EVALUATION_FINALE_EXECUTEE"
    for r in recs:
        r["L"] = np.array([np.mean([x["wait_patient_min"] for x in row]) for row in r["eval"]])
    pol = {"none": lambda r: 0, "historical": lambda r: 1,
           "R1": lambda r: r["R1_planner"]["choice"], "F": lambda r: r["F_planner"]["choice"],
           "D": lambda r: M.choose(r["pred"]["D"], r["actions"]), "W": lambda r: M.choose(r["pred"]["W"], r["actions"])}
    for i in range(len(fr["W_seeds"])):
        pol[f"W_seed{fr['W_seeds'][i]}"] = lambda r, i=i: M.choose(r["pred"]["W_seeds"][i], r["actions"])
    loss = {k: per_struct(recs, lambda r, f=f: r["L"][f(r)]) for k, f in pol.items()}
    loss["expost_min (retrospective diagnostic)"] = per_struct(recs, lambda r: r["L"].min())
    res["mean_loss"] = {k: float(np.mean(list(v.values()))) for k, v in loss.items()}
    d = {s: loss["D"][s] - loss["W"][s] for s in loss["D"]}
    prim = L.mean_diff_ci(d, 0.05)
    prim["definition"] = "attente(choix D) - attente(choix W), moyenne par structure; > 0 = W meilleur"
    lo, hi = prim["ci"]
    res["primary_W_vs_D"] = prim
    res["verdict"] = "GAIN_W" if lo > 0 else ("W_INFERIEUR" if hi < 0 else "INDETERMINE")
    sec = {}
    for a, b in (("R1", "W"), ("historical", "W"), ("F", "W"), ("none", "W"), ("F", "D"), ("R1", "D"), ("R1", "F"), ("historical", "F"),
                 ("D", "W_seed0"), ("D", "W_seed1"), ("D", "W_seed2")):
        if a in loss and b in loss:
            sec[f"{a}-{b}"] = L.mean_diff_ci({s: loss[a][s] - loss[b][s] for s in loss[a]}, 0.05)
    res["secondary_differences_95"] = sec
    res["choices"] = {k: [int(f(r)) for r in recs] for k, f in pol.items()}
    res["choice_agreement_W_D"] = float(np.mean([pol["W"](r) == pol["D"](r) for r in recs]))
    # guardrails W - D
    g = {}
    for m in GUARD + ("share_A",):
        def met(r, k, m=m):
            rows = r["eval"][k]
            if m == "share_A":
                return float(np.mean([x["wait_by_unit"]["A"] / max(1e-9, x["wait_patient_min"]) for x in rows]))
            return float(np.mean([float(x[m]) for x in rows]))
        g[m] = L.mean_diff_ci(per_struct(recs, lambda r, met=met: met(r, pol["W"](r)) - met(r, pol["D"](r))), 0.05)
    g["staff_hours_mean"] = {k: float(np.mean([r["actions"][f(r)]["staff_hours"] for r in recs])) for k, f in pol.items()}
    res["guardrails_W_minus_D_95"] = g
    # action-effect errors and ranking
    pv = {"D": lambda r: np.array(r["pred"]["D"]), "W": lambda r: np.array(r["pred"]["W"]),
          "F": lambda r: np.array(r["F_planner"]["mean_loss"]), "R1": lambda r: np.array(r["R1_planner"]["mean_loss"])}
    for i, s in enumerate(fr["W_seeds"]):
        pv[f"W_seed{s}"] = lambda r, i=i: np.array(r["pred"]["W_seeds"][i])
    eff = {}
    for k, f in pv.items():
        err, rho, top = [], [], []
        for r in recs:
            p, t = f(r), r["L"]
            err.append(((p - p[0]) - (t - t[0]))[1:])
            rr = spearmanr(p, t).statistic
            rho.append(0.0 if np.isnan(rr) else rr)
            top.append(t[int(np.argmin(p))] - t.min())
        eff[k] = {"effect_rmse": float(np.sqrt(np.mean(np.concatenate(err) ** 2))), "spearman_mean": float(np.mean(rho)),
                  "regret_vs_expost_min_mean": float(np.mean(top))}
    res["action_effects"] = eff
    # W trajectory quality and constraint violations (ensemble mean of seeds, standardised by TRAIN scale)
    import torch

    nets = [M.load_w(s) for s in fr["W_seeds"]]
    occ_idx = [0, 14]  # A_occ, B_occ in the s1_features order (14 variables per unit, then tr_busy, cl_busy)
    se, viol_neg, viol_occ, n_val = [], 0, 0, 0
    tw = []
    for r in recs:
        t0 = time.time()
        U = torch.tensor(M.schedules(r), dtype=torch.float32)
        Ss = []
        for net, norm in nets:
            x0 = torch.tensor(((M.xvec(r) - norm["x_mu"]) / norm["x_sd"])[None].repeat(len(r["actions"]), 0), dtype=torch.float32)
            with torch.no_grad():
                s, _c = net(x0, U)
            Ss.append(s.numpy() * norm["s_sd"] + norm["s_mu"])
        tw.append(time.time() - t0)
        Sp = np.mean(Ss, 0)  # [10, 84, 30]
        for k in range(len(r["actions"])):
            true = np.mean([x["states_every_24h"] for x in r["eval"][k]], 0)  # [7, 30]
            pred = Sp[k, 11::12]
            se.append(((pred - true) / nets[0][1]["s_sd"]) ** 2)
            viol_neg += int((Sp[k] < -1e-6).sum())
            viol_occ += int((Sp[k][:, occ_idx] > 1 + 1e-6).sum())
            n_val += Sp[k].size
    se = np.array(se)  # [n, 7, 30]
    res["W_trajectories"] = {"standardised_rmse_overall": float(np.sqrt(se.mean())),
                             "standardised_rmse_by_day": np.sqrt(se.mean((0, 2))).tolist(),
                             "violations": {"negative_values": viol_neg, "occupancy_above_1": viol_occ, "values_checked": n_val,
                                            "projection": "none (violations reported as is)"}}
    tm = {k: float(np.mean([r["timing_s"][k] for r in recs])) for k in ("D_W_predict", "plan_R1", "plan_F", "evaluate")}
    tm["W_ensemble_state_rollout_reanalysis"] = float(np.mean(tw))
    lw = json.loads((EV / "LEARN_W.json").read_text())
    ld = json.loads((EV / "LEARN_D.json").read_text())
    res["costs"] = {"response_seconds_per_decision": tm, "W_training_seconds_per_seed": [x["seconds"] for x in lw],
                    "W_params": lw[0]["n_params"], "W_selected_epochs": [x["selected_epoch"] for x in lw],
                    "D_fit_seconds_selected": ld["configs"][fr["D_selected"]]["fit_seconds"],
                    "training_data": {"origins": ld["train_origins"], "trajectories": ld["train_origins"] * 10 * 2, "generation_ledger": "#137 (153.3 s wall, 568.8 s CPU)"}}
    fam = {}
    for r in recs:
        fam.setdefault(r["family"], []).append({k: float(r["L"][f(r)]) for k, f in pol.items()})
    res["by_family_mean_loss"] = {f: {k: float(np.mean([x[k] for x in v])) for k in pol} for f, v in fam.items()}
    (EV / "RESULTS_PILOT_W.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    print(json.dumps({k: res[k] for k in ("status", "kept_structures", "primary_W_vs_D", "verdict", "mean_loss", "choice_agreement_W_D")}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
