#!/usr/bin/env python3
"""Decision n.8 pilot models (PROTOCOLE_PILOTE_W s.5-8).

D (direct reference): cost(x, a) = base(x) + effect(x, a); base = Ridge(alpha=10) on public inputs fitted to the
  mean cost of 'none'; effect = one of 4 configurations fitted to paired effects mean_k(C_a,k - C_none,k).
W (learned dynamics): encoder MLP(public inputs) -> h0 (latent 64); GRU transition over 84 steps of 2 h driven
  ONLY by the exogenous step schedule (action, calendar, clock) derived from the descriptors; heads -> 30 state
  variables (standardised) and 2 per-unit step costs (softplus); plan cost = sum of predicted step costs.
  No observation, no true future state, no teacher forcing during a rollout.
Both receive exactly the same variables: public S0+S1+S2 at the origin, the calendar descriptor and the action
descriptor (W expands the two descriptors deterministically into the step schedule)."""

from __future__ import annotations

import glob
import hashlib
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
EV = ROOT / "evidence/howm2_bfrag2w"
MD = EV / "models"
LAT = 64
LAMBDA_CUM, LAMBDA_EFF = 1.0, 5.0
D_CONFIGS = [("ridge_inter", 10.0), ("ridge_inter", 1000.0), ("hgb", 3), ("hgb", 5)]


def feature_names() -> list[str]:
    return json.loads((ROOT / "evidence/howm2_bfrag2/LEARN.json").read_text())["feature_names"]["S2"]


FN = None
CAL = ("c_has_drop", "c_drop_start_h", "c_drop_end_h", "c_drop_minus")
ADESC = ("a_none", "a_coord", "a_reinf", "a_res_cl", "a_res_tr", "a_intensity", "a_start_h", "a_dur_h", "a_compat_h", "a_staff_h")


def xvec(rec: dict) -> np.ndarray:
    global FN
    FN = FN or feature_names()
    f = rec["inputs"]["S0"] | rec["inputs"]["S1"] | rec["inputs"]["S2"]
    return np.array([f[n] for n in FN] + [rec["calendar"][k] for k in CAL], np.float64)


def adesc(a: dict) -> np.ndarray:
    return np.array([a["desc"][k] for k in ADESC], np.float64)


def schedules(rec: dict) -> np.ndarray:
    from hospitalos.bfrag2w import core_w as W
    from hospitalos.howm.world import TPH

    t0 = rec["decision_hour"] * TPH
    return np.stack([W.step_schedule(a["desc"], rec["calendar"], t0) for a in rec["actions"]])


# ------------------------------------------------------------------------------ data
def load_train():
    recs, st, co = [], [], []
    for f in sorted(glob.glob(str(EV / "runs/train/*.json"))):
        r = json.loads(Path(f).read_text())
        z = np.load(f[:-5] + ".npz")
        recs.append(r)
        st.append(z["states"])
        co.append(z["costs"])
    return recs, np.stack(st), np.stack(co)  # [N,10,K,84,30], [N,10,K,84,2]


def load_val():
    """VAL-S (B-FRAG 2 VAL partition, structures 0-17): decision-origin public inputs and the true evaluation of
    all 10 actions (E = 8, recorded). Selection only."""
    import bfrag2_lib as L
    from hospitalos.bfrag2 import core2 as C
    from hospitalos.bfrag2w import core_w as W
    from hospitalos.howm.world import TPH

    out = []
    for ep in L.load("S", "BF2_VAL"):
        hd = ep["decision"]["hour"]
        o = next(o for o in ep["origins"] if o["hour"] == hd)
        w = W.structure("BF2_VAL", ep["structure"])
        t0 = hd * TPH
        acts = C.catalogue(t0)
        assert [a["id"] for a in acts] == [a["id"] for a in ep["decision"]["actions"]]
        out.append({"structure": ep["structure"], "episode": ep["episode"], "decision_hour": hd,
                    "inputs": {"S0": o["S0"], "S1": o["S1"], "S2": o["S2"]}, "calendar": W.calendar_descriptor(w.drop, t0),
                    "actions": [{"id": a["id"], "staff_hours": a["staff_hours"], "desc": W.action_descriptor(a, t0)} for a in acts],
                    "true_loss": L.eval_loss(ep).tolist()})
    return out


def choose(costs, recs_actions) -> int:
    return int(min(range(len(costs)), key=lambda i: (round(float(costs[i]), 6), recs_actions[i]["staff_hours"], i)))


def decision_loss(val, pred_fn) -> float:
    by = {}
    for v in val:
        c = choose(pred_fn(v), v["actions"])
        by.setdefault(v["structure"], []).append(v["true_loss"][c])
    return float(np.mean([np.mean(x) for x in by.values()]))


def effect_rmse(val, pred_fn) -> float:
    e = []
    for v in val:
        p, t = np.array(pred_fn(v)), np.array(v["true_loss"])
        e.append(((p - p[0]) - (t - t[0]))[1:])
    return float(np.sqrt(np.mean(np.concatenate(e) ** 2)))


# ------------------------------------------------------------------------------ D
class DModel:
    def __init__(self, cfg):
        self.cfg = cfg

    def _phi(self, X, A):
        Xs = (X - self.mu) / self.sd
        if self.cfg[0] == "ridge_inter":
            return np.concatenate([Xs, A, (A[:, :, None] * Xs[:, None, :]).reshape(len(X), -1)], 1)
        return np.concatenate([X, A], 1)

    def fit(self, X, A, eff, base_y):
        from sklearn.ensemble import HistGradientBoostingRegressor
        from sklearn.linear_model import Ridge

        self.mu, self.sd = X.mean(0), X.std(0) + 1e-6
        Xs = (X - self.mu) / self.sd
        self.base = Ridge(alpha=10.0).fit(Xs[::10], base_y[::10])  # one row per origin (rows are origin-major x 10 actions)
        if self.cfg[0] == "ridge_inter":
            self.eff = Ridge(alpha=self.cfg[1]).fit(self._phi(X, A), eff)
        else:
            self.eff = HistGradientBoostingRegressor(max_depth=self.cfg[1], learning_rate=0.05, max_iter=300, min_samples_leaf=20,
                                                     l2_regularization=1.0, early_stopping=False, random_state=0).fit(self._phi(X, A), eff)
        return self

    def predict(self, x, A):
        X = np.repeat(x[None], len(A), 0)
        e = self.eff.predict(self._phi(X, A))
        e = e - e[0] if A[0, 0] == 1 else e  # 'none' (first action) has effect 0 by definition
        return (self.base.predict(((x - self.mu) / self.sd)[None])[0] + e).tolist()


def d_rows(recs):
    X, A, eff, base = [], [], [], []
    for r in recs:
        x = xvec(r)
        c = np.array([[t["wait_patient_min"] for t in row] for row in r["totals"]])  # [10, K]
        for i, a in enumerate(r["actions"]):
            X.append(x)
            A.append(adesc(a))
            eff.append(float((c[i] - c[0]).mean()))
            base.append(float(c[0].mean()))
    return np.array(X), np.array(A), np.array(eff), np.array(base)


def train_d() -> dict:
    recs, _s, _c = load_train()
    val = load_val()
    X, A, eff, base = d_rows(recs)
    res = {}
    for cfg in D_CONFIGS:
        t = time.time()
        m = DModel(cfg).fit(X, A, eff, base)
        sec = time.time() - t
        fn = lambda v, m=m: m.predict(xvec(v), np.array([adesc(a) for a in v["actions"]]))  # noqa: E731
        blob = pickle.dumps(m)
        name = f"D_{cfg[0]}_{cfg[1]}"
        (MD / f"{name}.pkl").write_bytes(blob)
        res[name] = {"cfg": list(cfg), "fit_seconds": sec, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
                     "val_decision_loss": decision_loss(val, fn), "val_effect_rmse": effect_rmse(val, fn)}
    best = min(res, key=lambda k: (round(res[k]["val_decision_loss"], 6), res[k]["val_effect_rmse"]))
    return {"configs": res, "selected": best, "train_rows": int(len(X)), "train_origins": len(recs), "val_decisions": len(val)}


# ------------------------------------------------------------------------------ W
def make_w(n_in: int, n_u: int = 8, n_state: int = 30):
    import torch
    from torch import nn

    class WNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.enc = nn.Sequential(nn.Linear(n_in, LAT), nn.Tanh(), nn.Linear(LAT, LAT), nn.Tanh())
            self.cell = nn.GRUCell(n_u, LAT)
            self.state = nn.Linear(LAT, n_state)
            self.cost = nn.Linear(LAT, 2)

        def forward(self, x0, sched):
            """x0 [B, n_in] public inputs; sched [B, 84, n_u] exogenous schedule. Open-loop rollout."""
            h = self.enc(x0)
            S, Cc = [], []
            for t in range(sched.shape[1]):
                h = self.cell(sched[:, t], h)
                S.append(self.state(h))
                Cc.append(torch.nn.functional.softplus(self.cost(h)))
            return torch.stack(S, 1), torch.stack(Cc, 1)

    return WNet()


def w_norm(recs, states, costs):
    X = np.stack([xvec(r) for r in recs])
    st = states.reshape(-1, states.shape[-1])
    tot = costs.sum((-1, -2))  # [N,10,K]
    eff = (tot - tot[:, :1]).mean(2)[:, 1:]
    return {"x_mu": X.mean(0), "x_sd": X.std(0) + 1e-6, "s_mu": st.mean(0), "s_sd": st.std(0) + 1e-6,
            "c_scale": float(costs.std() + 1e-6), "tot_scale": float(tot.std() + 1e-6), "eff_scale": float(eff.std() + 1e-6)}


def w_predict_costs(net, norm, recs_like) -> np.ndarray:
    import torch

    X = np.stack([(xvec(r) - norm["x_mu"]) / norm["x_sd"] for r in recs_like])
    U = np.stack([schedules(r) for r in recs_like])  # [B,10,84,8]
    B, NA = U.shape[:2]
    with torch.no_grad():
        x0 = torch.tensor(np.repeat(X, NA, 0), dtype=torch.float32)
        _s, c = net(x0, torch.tensor(U.reshape(B * NA, *U.shape[2:]), dtype=torch.float32))
    return (c.sum((1, 2)).numpy() * norm["c_scale"]).reshape(B, NA)


def train_w(seed: int, wall_cap: float = 140.0, max_epochs: int = 400, eval_every: int = 2, patience: int = 10) -> dict:
    import torch

    torch.set_num_threads(1)
    torch.manual_seed(seed)
    np.random.seed(seed)
    recs, states, costs = load_train()
    val = load_val()
    norm = w_norm(recs, states, costs)
    X = torch.tensor(np.stack([(xvec(r) - norm["x_mu"]) / norm["x_sd"] for r in recs]), dtype=torch.float32)
    U = torch.tensor(np.stack([schedules(r) for r in recs]), dtype=torch.float32)  # [N,10,84,8]
    S = torch.tensor((states - norm["s_mu"]) / norm["s_sd"], dtype=torch.float32)  # [N,10,K,84,30]
    Cs = torch.tensor(costs / norm["c_scale"], dtype=torch.float32)  # [N,10,K,84,2]
    tot = Cs.sum((-1, -2))  # [N,10,K]
    eff_t = (tot - tot[:, :1]).mean(2)  # [N,10]
    N, NA, K = S.shape[:3]
    net = make_w(X.shape[1])
    n_params = sum(p.numel() for p in net.parameters())
    opt = torch.optim.Adam(net.parameters(), lr=2e-3, weight_decay=1e-5)
    rng = np.random.default_rng(seed)
    curve, best, best_state, bad, t0, ep = [], None, None, 0, time.time(), 0
    tot_k = norm["c_scale"] / norm["tot_scale"]
    eff_k = norm["c_scale"] / norm["eff_scale"]
    stop = "max_epochs"
    for ep in range(1, max_epochs + 1):
        net.train()
        perm = rng.permutation(N)
        tl = []
        for b in range(0, N, 16):
            idx = perm[b:b + 16]
            nb = len(idx)
            x0 = X[idx].repeat_interleave(NA, 0)
            sh, ch = net(x0, U[idx].reshape(nb * NA, 84, -1))
            sh, ch = sh.reshape(nb, NA, 1, 84, -1), ch.reshape(nb, NA, 1, 84, 2)
            l_state = ((sh - S[idx]) ** 2).mean()
            l_cost = ((ch - Cs[idx]) ** 2).mean()
            th = ch.sum((-1, -2))  # [nb,NA,1]
            l_cum = (((th - tot[idx]) * tot_k) ** 2).mean()
            eh = (th - th[:, :1])[..., 0]
            l_eff = (((eh - eff_t[idx]) * eff_k)[:, 1:] ** 2).mean()
            loss = l_state + l_cost + LAMBDA_CUM * l_cum + LAMBDA_EFF * l_eff
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
            tl.append([float(loss), float(l_state), float(l_cost), float(l_cum), float(l_eff)])
        row = {"epoch": ep, "train": np.mean(tl, 0).tolist(), "seconds": time.time() - t0}
        if ep % eval_every == 0:
            net.eval()
            P = w_predict_costs(net, norm, val)
            fn = lambda v, P=P, idx={id(v): i for i, v in enumerate(val)}: P[idx[id(v)]]  # noqa: E731
            row["val_decision_loss"] = decision_loss(val, fn)
            row["val_effect_rmse"] = effect_rmse(val, fn)
            key = (round(row["val_decision_loss"], 6), row["val_effect_rmse"])
            if best is None or key < best[0]:
                best, bad = (key, ep), 0
                best_state = {k: v.clone() for k, v in net.state_dict().items()}
            else:
                bad += 1
        curve.append(row)
        if ep % eval_every == 0 and bad >= patience:
            stop = "patience"
            break
        if time.time() - t0 > wall_cap:
            stop = "wall_cap"
            break
    last_state = {k: v.clone() for k, v in net.state_dict().items()}
    torch.save({"state": best_state, "norm": norm, "n_in": int(X.shape[1]), "seed": seed, "epoch": best[1]}, MD / f"W_seed{seed}_best.pt")
    torch.save({"state": last_state, "norm": norm, "n_in": int(X.shape[1]), "seed": seed, "epoch": ep}, MD / f"W_seed{seed}_last.pt")
    return {"seed": seed, "n_params": int(n_params), "selected_epoch": best[1], "selected_val": list(best[0]), "last_epoch": ep, "stop": stop,
            "curve": curve, "train_origins": N, "K": K, "seconds": time.time() - t0,
            "sha256_best": hashlib.sha256((MD / f"W_seed{seed}_best.pt").read_bytes()).hexdigest()}


def load_w(seed: int, which: str = "best"):
    import torch

    ck = torch.load(MD / f"W_seed{seed}_{which}.pt", weights_only=False)
    net = make_w(ck["n_in"])
    net.load_state_dict(ck["state"])
    net.eval()
    return net, ck["norm"]


def predict_costs(rec: dict) -> dict:
    """Frozen systems (FREEZE_PILOT.json): D selected configuration, W ensemble of the 3 seeds' VAL-selected
    checkpoints (main) and each seed. Public inputs and descriptors only."""
    fr = json.loads((EV / "FREEZE_PILOT.json").read_text())
    d = pickle.loads((MD / f"{fr['D_selected']}.pkl").read_bytes())
    out = {"D": d.predict(xvec(rec), np.array([adesc(a) for a in rec["actions"]]))}
    seeds = []
    for s in fr["W_seeds"]:
        net, norm = load_w(s)
        seeds.append(w_predict_costs(net, norm, [rec])[0].tolist())
    out["W_seeds"] = seeds
    out["W"] = np.mean(seeds, 0).tolist()
    return out


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train_d", "train_w"])
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--wall", type=float, default=140.0)
    a = ap.parse_args()
    MD.mkdir(parents=True, exist_ok=True)
    if a.cmd == "train_d":
        r = train_d()
        (EV / "LEARN_D.json").write_text(json.dumps(r, indent=1) + "\n")
        print(json.dumps(r, indent=1))
    else:
        from multiprocessing import get_context

        seeds = [int(x) for x in a.seeds.split(",")]
        with get_context("fork").Pool(len(seeds)) as pool:
            rs = pool.starmap(train_w, [(s, a.wall) for s in seeds])
        (EV / "LEARN_W.json").write_text(json.dumps(rs, indent=1) + "\n")
        print(json.dumps([{k: v for k, v in r.items() if k != "curve"} for r in rs], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
