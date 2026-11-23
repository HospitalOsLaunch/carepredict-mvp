#!/usr/bin/env python3
"""HOWM-INT-1 SF1 diagnostic (internal task; TRAIN/VAL only).

(a) capacity to fit a small TRAIN set of SF1 (cleaning) situations with a fresh W-S (implementation / optimisation
    check, fixed 1 500 updates); (b) effect errors TRAIN vs VAL by family for a trained W and for D-ridge
    (generalisation); (c) best-action errors (regret) and gap errors between the true best and the chosen action;
(d) drift with the horizon (state error per 2-h step, 2-unit VAL); (e) coverage of families, regimes, provenances
and action kinds in TRAIN.   diag_sf1.py --w RUN [--w RUN ...] --d D_RUN/NAME --tier 1"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
import argparse  # noqa: E402
import collections  # noqa: E402
import json  # noqa: E402
import pickle  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import torch  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts/int1"))
import train_d  # noqa: E402
import train_w as TW  # noqa: E402
from hospitalos.howmint import data as DA  # noqa: E402
from hospitalos.howmint import models as MO  # noqa: E402
from hospitalos.howmint import planners as PL  # noqa: E402

S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")


def load_w(run):
    rd = S / "int1_runs" / run
    cfg = json.loads((rd / "config.json").read_text())
    m = MO.GraphWM(cfg["d"])
    m.load_state_dict(torch.load(rd / "best.pt", weights_only=False)["model"])
    m.eval()
    return m, {k: (v.item() if v.ndim == 0 else v) for k, v in np.load(rd / "norm.npz").items()}


def w_pred(models, st, s):
    L = DA.LOOKAHEAD_STEPS[s["n"]]
    t = DA.tensors(s, st)
    with torch.no_grad():
        outs = [m(t["unit"], t["res"], t["glob"], t["ur_mask"], t["uu"], t["U"][:, :L], t["R"][:, :L], t["C"][:, :L], t["beds"], steps=L) for m in models]
    return np.mean([(o[1].sum((1, 2)) * st["cost_s"]).numpy() for o in outs], 0), outs


def errs(pred, s):
    L = DA.LOOKAHEAD_STEPS[s["n"]]
    true = s["costs"][:, :, :L].sum((2, 3)).mean(1)
    i, j = int(np.argmin(pred)), int(np.argmin(true))
    return {"eff_err": ((pred - pred[0]) - (true - true[0]))[1:], "regret": float(true[i] - true[j]), "rel": float((true[i] - true[j]) / max(1.0, true[0])),
            "gap_err": float(abs((pred[i] - pred[j]) - (true[i] - true[j])))}


def summarise(rows):
    if not rows:
        return None
    return {"situations": len(rows), "effect_rmse": float(np.sqrt(np.mean(np.concatenate([r["eff_err"] for r in rows]) ** 2))),
            "regret": float(np.mean([r["regret"] for r in rows])), "rel_regret": float(np.mean([r["rel"] for r in rows])),
            "gap_err": float(np.mean([r["gap_err"] for r in rows]))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", action="append", required=True)
    ap.add_argument("--d", required=True)
    ap.add_argument("--tier", type=int, default=1)
    ap.add_argument("--fit-updates", type=int, default=1500)
    a = ap.parse_args()
    torch.set_num_threads(1)
    tr = DA.situations(DA.load(S / "int1_corpus", "INT_TRAIN", list(range(1000))))
    va = DA.situations(DA.load(S / "int1_corpus", "INT_VAL", list(range(300))))
    ms = [load_w(r) for r in a.w]
    models, st = [m for m, _ in ms], ms[0][1]
    dm = train_d.load_d_model(S / "int1_runs" / a.d.split("/")[0] / f"{a.d.split('/')[1]}.pkl")
    out = {"W": a.w, "D": a.d}
    # (b)(c) by family, TRAIN (first 600 2-unit situations) vs VAL
    for name, sits in (("train", [s for s in tr if s["n"] == 2][:600]), ("val", [s for s in va if s["n"] == 2])):
        by = collections.defaultdict(lambda: {"W": [], "D": []})
        for s in sits:
            pw, _ = w_pred(models, st, s)
            g = {"unit": s["unit"][0], "res": s["res"][0], "glob": s["glob"][0]}
            L = DA.LOOKAHEAD_STEPS[2]
            pd = dm.predict(np.stack([PL.fixed_features(g, {"U": s["U"][i], "R": s["R"][i]}, s["desc"][i], L) for i in range(len(s["desc"]))]))
            for k, p in (("W", pw), ("D", pd)):
                e = errs(p, s)
                by[s["family"]][k].append(e)
                by["ALL"][k].append(e)
        out[f"by_family_{name}"] = {f: {k: summarise(v) for k, v in d.items()} for f, d in by.items()}
    # (d) drift with horizon on 2-unit VAL (state error per step, standardised)
    drift = []
    for s in [x for x in va if x["n"] == 2][:200]:
        t = DA.tensors(s, st)
        with torch.no_grad():
            sh, _c, _r = models[0](t["unit"], t["res"], t["glob"], t["ur_mask"], t["uu"], t["U"], t["R"], t["C"], t["beds"], steps=36)
        drift.append((((sh - t["states"].mean(1)) / torch.tensor(st["st_s"])) ** 2).mean((0, 2, 3)).numpy())
    out["drift_state_mse_per_2h_step"] = np.mean(drift, 0).tolist()
    # (e) coverage
    cov = {"family": collections.Counter(), "regime": collections.Counter(), "provenance": collections.Counter(), "kind_a0": collections.Counter()}
    for s in tr:
        cov["family"][s["family"].split("_")[0] if s["n"] > 2 else s["family"]] += 1
        cov["regime"][s["regime"]] += 1
        cov["provenance"][s["provenance"]] += 1
        for sq in s["seqs"]:
            cov["kind_a0"][(sq[0] or "none").split("_")[0]] += 1
    out["coverage_train"] = {k: dict(v) for k, v in cov.items()}
    # (a) small-set fit of SF1 situations (fresh W-S, seed 0)
    sf1 = [s for s in tr if s["family"] == "SF1_cleaning_window"][:16]
    torch.manual_seed(0)
    np.random.seed(0)
    m = MO.GraphWM(128)
    opt = torch.optim.Adam(m.parameters(), lr=1e-3)
    curve = []
    for u in range(a.fit_updates):
        pick = np.random.choice(len(sf1), 4, replace=False)
        loss, parts = TW.batch_loss(m, [sf1[i] for i in pick], st, 20000)  # full 36-step horizon (slots w3/w4 lie beyond 24 h)
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
        opt.step()
        if (u + 1) % 300 == 0:
            m.eval()
            e = summarise([errs(w_pred([m], st, s)[0], s) for s in sf1])
            m.train()
            curve.append({"upd": u + 1, "loss": float(loss), "eff": parts["eff"], **e})
    out["small_set_fit_SF1"] = {"situations": len(sf1), "curve": curve, "note": "fit of 16 TRAIN SF1 situations, full 36-step horizon (first run used the 12-step stage: diagnostic defect, superseded)"}
    (ROOT / "evidence/howm_int1/DIAG_SF1.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps({"val_ALL": out["by_family_val"].get("ALL"), "val_SF1": out["by_family_val"].get("SF1_cleaning_window"),
                      "train_SF1": out["by_family_train"].get("SF1_cleaning_window"), "fit": curve[-1] if curve else None,
                      "drift": [round(x, 3) for x in out["drift_state_mse_per_2h_step"][::6]]}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
