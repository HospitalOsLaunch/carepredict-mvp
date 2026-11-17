#!/usr/bin/env python3
"""HOWM-INT-1 direct references D (same corpus, same public inputs and sequence descriptors as W).

    train_d.py --tier 1|2 --which ridge|hgb|dset [--budget 450] [--seed 0]

ridge  base Ridge(alpha=10) on situation features + effect Ridge(alpha in {1, 100}) on [x, desc, desc x pooled]
hgb    base HGB + effect HGB (max_depth in {4, 8}, 300 iterations, min_samples_leaf 40, l2 1)
dset   DeepSets direct cost predictor (base + paired-effect heads), capacity comparable to W-S; trained on the
       cumulative lookahead cost and paired effects only (no trajectory targets); resumable, VAL-selected
Targets: lookahead cumulative wait (mean over the row's futures): base = C(none,none) of the situation,
effect = C(seq) - C(none,none). TRAIN-only normalisation. Selection among configurations on VAL decision regret
(2-unit situations), tie -> effect RMSE (rule fixed before training)."""

import os
import sys

os.environ.setdefault("OMP_NUM_THREADS", "4")
import argparse  # noqa: E402
import json  # noqa: E402
import pickle  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts/int1"))
from hospitalos.howmint import data as DA  # noqa: E402
from hospitalos.howmint import planners as PL  # noqa: E402

S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")
CORPUS, OUT = S / "int1_corpus", S / "int1_runs"
TIER = {1: 1000, 2: 10000}


def rows(sits):
    X, base, eff, grp = [], [], [], []
    for gi, s in enumerate(sits):
        n, Ls = s["n"], DA.LOOKAHEAD_STEPS[s["n"]]
        cum = s["costs"][:, :, :Ls].sum((2, 3)).mean(1)
        g = {"unit": s["unit"][0], "res": s["res"][0], "glob": s["glob"][0]}
        for i in range(len(s["desc"])):
            X.append(PL.fixed_features(g, {"U": s["U"][i], "R": s["R"][i]}, s["desc"][i], Ls))
            base.append(cum[0])
            eff.append(cum[i] - cum[0])
            grp.append(gi)
    return np.array(X), np.array(base), np.array(eff), np.array(grp)


class BaseEffect:
    def __init__(self, base, eff, mu, sd):
        self.base, self.eff, self.mu, self.sd = base, eff, mu, sd

    def predict(self, X):
        Z = (X - self.mu) / self.sd
        return self.base.predict(Z) + self.eff.predict(Z)


def val_metrics(score_rows, sits):
    from scipy.stats import spearmanr

    out = {}
    for n in sorted({s["n"] for s in sits}):
        rr, er, rho = [], [], []
        for s in [x for x in sits if x["n"] == n]:
            p = score_rows(s)
            t = s["costs"][:, :, : DA.LOOKAHEAD_STEPS[n]].sum((2, 3)).mean(1)
            i = PL.choose(p, [[{"staff_hours": float(d[9]) if len(d) > 9 else 0.0}] for d in s["desc"]])
            rr.append((t[i] - t.min()) / max(1.0, t[0]))
            er.append(((p - p[0]) - (t - t[0]))[1:])
            r = spearmanr(p, t).statistic
            rho.append(0.0 if np.isnan(r) else r)
        out[str(n)] = {"situations": len(rr), "rel_regret": float(np.mean(rr)), "effect_rmse": float(np.sqrt(np.mean(np.concatenate(er) ** 2))),
                       "spearman": float(np.mean(rho))}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", type=int, default=1)
    ap.add_argument("--which", default="ridge")
    ap.add_argument("--budget", type=float, default=450.0)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    t0 = time.time()
    tr = DA.situations(DA.load(CORPUS, "INT_TRAIN", list(range(TIER[a.tier]))))
    va = DA.situations(DA.load(CORPUS, "INT_VAL", list(range(300))))
    od = OUT / f"D_t{a.tier}_{a.which}"
    od.mkdir(parents=True, exist_ok=True)
    res = {}
    if a.which in ("ridge", "hgb"):
        from sklearn.ensemble import HistGradientBoostingRegressor
        from sklearn.linear_model import Ridge

        X, yb, ye, _g = rows(tr)
        mu, sd = X.mean(0), X.std(0) + 1e-6
        Z = (X - mu) / sd
        for h in ((1.0, 100.0) if a.which == "ridge" else (4, 8)):
            ts = time.time()
            if a.which == "ridge":
                desc = Z[:, 54 * 3 + 30 + 8: 54 * 3 + 30 + 8 + 20]
                inter = (desc[:, :, None] * Z[:, None, :54]).reshape(len(Z), -1)
                base = Ridge(alpha=10.0).fit(Z, yb)

                class RI:
                    def __init__(self, m):
                        self.m = m

                    def predict(self, Zx):
                        d = Zx[:, 54 * 3 + 30 + 8: 54 * 3 + 30 + 8 + 20]
                        return self.m.predict(np.concatenate([Zx, (d[:, :, None] * Zx[:, None, :54]).reshape(len(Zx), -1)], 1))
                eff = RI(Ridge(alpha=h).fit(np.concatenate([Z, inter], 1), ye))
            else:
                base = HistGradientBoostingRegressor(max_depth=h, max_iter=300, min_samples_leaf=40, l2_regularization=1.0, random_state=0).fit(Z, yb)
                eff = HistGradientBoostingRegressor(max_depth=h, max_iter=300, min_samples_leaf=40, l2_regularization=1.0, random_state=0).fit(Z, ye)
            m = BaseEffect(base, eff, mu, sd)
            sec = time.time() - ts

            def score_rows(s, m=m):
                g = {"unit": s["unit"][0], "res": s["res"][0], "glob": s["glob"][0]}
                Ls = DA.LOOKAHEAD_STEPS[s["n"]]
                return m.predict(np.stack([PL.fixed_features(g, {"U": s["U"][i], "R": s["R"][i]}, s["desc"][i], Ls) for i in range(len(s["desc"]))]))
            name = f"{a.which}_{h}"
            blob = pickle.dumps(m)
            (od / f"{name}.pkl").write_bytes(blob)
            res[name] = {"fit_seconds": sec, "bytes": len(blob), "val": val_metrics(score_rows, va), "train_rows": int(len(X))}
    else:
        import torch

        from hospitalos.howmint import models as MO

        torch.set_num_threads(4)
        torch.manual_seed(a.seed)
        np.random.seed(a.seed)
        st = {k: (v.item() if v.ndim == 0 else v) for k, v in np.load(OUT / ("W_t1_S_s0" if a.tier == 1 else "W_t2_S_s0") / "norm.npz").items()}
        net = MO.DSet(160)
        opt = torch.optim.Adam(net.parameters(), lr=1e-3)
        ck = od / "last.pt"
        state = {"upd": 0, "best": None, "curve": [], "bad": 0, "stopped": None}
        if ck.exists():
            c = torch.load(ck, weights_only=False)
            net.load_state_dict(c["net"])
            opt.load_state_dict(c["opt"])
            state = c["state"]
        groups = {}
        for i, s in enumerate(tr):
            groups.setdefault(s["n"], []).append(i)
        sizes = sorted(groups)
        w = np.array([len(groups[n]) for n in sizes], float)
        w /= w.sum()
        while time.time() - t0 < a.budget - 30 and not state["stopped"]:
            n = sizes[np.random.choice(len(sizes), p=w)]
            Ls = DA.LOOKAHEAD_STEPS[n]
            pick = np.random.choice(groups[n], size=4, replace=False)
            loss = 0.0
            for i in pick:
                t = DA.tensors(tr[i], st)
                base, eff = net(t["unit"], t["res"], t["glob"], t["U"][:, :Ls], t["R"][:, :Ls], t["desc"])
                cum = t["costs"][:, :, :Ls].sum((2, 3))
                loss = loss + (((base[:, None] * st["cum_s"] - cum[:1]) / st["cum_s"]) ** 2).mean() \
                    + 5 * ((((eff - eff[0])[:, None] * st["cum_s"] - (cum - cum[:1])) / st["eff_s"]) ** 2)[1:].mean()
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
            state["upd"] += 1
            if state["upd"] % 500 == 0:
                sc = PL.dset_scorer(net, st)

                def score_rows(s, sc=sc):
                    g = {"unit": s["unit"][0], "res": s["res"][0], "glob": s["glob"][0], "uu": s["uu"][0]}
                    Ls_ = DA.LOOKAHEAD_STEPS[s["n"]]
                    return sc(g, [{"U": s["U"][i][:Ls_], "R": s["R"][i][:Ls_], "C": s["C"][i][:Ls_]} for i in range(len(s["desc"]))],
                              list(s["desc"]), s["n"], Ls_)
                ev = val_metrics(score_rows, va)
                key = (ev.get("2", {}).get("rel_regret", 9.0), ev.get("2", {}).get("effect_rmse", 9e9))
                state["curve"].append({"upd": state["upd"], "loss": float(loss), "val": ev})
                if state["best"] is None or key < tuple(state["best"]["key"]):
                    state["best"] = {"upd": state["upd"], "key": list(key), "val": ev}
                    state["bad"] = 0
                    torch.save({"net": net.state_dict(), "upd": state["upd"]}, od / "best.pt")
                else:
                    state["bad"] += 1
                    if state["bad"] >= 8:
                        state["stopped"] = "patience"
        torch.save({"net": net.state_dict(), "opt": opt.state_dict(), "state": state}, ck)
        res["dset"] = {"upd": state["upd"], "stopped": state["stopped"], "best": state["best"], "params": MO.n_params(net)}
    prev = json.loads((od / "result.json").read_text()) if (od / "result.json").exists() else {}
    prev.update(res)
    (od / "result.json").write_text(json.dumps(prev, indent=1, default=float))
    print(json.dumps(res, default=float)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
