#!/usr/bin/env python3
"""B-FRAG 2 CONF analysis (PROTOCOLE_BFRAG2 s.10), frozen before the CONF campaign (freeze 2).
Questions A (history), B (F vs best public reference), C (deferred interventions), D (NOT TESTED),
propagation controls. Reads VAL selections, learned models and CONF runs; writes RESULTS_BFRAG2_CONF.json."""

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import json  # noqa: E402
import pickle  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bfrag2_lib as L  # noqa: E402

EV = L.ROOT / "evidence/howm2_bfrag2"
AP = L.ALPHA_PRIMARY
CONF_S_N = 24
MIN_CONF_S = 12
GUARDRAILS = ("uncovered_care_min", "rejected_total", "rupture_minutes", "terminal_queue")
DESCRIPTIVE = ("terminal_max_wait_min", "rejected_at_plan", "share_A")


def model(view, cfg):
    return pickle.loads((EV / "models" / f"{view}_{cfg}.pkl").read_bytes())


def feasible_conf_s(eps):
    by = {}
    for ep in eps:
        by.setdefault(ep["structure"], []).append(ep)
    keep = []
    for s in range(CONF_S_N):
        if len(by.get(s, [])) == 3:
            keep.append(s)
        else:
            break
    return [ep for ep in eps if ep["structure"] in keep], keep


def per_struct(eps, fn):
    by = {}
    for ep in eps:
        by.setdefault(ep["structure"], []).append(fn(ep))
    return {s: float(np.mean(v)) for s, v in by.items()}


def main() -> int:
    sel = json.loads((EV / "SELECTION_VAL.json").read_text())
    learn = json.loads((EV / "LEARN.json").read_text())
    names, best, common = learn["feature_names"], learn["best_per_view"], learn["common_config_A"]
    cs_all = L.load("S", "BF2_CONF")
    cs, kept = feasible_conf_s(cs_all)
    cf = L.load("F", "BF2_CONF")
    s_in_cs = {ep["structure"] for ep in cs}
    allc = cs + [ep for ep in cf if ep["structure"] not in s_in_cs]
    res = {"conf_s_structures": kept, "conf_s_episodes": len(cs), "conf_all_episodes": len(allc),
           "conf_all_structures": len({ep["structure"] for ep in allc}), "status": {}}
    # ---------------------------------------------------------------- A: value of history
    R = L.rows(allc, names)
    y, s, lh, man = R["y72"], R["s"], R["lh"], R["manifest"]
    sc = {f"{v}|common": model(v, common).predict_proba(R["X"][v])[:, 1] for v in L.VIEWS}
    sc |= {f"{v}|best": model(v, best[v]).predict_proba(R["X"][v])[:, 1] for v in L.VIEWS}
    A = {"rows": int(len(y)), "positives": int(y.sum()), "common_config": common, "best_per_view": best,
         "primary_S2_minus_S1": L.auc_diff_ci(sc["S2|common"], sc["S1|common"], y, s, AP)}
    A["verdict"] = L.verdict_auc(A["primary_S2_minus_S1"]["ci"], 0.02, "AVANTAGE_HISTORIQUE", "DESAVANTAGE")
    sec = {}
    for a, b in (("S1", "S0"), ("S2", "S0")):
        sec[f"{a}-{b}|common"] = L.auc_diff_ci(sc[f"{a}|common"], sc[f"{b}|common"], y, s, 0.05)
    sec["S2-S1|best_per_view"] = L.auc_diff_ci(sc["S2|best"], sc["S1|best"], y, s, 0.05)
    sec["S2-S1|same_phase"] = L.auc_diff_ci(sc["S2|common"], sc["S1|common"], y, s, 0.05, phase=lh)
    nm = man == 0
    sec["S2-S1|before_manifest"] = L.auc_diff_ci(sc["S2|common"][nm], sc["S1|common"][nm], y[nm], s[nm], 0.05)
    sec["S2-S1|y24"] = L.auc_diff_ci(sc["S2|common"], sc["S1|common"], R["y24"], s, 0.05)
    sec["auc"] = {k: {"cond": L.cond_auc(v, y, s), "cond_equal_weight": L.cond_auc_equal(v, y, s), "global": L.global_auc(v, y),
                      "brier": float(np.mean((v - y) ** 2))} for k, v in sc.items()}
    sec["all_configs_S2_minus_S1_point"] = {}
    for fam, h in L.CONFIGS:
        cn = f"LR_C{h}" if fam == "LR" else f"HGB_d{h[0]}_lr{h[1]}"
        p1 = model("S1", cn).predict_proba(R["X"]["S1"])[:, 1]
        p2 = model("S2", cn).predict_proba(R["X"]["S2"])[:, 1]
        sec["all_configs_S2_minus_S1_point"][cn] = L.cond_auc(p2, y, s) - L.cond_auc(p1, y, s)
    A["secondary"] = sec
    res["A"] = A
    # ---------------------------------------------------------------- B and C need CONF-S
    if len(kept) < MIN_CONF_S:
        res["B"] = res["C"] = {"verdict": "NON CONCLUANT (budget)", "conf_s_structures": kept}
    else:
        Rs = L.rows(cs, names)
        ys, ss, lhs, mans = Rs["y72"], Rs["s"], Rs["lh"], Rs["manifest"]
        scs = {k: Rs["score"][k] for k in ("R0", "R1", "F", "O")}
        for v in L.VIEWS:
            scs[f"LR/HGB-{v}"] = model(v, best[v]).predict_proba(Rs["X"][v])[:, 1]
        cstar = sel["competitor_Cstar"]
        B = {"rows": int(len(ys)), "positives": int(ys.sum()), "competitor_Cstar": cstar,
             "primary_F_minus_Cstar": L.auc_diff_ci(scs["F"], scs[cstar], ys, ss, AP)}
        B["verdict"] = L.verdict_auc(B["primary_F_minus_Cstar"]["ci"], 0.03, "AVANTAGE_F", "DESAVANTAGE_F")
        bs = {f"F-{k}": L.auc_diff_ci(scs["F"], scs[k], ys, ss, 0.05) for k in scs if k != "F"}
        bs["O-F"] = L.auc_diff_ci(scs["O"], scs["F"], ys, ss, 0.05)
        bs["F-Cstar|same_phase"] = L.auc_diff_ci(scs["F"], scs[cstar], ys, ss, 0.05, phase=lhs)
        nm = mans == 0
        bs["F-Cstar|before_manifest"] = L.auc_diff_ci(scs["F"][nm], scs[cstar][nm], ys[nm], ss[nm], 0.05)
        bs["F-Cstar|y24"] = L.auc_diff_ci(scs["F"], scs[cstar], Rs["y24"], ss, 0.05)
        bs["auc"] = {k: {"cond": L.auc_ci(v, ys, ss), "cond_equal_weight": L.cond_auc_equal(v, ys, ss), "global": L.global_auc(v, ys),
                         "brier": float(np.mean((np.clip(v, 0, 1) - ys) ** 2)) if k != "R0" else None} for k, v in scs.items()}
        fns = {k: (lambda ep, k=k: [o["score"][k] for o in ep["origins"]]) for k in ("R0", "R1", "F", "O")}

        def lfn(v):
            m = model(v, best[v])
            return lambda ep: m.predict_proba(np.array([[(o["S0"] | o["S1"] | o["S2"])[n] for n in names[v]] for o in ep["origins"]], float))[:, 1].tolist()
        for v in L.VIEWS:
            fns[f"LR/HGB-{v}"] = lfn(v)
        bs["alerts_conf_s"] = {k: L.alert_summary(cs, fns[k], sel["alerts"][k]["theta"], sel["alerts"][k]["d"]) for k in fns}
        bs["alerts_conf_all_learned"] = {f"LR/HGB-{v}": L.alert_summary(allc, fns[f"LR/HGB-{v}"], sel["alerts"][f"LR/HGB-{v}"]["theta"],
                                                                        sel["alerts"][f"LR/HGB-{v}"]["d"]) for v in L.VIEWS}
        B["secondary"] = bs
        res["B"] = B
        # ------------------------------------------------------------ C: deferred interventions
        st_c = tuple(sel["structural_rule"])
        tau = sel["gate_tau"]
        s2f = fns["LR/HGB-S2"]

        def risk_at_dec(ep):
            return s2f(ep)[[o["hour"] for o in ep["origins"]].index(ep["decision"]["hour"])]
        pol = {"none": lambda ep: 0, "historical": lambda ep: 1, "structural": lambda ep: L.structural_action(st_c, ep),
               "gated_S2": lambda ep: L.structural_action(st_c, ep) if risk_at_dec(ep) >= tau else 0,
               "R1_planner": lambda ep: ep["decision"]["plans"]["R1_planner"]["choice"],
               "F_planner": lambda ep: ep["decision"]["plans"]["F_planner"]["choice"],
               "O_planner": lambda ep: ep["decision"]["plans"]["O_planner"]["choice"]}
        dstar = sel["decision_competitor_Dstar"]
        loss = {k: per_struct(cs, lambda ep, f=f: L.eval_loss(ep)[f(ep)]) for k, f in pol.items()}
        loss["expost_best"] = per_struct(cs, lambda ep: L.eval_loss(ep).min())
        diff = {st: loss[dstar][st] - loss["F_planner"][st] for st in loss[dstar]}
        C = {"Dstar": dstar, "decisions": len(cs), "primary_Dstar_minus_F": L.mean_diff_ci(diff, AP),
             "mean_loss": {k: float(np.mean(list(v.values()))) for k, v in loss.items()}}
        g = {}
        flag = False
        for m in GUARDRAILS + DESCRIPTIVE:
            inc = per_struct(cs, lambda ep, m=m: L.eval_metric(ep, pol["F_planner"](ep), m) - L.eval_metric(ep, pol[dstar](ep), m))
            g[m] = L.mean_diff_ci(inc, AP if m in GUARDRAILS else 0.05)
            if m in GUARDRAILS and g[m]["ci"][0] > 0:
                flag = True
        g["staff_hours_F_mean"] = float(np.mean([ep["decision"]["actions"][pol["F_planner"](ep)]["staff_hours"] for ep in cs]))
        g["staff_hours_Dstar_mean"] = float(np.mean([ep["decision"]["actions"][pol[dstar](ep)]["staff_hours"] for ep in cs]))
        C["guardrails_F_minus_Dstar"] = g
        lo, hi = C["primary_Dstar_minus_F"]["ci"]
        C["verdict"] = ("GAIN_AVEC_DEGRADATION" if flag else "GAIN_F") if lo > 0 else ("PERTE_F" if hi < 0 else "INDETERMINE")
        cs2 = {}
        for k in pol:
            if k != "F_planner":
                cs2[f"{k}-F"] = L.mean_diff_ci({st: loss[k][st] - loss["F_planner"][st] for st in loss[k]}, 0.05)
        cs2["none-expost_best"] = L.mean_diff_ci({st: loss["none"][st] - loss["expost_best"][st] for st in loss["none"]}, 0.05)
        cs2["choices"] = {k: [int(f(ep)) for ep in cs] for k, f in pol.items()}
        fam = {}
        for ep in cs:
            fam.setdefault(ep["family"], []).append({k: float(L.eval_loss(ep)[f(ep)]) for k, f in pol.items()})
        cs2["by_family_mean_loss"] = {f: {k: float(np.mean([r[k] for r in v])) for k in pol} for f, v in fam.items()}
        C["secondary"] = cs2
        res["C"] = C
        # examples (report)
        ex = []
        for ep in cs[:: max(1, len(cs) // 6)][:6]:
            ex.append({"structure": ep["structure"], "episode": ep["episode"], "family": ep["family"],
                       "origins": [{"h": o["hour"], "active": o["labels"]["active"], "y72": o["labels"]["y72"], "manifest": o["manifest"],
                                    "F": round(o["score"]["F"], 3), "R1": round(o["score"]["R1"], 3), "O": round(o["score"]["O"], 3)} for o in ep["origins"]],
                       "decision_hour": ep["decision"]["hour"], "actions": [a["id"] for a in ep["decision"]["actions"]],
                       "eval_loss": L.eval_loss(ep).round(0).tolist(), "choices": {k: int(f(ep)) for k, f in pol.items()},
                       "rupture_runs": ep["trace"]["rupture_runs"]})
        res["examples"] = ex
    res["D"] = {"verdict": "NON TESTÉ", "reason": "world model latent appris hors mandat (aucun réseau de neurones autorisé)"}
    # ---------------------------------------------------------------- propagation
    pr = [json.loads(p.read_text()) for p in sorted((L.RUNS / "PAIRED" / "BF2_CONF").glob("s*.json"))]
    P = {"structures": len(pr)}
    if pr:
        out = {}
        for fam in sorted({r["family"] for r in pr}):
            rr = [r for r in pr if r["family"] == fam]
            o = {"structures": len(rr)}
            for dep in ("cl", "tr", "compat", "drop", "cl+tr"):
                for met in ("rupture_minutes", "onsets", "n24_ticks"):
                    d = {r["structure"]: float(np.mean([e["base"][met] - e[dep][met] for e in r["episodes"]])) for r in rr}
                    o[f"{dep}|{met}"] = L.mean_diff_ci(d, 0.05)
            inter = {r["structure"]: float(np.mean([(e["base"]["rupture_minutes"] - e["cl+tr"]["rupture_minutes"])
                                                    - (e["base"]["rupture_minutes"] - e["cl"]["rupture_minutes"])
                                                    - (e["base"]["rupture_minutes"] - e["tr"]["rupture_minutes"]) for e in r["episodes"]])) for r in rr}
            o["interaction_cl_tr|rupture_minutes"] = L.mean_diff_ci(inter, 0.05)
            o["base_rupture_minutes_mean"] = float(np.mean([e["base"]["rupture_minutes"] for r in rr for e in r["episodes"]]))
            o["block_ticks_base_mean"] = {k: float(np.mean([e["base"]["block_ticks"][k] for r in rr for e in r["episodes"]]))
                                          for k in ("block_compat", "block_clean", "block_transport")}
            out[fam] = o
        P["by_family"] = out
    att = {}
    for ep in allc:
        a = att.setdefault(ep["family"], {"block_compat": 0, "block_clean": 0, "block_transport": 0, "n24_ticks": 0})
        for un, v in ep["trace"]["attribution_at_n24"].items():
            for k in ("block_compat", "block_clean", "block_transport"):
                a[k] += v[k]
            a["n24_ticks"] += ep["trace"]["n24_ticks"][un]
    P["trace_attribution_at_n24"] = att
    P["cascade_between_units"] = "NON ÉVALUABLE (aucun contrôle apparié n'isole la transmission A→B)"
    res["propagation"] = P
    (EV / "RESULTS_BFRAG2_CONF.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    print(json.dumps({"A": {k: A[k] for k in ("primary_S2_minus_S1", "verdict")},
                      "B": {k: res["B"].get(k) for k in ("competitor_Cstar", "primary_F_minus_Cstar", "verdict")},
                      "C": {k: res["C"].get(k) for k in ("Dstar", "primary_Dstar_minus_F", "verdict", "mean_loss")}}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
