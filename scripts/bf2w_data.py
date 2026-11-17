#!/usr/bin/env python3
"""Decision n.8 pilot data (TRAIN trajectories) and, after the freeze, the single final evaluation campaign.

  train --s0 a --s1 b [--K 2]      BF2_TRAIN structure s, episode e = s % 3, decision origin; all 10 actions x
                                   K true futures (r = 1..K, common to all actions); 2-h states and step costs
  eval  --s0 a --s1 b [--E 8]      BF2W_CONF (NEW structures) x 3 episodes: public inputs, frozen D and W choices,
                                   F and R1 planners (Md from the pilot protocol), true evaluation of all 10 actions
                                   on E fresh futures (r = 1..E); requires FREEZE_PILOT.json
One atomic file per origin under evidence/howm2_bfrag2w/runs/<mode>/; resumable; slot scheduler (no killed job)."""

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import argparse  # noqa: E402
import json  # noqa: E402
import resource  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
EV = ROOT / "evidence/howm2_bfrag2w"


def origin(part, s, e):
    from hospitalos.bfrag2 import core2 as C
    from hospitalos.bfrag2w import core_w as W
    from hospitalos.howm.world import TPH

    w = W.structure(part, s)
    spec_e = C.episode_spec(w, e)
    hd = C.DECISION_HOURS[e % 3]
    t0 = hd * TPH
    h = hd
    ticks = sorted({x * TPH for x in (h - 24, h - 6, h) if x >= 0})
    ep, _tr = C.generate2(spec_e, ticks, w.drop)
    acts = C.catalogue(t0)
    rec = {"part": part, "structure": s, "episode": e, "family": w.family, "decision_hour": hd,
           "inputs": W.public_inputs(w, ep, t0), "calendar": W.calendar_descriptor(w.drop, t0),
           "actions": [{"id": a["id"], "staff_hours": a["staff_hours"], "desc": W.action_descriptor(a, t0)} for a in acts]}
    return C, W, w, spec_e, ep, t0, acts, rec


def job_train(arg):
    s, K = arg
    from hospitalos.bfrag import core as KK
    from hospitalos.howm import generator as G

    part, e = "BF2_TRAIN", s % 3
    p = EV / "runs/train" / f"s{s:03d}_e{e}.json"
    if p.exists():
        return 0
    t = time.time()
    C, W, w, spec_e, ep, t0, acts, rec = origin(part, s, e)
    anchor = G.true_regime_at(ep, t0)
    states = np.zeros((len(acts), K, W.N_STEPS, 30), np.float32)
    costs = np.zeros((len(acts), K, W.N_STEPS, 2), np.float32)
    totals = []
    for i, a in enumerate(acts):
        row = []
        for k in range(K):
            r = W.rollout_traj(ep.instants[t0], KK.bf_provider(spec_e, k + 1, w.nominal, regime_anchor=anchor), a["plan"], w.drop, a["extra"])
            states[i, k] = np.array(r.pop("states"), np.float32)
            costs[i, k] = np.array(r.pop("step_costs"), np.float32)
            row.append(r)
        totals.append(row)
    rec["totals"] = totals
    rec["futures"] = list(range(1, K + 1))
    rec["seconds"] = time.time() - t
    rec["maxrss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    np.savez_compressed(p.with_suffix(".npz.tmp.npz"), states=states, costs=costs)
    Path(str(p.with_suffix(".npz.tmp.npz"))).replace(p.with_suffix(".npz"))
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec) + "\n")
    tmp.replace(p)
    return 1


def job_eval(arg):
    s, e, E, Md = arg
    from hospitalos.bfrag import core as KK
    from hospitalos.howm import generator as G
    from hospitalos.howm.b0 import B0Params

    import bf2w_models as MOD

    part = "BF2W_CONF"
    p = EV / "runs/eval" / f"s{s:03d}_e{e}.json"
    if p.exists():
        return 0
    t = time.time()
    C, W, w, spec_e, ep, t0, acts, rec = origin(part, s, e)
    tm = {}
    pub, ps, pe = C.public_state(ep, t0)
    ts = time.time()
    pred = MOD.predict_costs(rec)  # frozen D and W (W main system + each seed), public inputs only
    tm["D_W_predict"] = time.time() - ts
    rec["pred"] = pred
    pb = B0Params.from_json(json.loads((ROOT / "evidence/howm1/B0_PARAMS.json").read_text()))
    ts = time.time()
    rec["R1_planner"] = C.planner(C.r1_pairs(w, pub, ps, pe, t0, pb, Md), w.drop, acts)
    tm["plan_R1"] = time.time() - ts
    ts = time.time()
    rec["F_planner"] = C.planner(C.f_pairs(w, pub, ps, pe, t0, Md), w.drop, acts)
    tm["plan_F"] = time.time() - ts
    anchor = G.true_regime_at(ep, t0)
    ts = time.time()
    ev = []
    for a in acts:
        row = []
        for r in range(1, E + 1):
            x = W.rollout_traj(ep.instants[t0], KK.bf_provider(spec_e, r, w.nominal, regime_anchor=anchor), a["plan"], w.drop, a["extra"])
            x["state_end"] = x["states"][-1]
            x["states_every_24h"] = x["states"][11::12]
            x.pop("states")
            x["step_costs_sum"] = np.array(x.pop("step_costs")).sum(0).tolist()
            row.append(x)
        ev.append(row)
    tm["evaluate"] = time.time() - ts
    rec["eval"] = ev
    rec["E"], rec["Md"] = E, Md
    rec["timing_s"] = tm | {"total": time.time() - t}
    rec["maxrss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec) + "\n")
    tmp.replace(p)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["train", "eval"])
    ap.add_argument("--s0", type=int, default=0)
    ap.add_argument("--s1", type=int, default=1)
    ap.add_argument("--K", type=int, default=2)
    ap.add_argument("--E", type=int, default=8)
    ap.add_argument("--Md", type=int, default=32)
    ap.add_argument("--par", type=int, default=4)
    ap.add_argument("--budget", type=float, default=400.0)
    a = ap.parse_args()
    (EV / "runs" / a.mode).mkdir(parents=True, exist_ok=True)
    if a.mode == "train":
        todo, fn = [(s, a.K) for s in range(a.s0, a.s1) if not (EV / f"runs/train/s{s:03d}_e{s % 3}.json").exists()], job_train
    else:
        if not (EV / "FREEZE_PILOT.json").exists():
            raise SystemExit("final evaluation refused: FREEZE_PILOT.json missing")
        todo = [(s, e, a.E, a.Md) for s in range(a.s0, a.s1) for e in range(3) if not (EV / f"runs/eval/s{s:03d}_e{e}.json").exists()]
        fn = job_eval
    t0, n = time.time(), 0
    with get_context("fork").Pool(a.par, maxtasksperchild=8) as pool:
        pending, it = [], iter(todo)
        while True:
            while len(pending) < a.par and time.time() - t0 < a.budget:
                nxt = next(it, None)
                if nxt is None:
                    break
                pending.append(pool.apply_async(fn, (nxt,)))
            if not pending:
                break
            time.sleep(0.3)
            for r in [r for r in pending if r.ready()]:
                n += r.get()
                pending.remove(r)
    print(json.dumps({"mode": a.mode, "done_now": n, "files": len(list((EV / "runs" / a.mode).glob("*.json"))), "seconds": round(time.time() - t0, 1)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
