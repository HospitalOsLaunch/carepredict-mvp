#!/usr/bin/env python3
"""HOWM-INT-1 final analysis (frozen in FREEZE_INT1.json before the campaign). Writes evidence/howm_int1/RESULTS_INT1.json.

Primary (single): MAIN panel, cumulative 7-day wait of B* minus W (positive = W better), per-structure mean over
its 3 episodes x 4 futures, paired cluster bootstrap over structures (B = 2000, seed 20261117), 95 % CI.
Relative gain = (mean B* - mean W) / mean B* on aggregated means, ratio re-sampled with the same bootstrap.
Everything else descriptive (95 % CIs, no correction)."""
import glob
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
EV = ROOT / "evidence/howm_int1"
S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")
OUT = S / "int1_eval"
B, SEED = 2000, 20261117
GUARD = ("uncovered_care_min", "rejected", "rupture_minutes", "rupture_onsets", "terminal_queue", "terminal_max_wait_min", "staff_hours",
         "aval_blocked_end", "transfer_pending_end")


def load(panel):
    recs = [json.loads(Path(f).read_text()) for f in sorted(glob.glob(str(OUT / panel / "*.json")))]
    if panel != "SUB32":
        return recs
    merged = {}  # SUB32 files hold one future each (s, e, r): merge per (structure, episode)
    for r in recs:
        m = merged.setdefault((r["structure"], r["episode"]), {**r, "futures": {}})
        m["futures"].update(r["futures"])
    return list(merged.values())


def per_struct(recs, pol, metric="wait_patient_min"):
    by = {}
    for r in recs:
        for fut in r["futures"].values():
            if pol in fut:
                by.setdefault(r["structure"], []).append(float(fut[pol][metric]))
    return {s: float(np.mean(v)) for s, v in by.items()}


def boot(d: dict, rng_seed=SEED):
    st = sorted(d)
    v = np.array([d[s] for s in st])
    idx = np.random.default_rng(rng_seed).integers(0, len(st), (B, len(st)))
    bm = v[idx].mean(1)
    return {"mean": float(v.mean()), "ci95": [float(np.quantile(bm, 0.025)), float(np.quantile(bm, 0.975))], "n_structures": len(st)}


def ratio_boot(a: dict, b: dict):
    st = sorted(set(a) & set(b))
    va, vb = np.array([a[s] for s in st]), np.array([b[s] for s in st])
    idx = np.random.default_rng(SEED).integers(0, len(st), (B, len(st)))
    r = (va[idx].mean(1) - vb[idx].mean(1)) / va[idx].mean(1)
    return {"relative_gain": float((va.mean() - vb.mean()) / va.mean()), "ci95": [float(np.quantile(r, 0.025)), float(np.quantile(r, 0.975))]}


def diff(recs, a, b, metric="wait_patient_min"):
    pa, pb = per_struct(recs, a, metric), per_struct(recs, b, metric)
    return {s: pa[s] - pb[s] for s in pa if s in pb}


def main() -> int:
    fr = json.loads((EV / "FREEZE_INT1.json").read_text())
    bstar, w = fr["B_star"], fr["W_primary"]
    res = {"B_star": bstar, "W_primary": w}
    main_ = load("MAIN")
    kept = sorted({r["structure"] for r in main_ if sum(1 for x in main_ if x["structure"] == r["structure"]) == 3})
    res["MAIN"] = {"structures_complete": len(kept), "planned": fr["panels"]["MAIN"]}
    if len(kept) < fr["min_structures_main"]:
        res["status"] = "VALIDATION_FINALE_NON_EXECUTEE"
    else:
        main_ = [r for r in main_ if r["structure"] in kept]
        pols = sorted({p for r in main_ for f in r["futures"].values() for p in f})
        res["MAIN"]["mean_wait"] = {p: boot(per_struct(main_, p)) for p in pols}
        d = diff(main_, bstar, w)
        prim = boot(d)
        res["primary_Bstar_minus_W"] = prim
        res["verdict"] = "GAIN_W_ETABLI" if prim["ci95"][0] > 0 else ("W_INFERIEUR" if prim["ci95"][1] < 0 else "INDETERMINE")
        rg = ratio_boot(per_struct(main_, bstar), per_struct(main_, w))
        res["relative_gain"] = rg | {"target_5pct_estimate": rg["relative_gain"] >= 0.05, "target_5pct_supported_by_ci": rg["ci95"][0] >= 0.05}
        v = np.array(list(d.values()))
        res["distribution"] = {"quantiles": {q: float(np.quantile(v, q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)},
                               "frac_structures_W_worse": float(np.mean(v < 0)),
                               "worst_10": sorted(({"structure": s, "diff": x} for s, x in d.items()), key=lambda z: z["diff"])[:10]}
        res["guardrails_W_minus_Bstar"] = {m: boot(diff(main_, w, bstar, m)) for m in GUARD}
        res["secondary_vs_W"] = {p: boot(diff(main_, p, w)) for p in pols if p != w}
        fam = {}
        for r in main_:
            fam.setdefault(r["family"], set()).add(r["structure"])
        res["by_family_Bstar_minus_W"] = {f: float(np.mean([d[s] for s in ss])) for f, ss in fam.items()}
        res["status"] = "EVALUATION_FINALE_EXECUTEE"
    sub = load("SUB32")
    if sub:
        ss = sorted({r["structure"] for r in sub})
        m32 = [r for r in main_ if r["structure"] in ss]
        res["SUB32"] = {"structures": len(ss), "mean_wait": {p: boot(per_struct(sub, p)) for p in ("F", "R1")} |
                        {p: boot(per_struct(m32, p)) for p in sorted({p for r in m32 for f in r["futures"].values() for p in f})},
                        "F_minus_W": boot({s: per_struct(sub, "F")[s] - per_struct(m32, w)[s] for s in ss}),
                        "R1_minus_W": boot({s: per_struct(sub, "R1")[s] - per_struct(m32, w)[s] for s in ss}),
                        "decision_cpu_s": {p: float(np.mean([x for r in sub for f in r["futures"].values() for x in f[p]["decision_cpu_s"]])) for p in ("F", "R1")}}
    for panel in ("EXT", "COMBO", "SIZE12"):
        rr = load(panel)
        if not rr:
            continue
        pols = sorted({p for r in rr for f in r["futures"].values() for p in f})
        out = {"structures": len({r["structure"] for r in rr}), "mean_wait": {p: boot(per_struct(rr, p)) for p in pols},
               "Bstar_minus_W": boot(diff(rr, bstar, w)) if bstar in pols else None}
        for n in sorted({r["n"] for r in rr}):
            sub_n = [r for r in rr if r["n"] == n]
            out[f"n{n}_Bstar_minus_W"] = boot(diff(sub_n, bstar, w)) if bstar in pols else None
        res[panel] = out
    # anticipation: W predicted per-unit rupture probability over the next 24 h vs realised onset in that window
    ys, ps = [], []
    for panel in ("MAIN", "EXT", "COMBO", "SIZE12"):
        for r in load(panel):
            iv = 24 if panel == "MAIN" else 6
            for fut in r["futures"].values():
                o = fut.get(w)
                if not o or "anticipation" not in o:
                    continue
                units = sorted(o["rupture_runs"])
                for k, an in enumerate(a for a in o["anticipation"] if a["system"] == w):
                    t = k * iv * 4
                    for j, un in enumerate(units if len(an["p24"]) == len(units) else []):
                        y = any(t <= a_ < t + 96 for a_, _b in o["rupture_runs"][un])
                        ys.append(int(y))
                        ps.append(an["p24"][j])
    if ys and 0 < sum(ys) < len(ys):
        from sklearn.metrics import roc_auc_score

        yv, pv = np.array(ys), np.array(ps)
        bins = np.quantile(pv, np.linspace(0, 1, 11))
        cal = [{"p_mean": float(pv[(pv >= lo) & (pv <= hi)].mean()), "freq": float(yv[(pv >= lo) & (pv <= hi)].mean())}
               for lo, hi in zip(bins[:-1], bins[1:]) if ((pv >= lo) & (pv <= hi)).any()]
        res["anticipation_W"] = {"unit_decisions": len(ys), "positives": int(yv.sum()), "auc": float(roc_auc_score(yv, pv)),
                                 "brier": float(np.mean((pv - yv) ** 2)), "base_rate": float(yv.mean()), "calibration_deciles": cal}
    cpu = {}
    for r in main_:
        for fut in r["futures"].values():
            for p, o in fut.items():
                cpu.setdefault(p, []).extend(o.get("decision_cpu_s", []))
    res["decision_cpu_s_MAIN"] = {p: {"mean": float(np.mean(v)), "p95": float(np.quantile(v, 0.95))} for p, v in cpu.items() if v}
    (EV / "RESULTS_INT1.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps({k: res.get(k) for k in ("status", "verdict", "primary_Bstar_minus_W", "relative_gain")}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
