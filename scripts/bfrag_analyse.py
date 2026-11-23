#!/usr/bin/env python3
"""B-FRAG analysis (PROTOCOLE_BFRAG s.4, s.7, s.8).

    tune --tag T    -> evidence/howm2_bfrag/TUNE_<T>.json  (validity V2-V5, thresholds, competitor choice; all methods)
    conf --tag T    -> evidence/howm2_bfrag/RESULTS_BFRAG_CONF.json (frozen selection from FREEZE_BFRAG.json)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
EV = ROOT / "evidence/howm2_bfrag"
HS = ("6", "24", "72", "168")
SCORED = ("R0", "R1", "F", "O")
DEC = ("ref", "R0", "R2", "F", "O")
FRAGILE = ("SF1_cleaning_window", "SF2_transport_window", "SF3_planned_drop")
B = 2000


def seed() -> int:
    from hospitalos.howm.keys import key

    return int(key("BFRAG", "bootstrap") % (2**31))


def load(tag: str, part: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((EV / "runs" / tag / part).glob("*.json"))]


def labels(rec: dict, h: str) -> list[int]:
    return [int(r["rupture"]["within"][h]) for r in rec["eval"]["0"]]


def active(rec: dict) -> bool:
    return any(r["rupture"]["active_at_start"] for r in rec["eval"]["0"])


def score(rec: dict, m: str, h: str) -> float:
    if m == "R0":
        return rec["methods"]["R0"]["score"]
    return rec["methods"][m]["risk"][h]


def loss(rec: dict, m: str) -> float:
    return float(np.mean([r["wait_patient_min"] for r in rec["eval"][str(rec["plans"][m])]]))


def auc(recs: list[dict], m: str, h: str, idx: np.ndarray | None = None) -> float | None:
    rs = [recs[i] for i in (idx if idx is not None else range(len(recs)))]
    ids = [r["index"] for r in rs]
    s = np.array([score(r, m, h) for r in rs])
    pos = np.array([sum(labels(r, h)) for r in rs], float)
    neg = np.array([len(labels(r, h)) - sum(labels(r, h)) for r in rs], float)
    same = np.equal.outer(ids, ids)
    gt = (np.greater.outer(s, s) + 0.5 * np.equal.outer(s, s)) * ~same
    w = np.outer(pos, neg) * ~same
    tot = w.sum()
    return float((gt * w).sum() / tot) if tot > 0 else None


def boot(recs: list[dict], stat, rng: np.random.Generator) -> list[float]:
    n = len(recs)
    vals = []
    for _ in range(B):
        v = stat(rng.integers(0, n, n))
        if v is not None:
            vals.append(v)
    return [float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))] if vals else [None, None]


def youden(recs: list[dict], m: str, h: str) -> dict:
    s = np.array([score(r, m, h) for r in recs])
    best = None
    for thr in sorted(set(s.tolist())) + [float("inf")]:
        alert = s >= thr
        rate = float(alert.mean())
        if rate > 0.5:
            continue
        tp = sum(a * sum(labels(r, h)) for a, r in zip(alert, recs))
        fn = sum((1 - a) * sum(labels(r, h)) for a, r in zip(alert, recs))
        fp = sum(a * (len(labels(r, h)) - sum(labels(r, h))) for a, r in zip(alert, recs))
        tn = sum((1 - a) * (len(labels(r, h)) - sum(labels(r, h))) for a, r in zip(alert, recs))
        tpr = tp / (tp + fn) if tp + fn else 0.0
        fpr = fp / (fp + tn) if fp + tn else 0.0
        j = tpr - fpr
        if best is None or j > best["J"] + 1e-12:
            best = {"threshold": thr, "J": j, "tpr": tpr, "fpr": fpr, "alert_rate": rate}
    return best


def alert_metrics(recs: list[dict], m: str, h: str, thr: float) -> dict:
    tp = fn = fp = tn = 0
    lead_sum, n_rupt = 0.0, 0
    for r in recs:
        a = score(r, m, h) >= thr
        for row in r["eval"]["0"]:
            y = row["rupture"]["within"][h]
            if y:
                n_rupt += 1
                lead = row["rupture"]["first_onset_tick"] / 4.0
                lead_sum += lead if a else 0.0
                tp += a
                fn += not a
            else:
                fp += a
                tn += not a
    out = {"threshold": thr, "sensitivity": tp / (tp + fn) if tp + fn else None, "missed": fn,
           "false_alert_rate": fp / (fp + tn) if fp + tn else None, "alert_load": float(np.mean([score(r, m, h) >= thr for r in recs])),
           "mean_lead_h_misses_as_0": lead_sum / n_rupt if n_rupt else None, "n_rupture_realisations": n_rupt}
    if m != "R0":
        out["brier"] = float(np.mean([(score(r, m, h) - y) ** 2 for r in recs for y in labels(r, h)]))
    return out


def describe(recs: list[dict], rng: np.random.Generator) -> dict:
    out = {"n_worlds": len(recs), "families": {}}
    for m in DEC:
        rows = [row for r in recs for row in r["eval"][str(r["plans"][m])]]
        out.setdefault("decision_outcomes", {})[m] = {
            "mean_wait_patient_min": float(np.mean([loss(r, m) for r in recs])),
            "uncovered_care_min": float(np.mean([x["uncovered_care_min"] for x in rows])),
            "rupture_168_rate": float(np.mean([x["rupture"]["within"]["168"] for x in rows])),
            "rupture_duration_min": float(np.mean([x["rupture"]["duration_min"] for x in rows])),
            "rupture_severity_patient_min": float(np.mean([x["rupture"]["severity_patient_min"] for x in rows])),
            "cascade_rate": float(np.mean([x["rupture"]["cascade_both_units_24h"] for x in rows])),
            "reinforcement_hours": float(np.mean([x["reinforcement_hours"] for x in rows])),
            "rejected_at_plan": float(np.sum([x["rejected_at_plan"] for x in rows])),
            "terminal_queue": float(np.mean([sum(t["queue"] for t in x["terminal"].values()) for x in rows])),
            "terminal_max_wait_min": float(np.mean([max(t["max_wait_min"] for t in x["terminal"].values()) for x in rows])),
            "plan_distribution": {str(k): int(v) for k, v in zip(*np.unique([r["plans"][m] for r in recs], return_counts=True))}}
    for fam in sorted({r["family"] for r in recs}):
        rf = [r for r in recs if r["family"] == fam]
        out["families"][fam] = {"n": len(rf), "rupture_168_ref": float(np.mean([y for r in rf for y in labels(r, "168")])),
                                "active_at_t0": int(sum(active(r) for r in rf)),
                                "mean_loss": {m: float(np.mean([loss(r, m) for r in rf])) for m in DEC}}
    return out


def validity(recs: list[dict], rng: np.random.Generator) -> dict:
    prev = float(np.mean([y for r in recs for y in labels(r, "168")]))
    act = float(np.mean([active(r) for r in recs]))
    none = float(np.mean([sum(labels(r, "168")) == 0 for r in recs]))
    fam = {f: float(np.mean([y for r in recs if r["family"] == f for y in labels(r, "168")])) for f in sorted({r["family"] for r in recs})}
    sf = float(np.mean([fam[f] for f in FRAGILE if f in fam]))
    v5 = {}
    for f in FRAGILE:
        rf = [r for r in recs if r["family"] == f and r.get("controls_relaxed_ref")]
        if not rf:
            continue
        d = np.array([loss(r, "ref") - float(np.mean([x["wait_patient_min"] for x in r["controls_relaxed_ref"]])) for r in rf])
        dr = np.array([np.mean(labels(r, "168")) - np.mean([x["rupture"]["within"]["168"] for x in r["controls_relaxed_ref"]]) for r in rf])
        v5[f] = {"n": len(rf), "wait_reduction_mean": float(d.mean()), "wait_reduction_ci95": boot(rf, lambda i, d=d: float(d[i].mean()), rng),
                 "rupture_rate_reduction_mean": float(dr.mean())}
    out = {"V2_prevalence_168": prev, "V2_pass": 0.2 <= prev <= 0.8, "V3_active_at_t0": act, "V3_pass": act <= 0.10,
           "V4_worlds_without_rupture": none, "V4_SC6_vs_SF": [fam.get("SC6_low_load"), sf],
           "V4_pass": none >= 0.10 and fam.get("SC6_low_load", 1.0) < sf, "V5_paired_controls": v5, "family_prevalence_168": fam}
    out["V2_V4_pass"] = bool(out["V2_pass"] and out["V3_pass"] and out["V4_pass"])
    return out


def anticipation(recs: list[dict], rng: np.random.Generator, thresholds: dict | None) -> dict:
    ra = [r for r in recs if not active(r)]
    out = {"n_worlds_scored": len(ra), "excluded_active_at_t0": len(recs) - len(ra), "auc": {}, "alerts": {}}
    for m in SCORED:
        out["auc"][m] = {}
        for h in HS:
            a = auc(ra, m, h)
            out["auc"][m][h] = {"auc": a, "ci95": boot(ra, lambda i, m=m, h=h: auc(ra, m, h, i), rng) if h == "72" else None}
    thr = thresholds or {m: {h: youden(ra, m, h) for h in HS} for m in SCORED}
    out["thresholds_used"] = thr
    for m in SCORED:
        out["alerts"][m] = {h: alert_metrics(ra, m, h, thr[m][h]["threshold"]) for h in HS}
    return out


def tune(tag: str) -> int:
    rng = np.random.default_rng(seed())
    recs = load(tag, "BFRAG_TUNE")
    val = validity(recs, rng)
    ant = anticipation(recs, rng, None)
    desc = describe(recs, rng)
    loss_r0 = desc["decision_outcomes"]["R0"]["mean_wait_patient_min"]
    loss_r2 = desc["decision_outcomes"]["R2"]["mean_wait_patient_min"]
    comp_dec = "R0" if loss_r0 <= loss_r2 else "R2"
    a0, a1 = ant["auc"]["R0"]["72"]["auc"], ant["auc"]["R1"]["72"]["auc"]
    comp_ant = "R0" if (a0 or 0) >= (a1 or 0) else "R1"
    gains = np.array([loss(r, comp_dec) - loss(r, "F") for r in recs])
    out = {"tag": tag, "n_worlds": len(recs), "validity": val, "anticipation": ant, "descriptive": desc,
           "selection_if_retained": {"decision_competitor": comp_dec, "anticipation_competitor": comp_ant,
                                     "alert_thresholds": ant["thresholds_used"]},
           "tune_gain_F_vs_competitor_descriptive": {"mean": float(gains.mean()), "ci95": boot(recs, lambda i: float(gains[i].mean()), rng)},
           "timing_s_mean": {k: float(np.mean([r["timing_s"].get(k, 0) for r in recs])) for k in ("R1_R2", "F", "O", "evaluate", "total")}}
    (EV / f"TUNE_{tag}.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"validity": {k: v for k, v in val.items() if k != "V5_paired_controls"}, "V5": val["V5_paired_controls"],
                      "auc72": {m: ant["auc"][m]["72"] for m in SCORED}, "selection": {k: v for k, v in out["selection_if_retained"].items() if k != "alert_thresholds"},
                      "losses": {m: round(desc["decision_outcomes"][m]["mean_wait_patient_min"]) for m in DEC},
                      "gain_F": out["tune_gain_F_vs_competitor_descriptive"]}, indent=1))
    return 0


def conf(tag: str) -> int:
    rng = np.random.default_rng(seed())
    fz = json.loads((EV / "FREEZE_BFRAG.json").read_text())
    sel = fz["selection"]
    recs = load(tag, "BFRAG_CONF")
    complete = len(recs) == fz["conf_size"]
    val = validity(recs, rng)
    ant = anticipation(recs, rng, sel["alert_thresholds"])
    desc = describe(recs, rng)
    comp = sel["decision_competitor"]
    g = np.array([loss(r, comp) - loss(r, "F") for r in recs])
    ci = boot(recs, lambda i: float(g[i].mean()), rng)
    constraints = all(x["rejected_at_plan"] == 0 for r in recs for x in r["eval"][str(r["plans"]["F"])])
    if not complete:
        dec_v = "INCOMPLET"
    elif not val["V2_V4_pass"]:
        dec_v = "VALIDITE_NON_ETABLIE"
    elif ci[0] > 0 and constraints:
        dec_v = "GAIN_STATISTIQUE"
    elif ci[1] <= 0:
        dec_v = "ABSENCE_DE_SUPERIORITE"
    else:
        dec_v = "INDETERMINE"
    ra = [r for r in recs if not active(r)]
    ca = sel["anticipation_competitor"]
    d_auc = (ant["auc"]["F"]["72"]["auc"] or 0) - (ant["auc"][ca]["72"]["auc"] or 0)
    d_ci = boot(ra, lambda i: (auc(ra, "F", "72", i) or 0) - (auc(ra, ca, "72", i) or 0), rng)
    if not complete:
        ant_v = "INCOMPLET"
    elif not val["V2_V4_pass"]:
        ant_v = "VALIDITE_NON_ETABLIE"
    elif d_ci[0] > 0:
        ant_v = "AVANTAGE_ANTICIPATION"
    elif d_ci[1] <= 0:
        ant_v = "ABSENCE_DE_SUPERIORITE"
    else:
        ant_v = "INDETERMINE"
    others = {m: {"gain_vs_F_competitor_minus_m": None} for m in DEC}
    for m in DEC:
        gm = np.array([loss(r, m) - loss(r, "F") for r in recs])
        others[m] = {"mean_loss_minus_F": float(gm.mean()), "ci95": boot(recs, lambda i, gm=gm: float(gm[i].mean()), rng)}
    out = {"freeze_sha256": fz.get("self_sha256"), "n_worlds": len(recs), "complete": complete,
           "verdicts": {"technical_validity": "VALIDE" if val["V2_V4_pass"] else "VALIDITE_NON_ETABLIE",
                        "anticipation": ant_v, "decision": dec_v, "learned_network": "NON TESTÉ"},
           "decision": {"competitor": comp, "gain_competitor_minus_F_patient_min": float(g.mean()), "ci95": ci,
                        "constraints_respected": constraints, "all_methods_minus_F": others},
           "anticipation_primary": {"competitor": ca, "delta_auc72_F_minus_comp": d_auc, "ci95": d_ci},
           "validity": val, "anticipation": ant, "descriptive": desc,
           "timing_s_mean": {k: float(np.mean([r["timing_s"].get(k, 0) for r in recs])) for k in ("R1_R2", "F", "O", "evaluate", "total")}}
    (EV / "RESULTS_BFRAG_CONF.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"verdicts": out["verdicts"], "decision": {k: v for k, v in out["decision"].items() if k != "all_methods_minus_F"},
                      "anticipation_primary": out["anticipation_primary"], "auc72": {m: ant["auc"][m]["72"] for m in SCORED},
                      "losses": {m: round(desc["decision_outcomes"][m]["mean_wait_patient_min"]) for m in DEC},
                      "validity": {k: v for k, v in val.items() if k not in ("V5_paired_controls",)}}, indent=1))
    return 0


if __name__ == "__main__":
    cmd, tag = sys.argv[1], sys.argv[sys.argv.index("--tag") + 1]
    raise SystemExit({"tune": tune, "conf": conf}[cmd](tag))
