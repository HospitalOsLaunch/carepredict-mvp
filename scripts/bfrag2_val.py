#!/usr/bin/env python3
"""B-FRAG 2 selections on VAL (PROTOCOLE_BFRAG2 s.7-8, s.10): competitor C* (anticipation), alert
thresholds, structural rule, S2 gate, decision competitor D*. VAL only; no CONF data is read."""

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
REFS = ("R0", "R1", "LR/HGB-S0", "LR/HGB-S1", "LR/HGB-S2")  # tie-break order for C*


def model(view: str, cfg: str):
    return pickle.loads((EV / "models" / f"{view}_{cfg}.pkl").read_bytes())


def ep_matrix(ep: dict, names: list[str]) -> np.ndarray:
    return np.array([[(o["S0"] | o["S1"] | o["S2"])[n] for n in names] for o in ep["origins"]], float)


def learned_fn(view: str, cfg: str, names: dict):
    m = model(view, cfg)
    cache: dict = {}

    def f(ep):
        k = (ep["part"], ep["structure"], ep["episode"])
        if k not in cache:
            cache[k] = m.predict_proba(ep_matrix(ep, names[view]))[:, 1].tolist()
        return cache[k]
    return f


def sim_fn(name: str):
    return lambda ep: [o["score"][name] for o in ep["origins"]]


def per_structure_mean(eps: list[dict], val_fn) -> float:
    by: dict = {}
    for ep in eps:
        by.setdefault(ep["structure"], []).append(val_fn(ep))
    return float(np.mean([np.mean(v) for v in by.values()]))


def main() -> int:
    learn = json.loads((EV / "LEARN.json").read_text())
    names = learn["feature_names"]
    best = learn["best_per_view"]
    vs = L.load("S", "BF2_VAL")
    assert len(vs) == 54, len(vs)
    va = L.load("F", "BF2_VAL")
    R = L.rows(vs, names)
    sc = {"R0": R["score"]["R0"], "R1": R["score"]["R1"], "F": R["score"]["F"], "O": R["score"]["O"]}
    fns = {"R0": sim_fn("R0"), "R1": sim_fn("R1"), "F": sim_fn("F"), "O": sim_fn("O")}
    for v in L.VIEWS:
        m = model(v, best[v])
        sc[f"LR/HGB-{v}"] = m.predict_proba(R["X"][v])[:, 1]
        fns[f"LR/HGB-{v}"] = learned_fn(v, best[v], names)
    auc = {k: L.cond_auc(sc[k], R["y72"], R["s"]) for k in sc}
    cstar = max(((auc[k] if auc[k] is not None else -1, -i, k) for i, k in enumerate(REFS)))[2]
    # alerts: simulators on VAL-S; learned on VAL (100 structures)
    alerts = {}
    for k in ("R0", "R1", "F", "O"):
        alerts[k] = L.tune_alert(vs, fns[k])
    for v in L.VIEWS:
        alerts[f"LR/HGB-{v}"] = L.tune_alert(va, fns[f"LR/HGB-{v}"])
    # decisions
    ids = [a["id"] for a in vs[0]["decision"]["actions"]]
    staff = [a["staff_hours"] for a in vs[0]["decision"]["actions"]]
    cands = L.structural_candidates()
    sl = []
    for i, c in enumerate(cands):
        loss = per_structure_mean(vs, lambda ep, c=c: L.eval_loss(ep)[L.structural_action(c, ep)])
        sl.append((round(loss, 6), staff[L.structural_action(c, vs[0])] if c[0] == "fixed" else 8, i))
    st_i = min(sl)[2]
    st_c = cands[st_i]
    s2 = fns["LR/HGB-S2"]

    def risk_at_dec(ep):
        return s2(ep)[[o["hour"] for o in ep["origins"]].index(ep["decision"]["hour"])]
    rd = np.array([risk_at_dec(ep) for ep in vs])
    taus = [float(np.quantile(rd, q)) for q in (0.25, 0.5, 0.75)]
    gl = []
    for j, tau in enumerate(taus):
        loss = per_structure_mean(vs, lambda ep, tau=tau: L.eval_loss(ep)[L.structural_action(st_c, ep) if risk_at_dec(ep) >= tau else 0])
        gl.append((round(loss, 6), j))
    tau = taus[min(gl)[1]]
    pol = {"none": lambda ep: 0, "historical": lambda ep: 1, "structural": lambda ep: L.structural_action(st_c, ep),
           "gated_S2": lambda ep: L.structural_action(st_c, ep) if risk_at_dec(ep) >= tau else 0,
           "R1_planner": lambda ep: ep["decision"]["plans"]["R1_planner"]["choice"]}
    pl = {k: per_structure_mean(vs, lambda ep, f=f: L.eval_loss(ep)[f(ep)]) for k, f in pol.items()}
    dstar = min(((round(v, 6), i, k) for i, (k, v) in enumerate(pl.items())))[2]
    expost = per_structure_mean(vs, lambda ep: L.eval_loss(ep).min())
    out = {"val_s": {"episodes": len(vs), "structures": len({e["structure"] for e in vs}), "rows": int(len(R["y72"])), "positives": int(R["y72"].sum()),
                     "structures_with_pairs": sum(1 for _u, p in L.group_up(np.zeros(len(R["y72"])), R["y72"], R["s"]).values() if p)},
           "val_s_cond_auc": auc, "competitor_Cstar": cstar, "competitor_rule": "max VAL-S pooled conditional AUC among " + ", ".join(REFS),
           "alerts": alerts, "alert_tuning_population": {"R0/R1/F/O": "VAL-S (18 x 3)", "learned": "VAL (100 x 3)"},
           "structural_candidates": [list(c) for c in cands], "structural_losses": {str(cands[i]): l_ for l_, _s, i in sl},
           "structural_rule": list(st_c), "structural_rule_ids_example": ids[L.structural_action(st_c, vs[0])],
           "gate_taus": taus, "gate_losses": {str(taus[j]): l_ for l_, j in gl}, "gate_tau": tau,
           "policy_losses_val_s": pl, "decision_competitor_Dstar": dstar, "expost_best_val_s": expost,
           "learned_configs": best, "common_config_A": learn["common_config_A"]}
    (EV / "SELECTION_VAL.json").write_text(json.dumps(out, indent=1, default=float) + "\n")
    print(json.dumps({k: out[k] for k in ("val_s", "val_s_cond_auc", "competitor_Cstar", "structural_rule", "gate_tau", "policy_losses_val_s",
                                          "decision_competitor_Dstar", "expost_best_val_s")}, indent=1, default=float))
    print(json.dumps({k: {"theta": v["theta"], "d": v["d"], **(v["val"] or {})} for k, v in alerts.items()}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
