#!/usr/bin/env python3
"""HOWM-2 C1 palier 1: CVAL selection, F-C1 freeze, single final campaign, analysis
(NORME_C1_PALIER1 s.6-s.11, ledger note c1_lot_reallocation).

    select                          -> evidence/howm2_c1/SELECTION.json (CVAL only)
    freeze                          -> evidence/howm2_c1/F_C1.json (before any CEVAL generation)
    run --part P --start a --stop b -> evidence/howm2_c1/final/<P>/<i>.json (resumable)
    analyse                         -> evidence/howm2_c1/RESULTS_C1_P1.json
"""

from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
EV = ROOT / "evidence/howm2_c1"
FINAL = EV / "final"
HS = ("1", "6", "24")
R1_FAMS = ("ready", "transport", "cleaning", "confirmation", "presence", "arrivals", "care")
RHO_FAMS = ("ready", "confirmation", "presence", "arrivals", "care")
DELTA_ID = 0.02
B = 2000
VERDICT_SYSTEMS = ("C.1", "C.2b")  # C.2a: N=1000 infeasible in budget -> no verdict (ledger note)
ENSEMBLES = [("C.1", 100), ("C.1", 1000), ("C.2b", 100), ("C.2b", 1000), ("C.2a", 100)]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_state(system: str, N: int, seed: int) -> dict:
    from hospitalos.howm2 import c1

    return json.loads((c1.run_dir(system, N, seed) / "state.json").read_text())


def select() -> int:
    from hospitalos.howm2 import c1

    runs = {}
    for system in c1.SYSTEMS:
        for N in c1.SIZES:
            for s in c1.SEEDS:
                d = c1.run_dir(system, N, s)
                if not (d / "state.json").exists():
                    runs[f"{system}:{N}:{s}"] = {"status": "not_executed"}
                    continue
                m = run_state(system, N, s)
                st = m["state"]
                runs[f"{system}:{N}:{s}"] = {"status": "done" if m["done"] else "incomplete", "steps": st["step"],
                                             "best_step": st["best_step"], "best_cval_total": st["best_total"],
                                             "consumed": c1.consumed_check(st, N), "log": m["log"],
                                             "best_sha256": m.get("best_sha256")}
    retained, lead = {}, {}
    for system in c1.SYSTEMS:
        done = [N for N in c1.SIZES if all(runs[f"{system}:{N}:{s}"]["status"] == "done" for s in c1.SEEDS)]
        retained[system] = max(done) if done else None
    for system in VERDICT_SYSTEMS:
        if retained[system] == 1000:
            lead[system] = float(np.mean([runs[f"{system}:1000:{s}"]["best_cval_total"] for s in c1.SEEDS]))
    leader = min(lead, key=lead.get) if lead else None
    out = {"rule": "NORME_C1_PALIER1 s.6 (CVAL only)", "runs": runs, "retained_point": retained,
           "cval_mean_best_total_at_1000": lead, "leading_system": leader,
           "c2a_note": "C.2a N=1000 not executed (budget, ledger note c1_lot_reallocation): no verdict, no substitution; C.2a N=100 descriptive"}
    (EV / "SELECTION.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "runs"}, indent=1))
    return 0


def freeze() -> int:
    from hospitalos.howm import corpus as C
    from hospitalos.howm2 import c1

    if FINAL.exists() and any(FINAL.rglob("*.json")):
        raise SystemExit("final campaign already started: freeze refused")
    sel = json.loads((EV / "SELECTION.json").read_text())
    weights = {}
    for system, N in ENSEMBLES:
        for s in c1.SEEDS:
            d = c1.run_dir(system, N, s)
            weights[f"{system}:{N}:{s}"] = {"best.pt": sha(d / "best.pt"), "state.json": sha(d / "state.json")}
    code = {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT / "src/hospitalos/howm2").glob("*.py"))}
    code.update({str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT / "scripts").glob("howm2_c1*.py"))})
    code["scripts/howm2_a2_l2c.py"] = sha(ROOT / "scripts/howm2_a2_l2c.py")
    out = {"freeze": "F-C1", "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "selection_sha256": sha(EV / "SELECTION.json"), "leading_system": sel["leading_system"],
           "retained_point": sel["retained_point"], "weights": weights, "code": code,
           "frozen_howm1_code": C.code_hashes(),
           "references": {"L2": "hospitalos.howm2.ladder.l2_predict + evidence/howm1/B0_PARAMS.json",
                          "B0_PARAMS.json": sha(ROOT / "evidence/howm1/B0_PARAMS.json"),
                          "L2c": "evidence/howm2/L2C_PARAMS.json", "L2C_PARAMS.json": sha(ROOT / "evidence/howm2/L2C_PARAMS.json"),
                          "L4": "hospitalos.howm2.ladder (filter of tranche A)", "levels": "L0..L5 via ladder.run_establishment on C1 origins"},
           "populations": {"HOWM2_CEVAL": 200, "HOWM2_DIAG": 100}, "origins": c1.ORIGINS, "horizons": [1, 6, 24],
           "comparisons_closed_list": {
               "verdict": "per system in {C.1, C.2b} at N=1000: Delta_C(h) = L(R) - L(model), R = best of {L2, L2c} per horizon at R1-aggregate level, re-chosen per replicate; labels C1_BAT_REF / C1_NE_BAT_PAS_REF / C1_INDETERMINE; tranche verdict = leading system",
               "rho": "aggregate and per family on RHO_FAMS; unstable if denominator CI contains 0 or lower bound < 0.02",
               "descriptive": ["all 5 ensembles (incl. C.2a N=100) on CEVAL and DIAG", "scaling N=100 vs 1000", "absolute losses L_model, L2, L2c, L4 per family/horizon"],
               "bootstrap": {"B": B, "seed": "key('HOWM2','C1','bootstrap') mod 2^31", "cluster": "establishment"}}}
    (EV / "F_C1.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"leading_system": out["leading_system"], "weights": len(weights)}, indent=1))
    return 0


_MODELS: dict = {}


def _models():
    import torch

    from hospitalos.howm2 import c1

    if not _MODELS:
        f1 = json.loads((EV / "F_C1.json").read_text())
        for system, N in ENSEMBLES:
            mem = []
            for s in c1.SEEDS:
                p = c1.run_dir(system, N, s) / "best.pt"
                if sha(p) != f1["weights"][f"{system}:{N}:{s}"]["best.pt"]:
                    raise RuntimeError(f"weights differ from F-C1: {p}")
                m = c1.new_model(system, c1.b0(), s)
                m.load_state_dict(torch.load(p, weights_only=True)["model"])
                m.eval()
                mem.append(m)
            _MODELS[(system, N)] = mem
    return _MODELS


def l2c_acc(ep, origins) -> dict:
    import howm2_a2_l2c as L

    from hospitalos.howm.heads import BIN_MIN
    from hospitalos.howm2 import data as D

    pr = json.loads((ROOT / "evidence/howm2/L2C_PARAMS.json").read_text())
    sub = {s: (np.array(pr["sub"][s]["base"]), np.array(pr["sub"][s]["tod"]), pr["sub"][s]["tau"]) for s in L.SUB}
    width = BIN_MIN["confirmation"]
    acc = {h: [0.0, 0] for h in HS}
    for H, od, ps in D.origins(ep, origins):
        t = H * 60
        its = od.items.get("confirmation", [])
        if not its:
            continue
        w = L.window_sub(ps, t)
        ds = {s: L.delta(sub[s][0], sub[s][1], w[s], t, sub[s][2], width) for s in L.SUB}
        for h in HS:
            for s in L.SUB:
                sel = [it for it in its if it["ref"].startswith(s + ":")]
                lp = L.item_lp(sub[s][0], sub[s][1], ds[s], sel, t, int(h), width)
                acc[h][0] += float(-lp.sum())
                acc[h][1] += len(lp)
    return acc


def job(arg):
    import torch

    from hospitalos.howm import generator as G
    from hospitalos.howm.predict import ensemble_logscores
    from hospitalos.howm2 import c1
    from hospitalos.howm2 import ladder as LD

    torch.set_num_threads(1)
    part, i = arg
    out_p = FINAL / part / f"{i:03d}.json"
    if out_p.exists():
        return i
    c1.register()
    LD.ORIGINS = list(c1.ORIGINS)  # C1 origins for the ladder references (module attribute, file unchanged)
    t0 = time.time()
    lad = LD.run_establishment(part, i, c1.b0(), pit_levels=())
    acc = lad["acc"]
    ep = G.generate(G.establishment(part, i))
    lc = l2c_acc(ep, c1.ORIGINS)
    acc["L2c"] = {h: {**acc["L2"][h], "confirmation": lc[h]} for h in HS}
    rec = c1.make_record(part, i, c1.b0())
    for (system, N), mem in _models().items():
        preds = [c1.predict_many(m, system, rec, c1.ORIGINS) for m in mem]
        a = {h: {} for h in HS}
        for k, H in enumerate(c1.ORIGINS):
            od = rec["data"].origins[H]
            for h in HS:
                for fam, v in ensemble_logscores([p[k] for p in preds], od, int(h)).items():
                    x = a[h].setdefault(fam, [0.0, 0])
                    x[0] += float(-np.sum(v))
                    x[1] += len(v)
        acc[f"{system}@{N}"] = a
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps({"part": part, "index": i, "mech": lad["mech"], "acc": acc,
                                 "seconds": round(time.time() - t0, 1)}) + "\n")
    return i


def run(part: str, start: int, stop: int, budget: float) -> int:
    t0 = time.time()
    todo = [(part, i) for i in range(start, stop) if not (FINAL / part / f"{i:03d}.json").exists()]
    n = 0
    with get_context("fork").Pool(4) as pool:
        for _ in pool.imap_unordered(job, todo):
            n += 1
            if time.time() - t0 > budget:
                pool.terminate()
                break
    print(json.dumps({"part": part, "done_now": n, "files": len(list((FINAL / part).glob("*.json")))}))
    return 0


# ------------------------------------------------------------------------------ analysis
def fam_mean(r, lv, h, f):
    v = r["acc"][lv][h].get(f, [0.0, 0])
    return v[0] / v[1] if v[1] else float("nan")


def L(r, lv, h, fams):
    vals = [fam_mean(r, lv, h, f) for f in fams]
    vals = [x for x in vals if not math.isnan(x)]
    return float(np.mean(vals)) if vals else float("nan")


def analyse_part(rs: list[dict], seed: int) -> dict:
    n = len(rs)
    rng = np.random.default_rng(seed)
    idx = [rng.integers(0, n, n) for _ in range(B)]
    out = {"n_establishments": n, "ensembles": {}}
    lv_all = ["L0", "L1", "L2", "L2c", "L3", "L4", "L5"] + [f"{s}@{N}" for s, N in ENSEMBLES]

    def ci(a):
        return [float(np.nanquantile(a, 0.025)), float(np.nanquantile(a, 0.975))]

    tab = {h: {f: {lv: float(np.nanmean([fam_mean(r, lv, h, f) for r in rs])) for lv in lv_all} for f in R1_FAMS} for h in HS}
    out["family_table_absolute"] = tab
    for s, N in ENSEMBLES:
        m = f"{s}@{N}"
        res = {}
        for h in HS:
            l2 = np.array([L(r, "L2", h, R1_FAMS) for r in rs])
            l2c = np.array([L(r, "L2c", h, R1_FAMS) for r in rs])
            lm = np.array([L(r, m, h, R1_FAMS) for r in rs])
            best = "L2" if np.nanmean(l2) <= np.nanmean(l2c) else "L2c"
            dc = float(min(np.nanmean(l2), np.nanmean(l2c)) - np.nanmean(lm))
            bs = np.array([min(np.nanmean(l2[i]), np.nanmean(l2c[i])) - np.nanmean(lm[i]) for i in idx])
            # rho on validated families, R chosen at R1-aggregate level per replicate
            def fl(lv, fams):
                return np.array([L(r, lv, h, fams) for r in rs])

            g2, g2c, gm, g4 = fl("L2", RHO_FAMS), fl("L2c", RHO_FAMS), fl(m, RHO_FAMS), fl("L4", RHO_FAMS)
            pick = lambda ii: (g2 if np.nanmean(l2[ii]) <= np.nanmean(l2c[ii]) else g2c)  # noqa: E731
            num_b = np.array([np.nanmean(pick(i)[i]) - np.nanmean(gm[i]) for i in idx])
            den_b = np.array([np.nanmean(pick(i)[i]) - np.nanmean(g4[i]) for i in idx])
            allidx = np.arange(n)
            num, den = float(np.nanmean(pick(allidx)) - np.nanmean(gm)), float(np.nanmean(pick(allidx)) - np.nanmean(g4))
            den_ci = ci(den_b)
            unstable = bool(den_ci[0] <= 0 <= den_ci[1] or den_ci[0] < DELTA_ID)
            fam_rho = {}
            for f in RHO_FAMS:
                a2, a2c, am, a4 = (np.array([fam_mean(r, lv, h, f) for r in rs]) for lv in ("L2", "L2c", m, "L4"))
                pf = lambda ii, a2=a2, a2c=a2c: (a2 if np.nanmean(l2[ii]) <= np.nanmean(l2c[ii]) else a2c)  # noqa: E731
                nb = np.array([np.nanmean(pf(i)[i]) - np.nanmean(am[i]) for i in idx])
                db = np.array([np.nanmean(pf(i)[i]) - np.nanmean(a4[i]) for i in idx])
                nn_, dd_ = float(np.nanmean(pf(allidx)) - np.nanmean(am)), float(np.nanmean(pf(allidx)) - np.nanmean(a4))
                dci = ci(db)
                fam_rho[f] = {"L_model": float(np.nanmean(am)), "L2": float(np.nanmean(a2)), "L2c": float(np.nanmean(a2c)),
                              "L4": float(np.nanmean(a4)), "gain": nn_, "gain_ci95": ci(nb), "denominator": dd_,
                              "denominator_ci95": dci, "rho": nn_ / dd_ if dd_ else None,
                              "rho_ci95": ci(nb / np.where(db == 0, np.nan, db)),
                              "unstable": bool(dci[0] <= 0 <= dci[1] or dci[0] < DELTA_ID)}
            res[h] = {"reference": best, "L_model": float(np.nanmean(lm)), "L2": float(np.nanmean(l2)), "L2c": float(np.nanmean(l2c)),
                      "Delta_C": dc, "Delta_C_ci95": ci(bs),
                      "rho_aggregate": {"gain": num, "gain_ci95": ci(num_b), "denominator": den, "denominator_ci95": den_ci,
                                        "rho": num / den if den else None, "rho_ci95": ci(num_b / np.where(den_b == 0, np.nan, den_b)),
                                        "unstable": unstable},
                      "rho_by_family": fam_rho}
        lo = [res[h]["Delta_C_ci95"][0] for h in ("6", "24")]
        hi = [res[h]["Delta_C_ci95"][1] for h in ("6", "24")]
        verdict = "C1_BAT_REF" if all(x > 0 for x in lo) else ("C1_NE_BAT_PAS_REF" if all(x < 0 for x in hi) else "C1_INDETERMINE")
        amb = all((res[h]["rho_aggregate"]["rho"] or -1) >= 0.5 for h in ("6", "24"))
        out["ensembles"][m] = {"by_horizon": res, "verdict_label_if_eligible": verdict,
                               "eligible_for_verdict": s in VERDICT_SYSTEMS and N == 1000,
                               "ambition": "AMBITION_ATTEINTE" if amb else "AMBITION_NON_ATTEINTE"}
    return out


def analyse() -> int:
    from hospitalos.howm.keys import key

    f1 = json.loads((EV / "F_C1.json").read_text())
    seed = int(key("HOWM2", "C1", "bootstrap") % (2**31))
    out = {"norm": "NORME_C1_PALIER1", "f_c1_sha256": sha(EV / "F_C1.json"), "leading_system": f1["leading_system"]}
    for part in ("HOWM2_CEVAL", "HOWM2_DIAG"):
        rs = [json.loads(p.read_text()) for p in sorted((FINAL / part).glob("*.json"))]
        out[part] = analyse_part(rs, seed)
    ce = out["HOWM2_CEVAL"]["ensembles"]
    out["verdicts"] = {s: ce[f"{s}@1000"]["verdict_label_if_eligible"] for s in VERDICT_SYSTEMS}
    out["verdicts"]["C.2a"] = "NO_VERDICT (N=1000 not executed: budget; signalled before training)"
    lead = f1["leading_system"]
    out["tranche_verdict"] = ce[f"{lead}@1000"]["verdict_label_if_eligible"] if lead else "NO_VERDICT"
    out["scope"] = "forecasting on synthetic HOWM-1 only; not a decision advantage; not real hospitals"
    (EV / "RESULTS_C1_P1.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"tranche_verdict": out["tranche_verdict"], "verdicts": out["verdicts"], "leading": lead,
                      "summary": {m: {h: [round(v["by_horizon"][h]["Delta_C"], 4), [round(x, 4) for x in v["by_horizon"][h]["Delta_C_ci95"]],
                                          v["by_horizon"][h]["reference"]] for h in HS} for m, v in ce.items()}}, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--part")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--stop", type=int, default=10**6)
    ap.add_argument("--budget", type=float, default=420.0)
    a = ap.parse_args()
    return {"select": select, "freeze": freeze, "analyse": analyse}.get(a.cmd, lambda: run(a.part, a.start, a.stop, a.budget))()


if __name__ == "__main__":
    raise SystemExit(main())
