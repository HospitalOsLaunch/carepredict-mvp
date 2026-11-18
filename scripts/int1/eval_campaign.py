#!/usr/bin/env python3
"""HOWM-INT-1 single final evaluation campaign (closed loop, policy-own observations, common futures).

    eval_campaign.py --panel MAIN|SUB32|EXT|COMBO|SIZE12 --s0 a --s1 b [--par 4] [--budget 470]

Requires evidence/howm_int1/FREEZE_INT1.json (policies, models, panel sizes, futures, planner parameters).
One atomic JSON per (panel, structure, episode): for every future r = 1..R and every policy of the panel: outcome
metrics (wait, uncovered care, rejections, ruptures, terminal state, per-unit wait, staff-hours, choices) and
decision CPU times; for W: predicted per-unit rupture probability over the next 24 h at each decision (anticipation).
"""

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/int1"))
EV = ROOT / "evidence/howm_int1"
S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")
OUT = S / "int1_eval"
PANELS = {  # name -> (partition, n units or 'mix', task)
    "MAIN": ("INT_TEST_MAIN", 2, "week"), "SUB32": ("INT_TEST_MAIN", 2, "week"), "EXT": ("INT_TEST_EXT", "4/8", "day"),
    "COMBO": ("INT_TEST_COMBO", "4/8", "day"), "SIZE12": ("INT_TEST_12", 12, "day")}
COMBOS = (("aval", "calendar"), ("transfer", "transport"))


def structure_of(panel: str, s: int):
    from hospitalos.howmint import world as W

    part, n, _task = PANELS[panel]
    if panel in ("MAIN", "SUB32"):
        return W.structure(part, s, 2)
    if panel == "EXT":
        return W.structure(part, s, 4 if s % 2 == 0 else 8)
    if panel == "COMBO":
        return W.n_unit_structure(part, s, 4 if s % 2 == 0 else 8, regime="fragile", bottlenecks=COMBOS[(s // 2) % 2], intensity=1.3)
    return W.structure(part, s, 12)


def build_policies(fr: dict, panel: str, n: int, interval_h: int, timing: dict, antic: list) -> dict:
    import pickle

    import numpy as np
    import torch

    from hospitalos.howmint import models as MO
    from hospitalos.howmint import planners as PL
    from hospitalos.howmint import policies as P

    torch.set_num_threads(1)
    pols = {"historical": P.historical, "robust": P.robust}
    if panel == "SUB32":
        pols = {k: PL.sim_policy(k, fr["Md"], interval_h, timing.setdefault(k, [])) for k in ("F", "R1")}
        return pols

    def load_w(run):
        rd = S / "int1_runs" / run
        cfg = json.loads((rd / "config.json").read_text())
        m = MO.GraphWM(cfg["d"], use_messages=cfg.get("ablate") != "no_msg", use_history=cfg.get("ablate") != "no_hist")
        m.load_state_dict(torch.load(rd / "best.pt", weights_only=False)["model"])
        m.eval()
        st = {k: (v.item() if v.ndim == 0 else v) for k, v in np.load(rd / "norm.npz").items()}
        return m, st
    for name, runs in fr["W_systems"].items():
        ms = [load_w(r) for r in runs]
        sc = PL.w_scorer([m for m, _ in ms], ms[0][1])
        pols[name] = PL.model_policy(_with_antic(sc, ms, name, antic), interval_h, timing.setdefault(name, []))
    for name, spec in fr["D_systems"].items():
        if spec["kind"] == "dset":
            net = MO.DSet(160)
            net.load_state_dict(torch.load(S / "int1_runs" / spec["run"] / "best.pt", weights_only=False)["net"])
            net.eval()
            st = {k: (v.item() if v.ndim == 0 else v) for k, v in np.load(S / "int1_runs" / spec["norm_run"] / "norm.npz").items()}
            sc = PL.dset_scorer(net, st)
        else:
            import train_d

            sc = PL.d_scorer(train_d.load_d_model(S / "int1_runs" / spec["run"] / f"{spec['name']}.pkl"))
        pols[name] = PL.model_policy(sc, interval_h, timing.setdefault(name, []))
    return pols


def _with_antic(score, ms, name, antic):
    """Scorer wrapper that also records W's per-unit rupture probability over the next 24 h for the (none, none)
    sequence (the anticipation question is asked without intervention)."""
    import numpy as np
    import torch

    from hospitalos.howmint import data as DA

    def sc(g, schs, descs, n, Ls):
        out = score(g, schs, descs, n, Ls)
        s = {"unit": g["unit"][None], "res": g["res"][None], "glob": g["glob"][None], "uu": g["uu"][None], "U": schs[0]["U"][None],
             "R": schs[0]["R"][None], "C": schs[0]["C"][None], "desc": descs[0][None], "n": n,
             "states": np.zeros((1, 1, Ls, n, 9), np.float32), "costs": np.zeros((1, 1, Ls, n), np.float32), "n24": np.zeros((1, 1, Ls, n))}
        t = DA.tensors(s, ms[0][1])
        with torch.no_grad():
            p = np.mean([torch.sigmoid(m(t["unit"], t["res"], t["glob"], t["ur_mask"], t["uu"], t["U"], t["R"], t["C"], t["beds"], steps=min(12, Ls))[2])
                         .numpy()[0].max(0) for m, _ in ms], 0)
        antic.append({"system": name, "p24": p.tolist()})
        return out
    return sc


def job(arg):
    panel, s, e, fr = arg[:4]
    only_r = arg[4] if len(arg) > 4 else None  # SUB32: one future per job (F/R1 cost ~128 s CPU per future)
    import numpy as np

    from hospitalos.howmint import loop as L
    from hospitalos.howmint import world as W

    p = OUT / panel / (f"s{s:04d}_e{e}.json" if only_r is None else f"s{s:04d}_e{e}_r{only_r}.json")
    if p.exists():
        return 0
    t0 = time.time()
    sp = W.episode(structure_of(panel, s), e)
    import corpus as CO

    h0 = CO.h0_of(PANELS[panel][0], s, e, sp.n)
    week = PANELS[panel][2] == "week"
    nd, iv, hz = (7, 24, 168) if week else (4, 6, 24)
    pre = L.prefix(sp, h0)
    rec = {"panel": panel, "structure": s, "episode": e, "n": sp.n, "family": sp.family, "regime": sp.regime, "bottlenecks": list(sp.bottlenecks),
           "h0": h0, "futures": {}}
    for r in (range(1, fr["futures"] + 1) if only_r is None else [only_r]):
        timing, antic = {}, []
        pols = build_policies(fr, panel, sp.n, iv, timing, antic)
        res = {}
        for name, pol in pols.items():
            antic.clear()
            out = L.closed_loop(sp, pre, r, pol, nd, iv, hz)
            n24 = out.pop("n24_series", None)
            out["decision_cpu_s"] = timing.get(name, [])[-nd:] if name in timing else []
            if antic:
                out["anticipation"] = list(antic)
            res[name] = out
        rec["futures"][str(r)] = res
    rec["seconds"] = time.time() - t0
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, default=float))
    tmp.replace(p)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", required=True)
    ap.add_argument("--s0", type=int, default=0)
    ap.add_argument("--s1", type=int, default=1)
    ap.add_argument("--par", type=int, default=4)
    ap.add_argument("--budget", type=float, default=470.0)
    a = ap.parse_args()
    fr = json.loads((EV / "FREEZE_INT1.json").read_text())
    if a.panel == "SUB32":
        todo = [(a.panel, s, e, fr, r) for s in range(a.s0, a.s1) for e in range(3) for r in range(1, fr["futures"] + 1)
                if not (OUT / a.panel / f"s{s:04d}_e{e}_r{r}.json").exists()]
    else:
        todo = [(a.panel, s, e, fr) for s in range(a.s0, a.s1) for e in range(3) if not (OUT / a.panel / f"s{s:04d}_e{e}.json").exists()]
    t0, n = time.time(), 0
    with get_context("fork").Pool(a.par, maxtasksperchild=20) as pool:
        pending, it = [], iter(todo)
        while True:
            while len(pending) < a.par and time.time() - t0 < a.budget:
                nxt = next(it, None)
                if nxt is None:
                    break
                pending.append(pool.apply_async(job, (nxt,)))
            if not pending:
                break
            time.sleep(0.3)
            for r in [r for r in pending if r.ready()]:
                n += r.get()
                pending.remove(r)
    print(json.dumps({"panel": a.panel, "done_now": n, "files": len(list((OUT / a.panel).glob("*.json"))) if (OUT / a.panel).exists() else 0,
                      "seconds": round(time.time() - t0, 1)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
