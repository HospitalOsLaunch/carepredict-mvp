#!/usr/bin/env python3
"""HOWM-INT-1 W training (resumable; one call = one <= 540-s ledger command).

    train_w.py --run NAME --size S|M --seed k --tier 1|2 [--init RUN] [--ablate no_msg|no_hist] [--budget 450]

Losses (weights fixed before comparative training): per-unit states (standardised), per-step costs, cumulative
lookahead cost, paired action effects (x5: differences to the (none, none) sequence of the same situation and
future), rupture (BCE, x0.5). Horizon curriculum: 12 -> 24 -> 36 steps (2 units; 4/8 units: 12) by update count.
VAL (fixed situations and futures) every --eval-every updates: decision regret, effect RMSE, rank correlation,
state error; selection metric (fixed): mean relative decision regret on 2-unit VAL situations, tie -> effect RMSE.
Stop: --max-updates, or patience (evaluations without improvement), or the run's wall allotment.
"""

import os
import sys

os.environ.setdefault("OMP_NUM_THREADS", "1")
import argparse  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import torch  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from hospitalos.howmint import data as DA  # noqa: E402
from hospitalos.howmint import models as MO  # noqa: E402

S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")
CORPUS = S / "int1_corpus"
RUNS = S / "int1_runs"
SIZES = {"S": 128, "M": 320}
W_ST, W_CO, W_CUM, W_EFF, W_RUP = 1.0, 1.0, 1.0, 5.0, 0.5
TIER = {1: 1000, 2: 10000}


def horizon_of(n: int, upd: int, sched: tuple[int, int] = (4000, 10000)) -> int:
    if n > 2:
        return 12
    return 12 if upd < sched[0] else (24 if upd < sched[1] else 36)


def batch_loss(model, sits: list[dict], st: dict, upd: int) -> tuple[torch.Tensor, dict]:
    n = sits[0]["n"]
    T = horizon_of(n, upd)
    L = min(T, DA.LOOKAHEAD_STEPS[n])
    tens = [DA.tensors(s, st) for s in sits]
    cat = {k: torch.cat([t[k] for t in tens]) for k in ("unit", "res", "glob", "ur_mask", "uu", "U", "R", "C", "beds", "desc")}
    sh, ch, rh = model(cat["unit"], cat["res"], cat["glob"], cat["ur_mask"], cat["uu"], cat["U"][:, :T], cat["R"][:, :T], cat["C"][:, :T],
                       cat["beds"], steps=T)
    sts = torch.tensor(st["st_s"])
    cum_h = ch[:, :L].sum((1, 2)) * st["cost_s"]  # [B]
    ls, lc, lcum, leff, lrup, off = [], [], [], [], [], 0
    for t in tens:  # targets per situation (K futures may differ between situations)
        m = len(t["desc"])
        sl = slice(off, off + m)
        ls.append((((sh[sl, None] - t["states"][:, :, :T]) / sts) ** 2).mean())
        lc.append(((ch[sl, None] - t["costs"][:, :, :T] / st["cost_s"]) ** 2).mean())
        cy = t["costs"][:, :, :L].sum((2, 3))  # [m,K]
        lcum.append((((cum_h[sl, None] - cy) / st["cum_s"]) ** 2).mean())
        e_h = cum_h[sl] - cum_h[off]
        e_y = cy - cy[:1]
        leff.append((((e_h[:, None] - e_y) / st["eff_s"]) ** 2)[1:].mean())
        lrup.append(torch.nn.functional.binary_cross_entropy_with_logits(rh[sl, None].expand_as(t["n24"][:, :, :T]), t["n24"][:, :, :T]))
        off += m
    l_st, l_co, l_cum, l_eff, l_rup = (torch.stack(x).mean() for x in (ls, lc, lcum, leff, lrup))
    loss = W_ST * l_st + W_CO * l_co + W_CUM * l_cum + W_EFF * l_eff + W_RUP * l_rup
    return loss, {"st": float(l_st), "co": float(l_co), "cum": float(l_cum), "eff": float(l_eff), "rup": float(l_rup), "T": T}


@torch.no_grad()
def evaluate(model, sits: list[dict], st: dict) -> dict:
    from scipy.stats import spearmanr

    model.eval()
    by_n: dict[int, dict] = {}
    for s in sits:
        n = s["n"]
        L = DA.LOOKAHEAD_STEPS[n]
        t = DA.tensors(s, st)
        sh, ch, _rh = model(t["unit"], t["res"], t["glob"], t["ur_mask"], t["uu"], t["U"][:, :L], t["R"][:, :L], t["C"][:, :L], t["beds"], steps=L)
        pred = (ch.sum((1, 2)) * st["cost_s"]).numpy()
        true = t["costs"][:, :, :L].sum((2, 3)).mean(1).numpy()
        ch_i = int(np.argmin(pred))
        reg = true[ch_i] - true.min()
        d = by_n.setdefault(n, {"rel_regret": [], "regret": [], "eff_err": [], "rho": [], "st_err": []})
        d["regret"].append(float(reg))
        d["rel_regret"].append(float(reg / max(1.0, true[0])))
        d["eff_err"].append(((pred - pred[0]) - (true - true[0]))[1:])
        rr = spearmanr(pred, true).statistic
        d["rho"].append(0.0 if np.isnan(rr) else float(rr))
        d["st_err"].append(float((((sh - t["states"][:, :, :L].mean(1)) / torch.tensor(st["st_s"])) ** 2).mean()))
    out = {}
    for n, d in by_n.items():
        out[str(n)] = {"situations": len(d["regret"]), "rel_regret": float(np.mean(d["rel_regret"])), "regret": float(np.mean(d["regret"])),
                       "effect_rmse": float(np.sqrt(np.mean(np.concatenate(d["eff_err"]) ** 2))), "spearman": float(np.mean(d["rho"])),
                       "state_mse": float(np.mean(d["st_err"]))}
    model.train()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--size", default="S")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tier", type=int, default=1)
    ap.add_argument("--init", default="")
    ap.add_argument("--ablate", default="")
    ap.add_argument("--budget", type=float, default=450.0)
    ap.add_argument("--lr", type=float, default=0.0)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--max-updates", type=int, default=60000)
    ap.add_argument("--eval-every", type=int, default=1000)
    ap.add_argument("--patience", type=int, default=8)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--val-n", type=int, default=300)
    a = ap.parse_args()
    t_start = time.time()
    torch.set_num_threads(a.threads)
    rd = RUNS / a.run
    rd.mkdir(parents=True, exist_ok=True)
    cfg_p = rd / "config.json"
    cfg = vars(a) | {"d": SIZES[a.size], "weights": [W_ST, W_CO, W_CUM, W_EFF, W_RUP]}
    if not cfg_p.exists():
        cfg_p.write_text(json.dumps(cfg, indent=1))
    if a.tier == 2:  # 10 000 structures: memory-mapped pack (built by pack.py; first 2 futures per row)
        train = DA.packed_situations(S / "int1_pack_t2")
    else:
        train = DA.situations(DA.load(CORPUS, "INT_TRAIN", list(range(TIER[a.tier]))))
    val = DA.situations(DA.load(CORPUS, "INT_VAL", list(range(a.val_n))))
    st_p = rd / "norm.npz"
    if a.init and not st_p.exists():
        import shutil

        shutil.copy(RUNS / a.init / "norm.npz", st_p)  # continuation keeps the earlier TRAIN normalisation
    if not st_p.exists():
        np.savez(st_p, **{k: np.asarray(v) for k, v in DA.norm_stats(train).items()})
    st = {k: (v.item() if v.ndim == 0 else v) for k, v in np.load(st_p).items()}
    model = MO.GraphWM(SIZES[a.size], use_messages=a.ablate != "no_msg", use_history=a.ablate != "no_hist")
    lr = a.lr or (1e-3 if a.size == "S" else 5e-4)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    ck = rd / "last.pt"
    state = {"upd": 0, "curve": [], "best": None, "bad": 0, "stopped": None, "samples": 0, "train_seconds": 0.0}
    if ck.exists():
        c = torch.load(ck, weights_only=False)
        model.load_state_dict(c["model"])
        opt.load_state_dict(c["opt"])
        state = c["state"]
        np.random.set_state(c["np_rng"])
        torch.set_rng_state(c["torch_rng"])
    elif a.init:
        c = torch.load(RUNS / a.init / "best.pt", weights_only=False)
        model.load_state_dict(c["model"])
        state["init_from"] = a.init
        np.random.seed(a.seed)
        torch.manual_seed(a.seed)
    else:
        np.random.seed(a.seed)
        torch.manual_seed(a.seed)
    if state["stopped"]:
        print(json.dumps({"run": a.run, "already_stopped": state["stopped"]}))
        return 0
    groups: dict[int, list[int]] = {}
    for i, s in enumerate(train):
        groups.setdefault(s["n"], []).append(i)
    sizes = sorted(groups)
    weights = np.array([sum(len(train[i]["desc"]) for i in groups[n]) for n in sizes], float)
    weights /= weights.sum()
    stop_at = t_start + a.budget
    t_loop = time.time()
    while time.time() < stop_at - 25:
        n = sizes[np.random.choice(len(sizes), p=weights)]
        pick = np.random.choice(groups[n], size=a.batch, replace=False)
        loss, parts = batch_loss(model, [train[i] for i in pick], st, state["upd"])
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        state["upd"] += 1
        state["samples"] += int(sum(len(train[i]["desc"]) for i in pick))
        if state["upd"] % 50 == 0:
            state["curve"].append({"upd": state["upd"], "loss": float(loss), **parts})
        if state["upd"] % a.eval_every == 0:
            ev = evaluate(model, val, st)
            key = (ev.get("2", {}).get("rel_regret", 9.0), ev.get("2", {}).get("effect_rmse", 9e9))
            state["curve"].append({"upd": state["upd"], "val": ev})
            if state["best"] is None or key < tuple(state["best"]["key"]):
                state["best"] = {"upd": state["upd"], "key": list(key), "val": ev}
                state["bad"] = 0
                torch.save({"model": model.state_dict(), "upd": state["upd"], "cfg": cfg}, rd / "best.pt")
            else:
                state["bad"] += 1
            if state["bad"] >= a.patience:
                state["stopped"] = "patience"
                break
        if state["upd"] >= a.max_updates:
            state["stopped"] = "max_updates"
            break
    state["train_seconds"] += time.time() - t_loop
    torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "state": state, "np_rng": np.random.get_state(),
                "torch_rng": torch.get_rng_state()}, ck)
    (rd / "curve.json").write_text(json.dumps({"state": {k: v for k, v in state.items() if k != "curve"}, "curve": state["curve"]}))
    print(json.dumps({"run": a.run, "upd": state["upd"], "stopped": state["stopped"], "best": state["best"] and state["best"]["upd"],
                      "params": MO.n_params(model), "last": state["curve"][-1] if state["curve"] else None}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
