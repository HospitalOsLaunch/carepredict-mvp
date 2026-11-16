#!/usr/bin/env python3
"""HOWM-2 A2.L2C (NORM A2 N3, addendum A2-1 s.6): corrected explicit reference L2c.

L2c = L2 (B0-local over the whole public past) with confirmation split into two internal
families (transport, pool offer), each with its own base law, hourly profile and local intercept,
and pool offers included in the local window. Fitted on TRAIN 0-31; tau of each internal family by
the R1 criterion on TRAIN 0-31. Other families identical to L2. Scored as the R1 'confirmation'
family.

    fit        -> evidence/howm2/L2C_PARAMS.json
    score      -> evidence/howm2/l2c/HOWM2_REF/<i>.json (L2c and recomputed L2 confirmation)
    analyse    -> evidence/howm2/L2C_A2.json
"""

from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
PARAMS = ROOT / "evidence/howm2/L2C_PARAMS.json"
OUTD = ROOT / "evidence/howm2/l2c/HOWM2_REF"
HS = (1, 6, 24)
SUB = ("T", "O")


def records(ep) -> dict[str, list]:
    from hospitalos.howm.dataset import _end_index

    first = _end_index(ep.observations)["first"]
    rec = {"T": [], "O": []}
    for ev, _av, kind, subj, _u, v in ep.observations:
        if kind == "transport_requested":
            end = first.get(("transport_accepted", subj))
            rec["T"].append((ev, ev, end[1] if end else None))
        elif kind == "offer_requested" and v.get("source") == "pool":
            end = first.get(("offer_confirmed", subj))
            rec["O"].append((ev, ev, end[1] if end else None))
    return rec


def window_sub(ps, t: int) -> dict[str, list]:
    """Whole-public-past window of each internal family: (start, end_avail|None)."""
    first, avail_end, pool = {}, {}, set()
    for ev, av, kind, subj, _u, v in ps.obs[: ps.i]:
        first.setdefault((kind, subj), ev)
        avail_end.setdefault((kind, subj), av)
        if kind == "offer_requested" and v.get("source") == "pool":
            pool.add(subj)
    w = {"T": [], "O": []}
    for (kind, subj), ev in first.items():
        if kind == "transport_requested":
            w["T"].append((ev, avail_end.get(("transport_accepted", subj))))
        elif kind == "offer_requested" and subj in pool:
            w["O"].append((ev, avail_end.get(("offer_confirmed", subj))))
    return w


def window_l2_conf(ps, t: int) -> list:
    from hospitalos.howm2.ladder import window_long

    return [(s, e) for s, e, _ in window_long(ps, t)["hazard"]["confirmation"]]


def delta(base, tod, items, t, tau, width) -> float:
    from hospitalos.howm.b0 import _newton_1d, _rows, to_bins

    rows = [to_bins(s, s, e, t, width) for s, e in items]
    k, q, y, _ = _rows(rows, width // 15)
    if len(k) == 0:
        return 0.0
    b = base[k] + tod[q]

    def gh(d):
        pr = 1.0 / (1.0 + np.exp(-(b + d)))
        return float(np.sum(y - pr)), float(-np.sum(pr * (1 - pr)))

    return _newton_1d(gh, tau)


def item_lp(base, tod, d, items, t, h, width) -> np.ndarray:
    from hospitalos.howm.b0 import to_bins
    from hospitalos.howm.dataset import DATA_END_MIN
    from hospitalos.howm.heads import hazard_logits, hazard_logprob

    if not items:
        return np.zeros(0)
    cutoff = min(t + 60 * h, DATA_END_MIN)
    bins = [to_bins(it["start"], t, it.get("end_avail"), cutoff, width) for it in items]
    q = np.array([b[0] for b in bins], np.int64)
    logits = hazard_logits(base, tod, np.full(len(items), d), q, width // 15)
    return hazard_logprob(logits, np.array([b[1] for b in bins], np.int64), np.array([b[3] for b in bins], np.int64),
                          np.array([b[2] for b in bins], bool))


def fit() -> int:
    from hospitalos.howm import corpus as C
    from hospitalos.howm.b0 import TAU_GRID, fit_hazard, to_bins
    from hospitalos.howm.dataset import DATA_END_MIN
    from hospitalos.howm.heads import BIN_MIN
    from hospitalos.howm.history import PublicStream

    width = BIN_MIN["confirmation"]
    tr = [C.load("TRAIN", i) for i in range(32)]
    par = {}
    for s in SUB:
        items = [to_bins(a, b, e, DATA_END_MIN, width) for d in tr for a, b, e in records(d["episode"])[s]]
        base, tod = fit_hazard(items, width // 15)
        par[s] = {"base": base, "tod": tod, "n_items": len(items)}
    scores = {s: {tau: [0.0, 0] for tau in TAU_GRID} for s in SUB}
    for d in tr:
        est, ep = d["data"], d["episode"]
        ps = PublicStream(ep.observations)
        for H in sorted(est.origins):
            if (H - 24) % 12:
                continue
            t = H * 60
            ps.advance(t)
            w = window_sub(ps, t)
            its = est.origins[H].items.get("confirmation", [])
            for s in SUB:
                sel = [it for it in its if it["ref"].startswith(s + ":")]
                if not sel:
                    continue
                for tau in TAU_GRID:
                    dd = delta(par[s]["base"], par[s]["tod"], w[s], t, tau, width)
                    lp = item_lp(par[s]["base"], par[s]["tod"], dd, sel, t, 24, width)
                    scores[s][tau][0] += float(np.sum(lp))
                    scores[s][tau][1] += len(lp)
    out = {"rule": "addendum A2-1 s.6", "train": "TRAIN 0-31", "width_min": width, "sub": {}}
    for s in SUB:
        mean = {str(tau): v[0] / max(v[1], 1) for tau, v in scores[s].items()}
        tau = max(TAU_GRID, key=lambda x: mean[str(x)])
        out["sub"][s] = {"base": par[s]["base"].tolist(), "tod": par[s]["tod"].tolist(), "n_items": par[s]["n_items"],
                         "tau": tau, "tau_scores": mean, "n_scored": scores[s][TAU_GRID[0]][1]}
    PARAMS.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({s: {k: v for k, v in out["sub"][s].items() if k not in ("base", "tod")} for s in SUB}, indent=1))
    return 0


def job(i: int) -> int:
    from hospitalos.howm import generator as G
    from hospitalos.howm.b0 import B0Params
    from hospitalos.howm.heads import BIN_MIN
    from hospitalos.howm2 import data as D
    from hospitalos.howm2 import space
    from hospitalos.howm2.ladder import ORIGINS

    space.register()
    pr = json.loads(PARAMS.read_text())
    p = B0Params.from_json(json.loads((ROOT / "evidence/howm1/B0_PARAMS.json").read_text()))
    width = BIN_MIN["confirmation"]
    sub = {s: (np.array(pr["sub"][s]["base"]), np.array(pr["sub"][s]["tod"]), pr["sub"][s]["tau"]) for s in SUB}
    ep = G.generate(G.establishment("HOWM2_REF", i))
    acc = {"L2c": {str(h): [0.0, 0] for h in HS}, "L2_recomputed": {str(h): [0.0, 0] for h in HS},
           "L2c_by_sub": {s: {str(h): [0.0, 0] for h in HS} for s in SUB}}
    for H, od, ps in D.origins(ep, ORIGINS):
        t = H * 60
        its = od.items.get("confirmation", [])
        if not its:
            continue
        w = window_sub(ps, t)
        d2 = delta(p.base["confirmation"], p.tod["confirmation"], window_l2_conf(ps, t), t, p.tau.get("confirmation", 0.35), width)
        ds = {s: delta(sub[s][0], sub[s][1], w[s], t, sub[s][2], width) for s in SUB}
        for h in HS:
            lp2 = item_lp(p.base["confirmation"], p.tod["confirmation"], d2, its, t, h, width)
            a = acc["L2_recomputed"][str(h)]
            a[0] += float(-lp2.sum())
            a[1] += len(lp2)
            for s in SUB:
                sel = [it for it in its if it["ref"].startswith(s + ":")]
                lp = item_lp(sub[s][0], sub[s][1], ds[s], sel, t, h, width)
                for tgt in (acc["L2c"][str(h)], acc["L2c_by_sub"][s][str(h)]):
                    tgt[0] += float(-lp.sum())
                    tgt[1] += len(lp)
    OUTD.mkdir(parents=True, exist_ok=True)
    (OUTD / f"{i:03d}.json").write_text(json.dumps({"index": i, "acc": acc}) + "\n")
    return i


def score() -> int:
    todo = [i for i in range(200) if not (OUTD / f"{i:03d}.json").exists()]
    with get_context("fork").Pool(4) as pool:
        n = len(pool.map(job, todo))
    print(n, "establishments")
    return 0


def analyse() -> int:
    import howm2_analyse as A

    rs = A.load("HOWM2_REF")
    l2c = {json.loads(f.read_text())["index"]: json.loads(f.read_text())["acc"] for f in sorted(OUTD.glob("*.json"))}
    assert len(rs) == len(l2c) == 200
    check = []
    for r in rs:
        i = r["index"]
        r["acc"]["L2c"] = {h: {**r["acc"]["L2"][h], "confirmation": l2c[i]["L2c"][h]} for h in r["acc"]["L2"]}
        for h in ("1", "6", "24"):
            a, b = r["acc"]["L2"][h].get("confirmation", [0, 0]), l2c[i]["L2_recomputed"][h]
            check.append(a[1] == b[1] and abs(a[0] - b[0]) <= 1e-6 * max(1.0, abs(a[0])))
    fams = ("ready", "confirmation", "presence", "arrivals", "care")
    rng = np.random.default_rng(A.SEED)
    n = len(rs)
    res = {}
    for h in A.HS:
        l2 = np.array([A.L(r, "L2", h, fams) for r in rs])
        l2c_ = np.array([A.L(r, "L2c", h, fams) for r in rs])
        l4 = np.array([A.L(r, "L4", h, fams) for r in rs])
        best = "L2" if l2.mean() <= l2c_.mean() else "L2c"
        point = float(min(l2.mean(), l2c_.mean()) - l4.mean())
        bs = []
        for _ in range(A.B):
            i = rng.integers(0, n, n)
            bs.append(min(l2[i].mean(), l2c_[i].mean()) - l4[i].mean())
        res[h] = {"M_pub": point, "ci95": [float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))], "best_reference": best,
                  "L2": float(l2.mean()), "L2c": float(l2c_.mean()), "L4": float(l4.mean())}
    flag = [h for h in ("6", "24") if res[h]["ci95"][0] < A.DELTA_ID]
    table, rho = {}, {}
    for h in A.HS:
        table[h], rho[h] = {}, {}
        for f in ("ready", "transport", "cleaning", "confirmation", "presence", "arrivals", "care"):
            vals = {lv: float(np.nanmean([A.fam_mean(r, lv, h, f) for r in rs])) for lv in (*A.LEVELS, "L2c")}
            table[h][f] = vals
            if f in fams and not math.isnan(vals["L4"]):
                lb = min(vals["L2"], vals["L2c"])
                gap0 = vals["L2"] - vals["L4"]
                rho[h][f] = {"gap_A_L2_minus_L4": gap0, "gap_best_minus_L4": lb - vals["L4"],
                             "rho_remaining_share": (lb - vals["L4"]) / gap0 if gap0 else None}
    par = json.loads(PARAMS.read_text())
    out = {"recomputed_L2_confirmation_matches_ladder": {"checked": len(check), "identical": int(sum(check))},
           "params": {s: {k: v for k, v in par["sub"][s].items() if k not in ("base", "tod")} for s in SUB},
           "M_pub_best_of_L2_L2c": res, "families": list(fams),
           "flag_lower_bound_below_delta_id": flag,
           "C1_rule": "reference of C1's criterion = best of {L2, L2c}" + (" -- FLAG: C1 could no longer discriminate at " + ",".join(flag) if flag else ""),
           "verdict_A_unchanged": "HOWM1_DISCRIMINANT (A2.L2C is an additional measurement)",
           "family_table_REF": table, "rho_f": rho}
    (ROOT / "evidence/howm2/L2C_A2.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "family_table_REF"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit({"fit": fit, "score": score, "analyse": analyse}[sys.argv[1]]())
