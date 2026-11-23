#!/usr/bin/env python3
"""HOWM-INT-1 corpus generator (consequences from the TRUE engine; not a distillation of F).

Per structure: 3 decision situations, each in its own episode e = 0, 1, 2 with an origin hour H0 drawn by key
(decorrelated from family, structure index and episode), a provenance policy drawn by key (historical 40 %,
exploratory 40 %, robust 20 %; intermediate models may be added for TRAIN only, logged), and 0-2 provenance
decisions before the situation (drawn by key). At the situation: public graph inputs (policy-own history) and
paired action SEQUENCES from the common candidate generator, each played on K common true futures (r = 1..K;
K = 8 on the fixed subset idx % 20 == 0, else 2), recorded every 2 h (true per-unit state, wait, n24) over
72 h (2 units) or 24 h (4/8/12 units).

    corpus.py --part INT_TRAIN --s0 0 --s1 1000 [--out DIR] [--par 4] [--budget 480]
"""

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
DEFAULT_OUT = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad/int1_corpus")
HELDOUT_PAIRS = ({"aval", "calendar"}, {"transfer", "transport"})  # new combinations reserved to the generalisation test
SIZE_MIX = ((0.6, 2), (0.8, 4), (1.0, 8))  # 6 000 / 2 000 / 2 000 at 10 000 structures


def size_of(part: str, s: int) -> int:
    from hospitalos.howm.keys import key, u

    x = u(key("INT-size", part, s), 0, "size", "")
    return next(n for p, n in SIZE_MIX if x < p)


def train_structure(part: str, s: int, n: int):
    from hospitalos.howmint import world as W

    sp = W.structure(part, s, n)
    if n > 2 and any(p <= set(sp.bottlenecks) for p in HELDOUT_PAIRS):
        keep = tuple(sorted(sp.bottlenecks)[1:])  # deterministic: drop the first element of a held-out pair
        sp = W.n_unit_structure(part, s, n, regime=sp.regime, bottlenecks=keep)
    return sp


def h0_of(part: str, s: int, e: int, n: int) -> int:
    from hospitalos.howm.keys import key, u

    k = key("INT-h0", part, s, e)
    return (36 + 6 * int(u(k, 0, "h0", "") * 7)) if n == 2 else (36 + int(u(k, 0, "h0", "") * 48))


def situation(sp_e, n: int, h0: int, prov_name: str, n_prior: int, interval_h: int):
    """Closed-loop run of the provenance policy on the corpus realisation r = 0 up to the situation tick."""
    from hospitalos.howmint import actions as A
    from hospitalos.howmint import features as F
    from hospitalos.howmint import loop as L
    from hospitalos.howmint import policies as P
    from hospitalos.howmint import world as W

    pre = L.prefix(sp_e, h0)
    eng, prov, rec = L.start_future(pre, sp_e, 0)
    t_start = eng.tick
    pol = P.RULES[prov_name]
    target = t_start + n_prior * interval_h * TPH_
    prior_actions = []
    while eng.tick < target:
        t = eng.tick
        if (t - t_start) % (interval_h * TPH_) == 0:
            ps, pe = L.public_view(pre, rec, t)
            cat = A.catalogue(pe, sp_e.units)
            adm = [A.admissible(pe, a, n, t_start) for a in cat]
            a = pol(ps=ps, peng=pe, cat=cat, adm=adm, t=t, t_start=t_start, spec=sp_e)
            A.apply(eng, a, W._Cal(prov, sp_e.drop))
            prior_actions.append(a["id"])
        eng.step(prov)
    snaps = {}
    for lag in (6, 24):  # same policy-own public stream, observations available before target - lag
        ps_h, pe_h = L.public_view(pre, rec, target - lag * TPH_)
        snaps[lag] = {un: F.unit_raw(pe_h, ps_h, un) for un in sp_e.units}
    ps, pe = L.public_view(pre, rec, target)
    g = F.graph(pe, ps, snaps, sp_e.units, t_start, n)
    return pre, eng, pe, g, _anchor(prov, target), prior_actions, t_start


def _anchor(prov, tick):
    from hospitalos.howm.world import TPH

    h = tick // TPH
    if prov.spec.mech["m2_common"]:
        return {"common": (h, prov.regime("transport", h))}
    return {team: (h, prov.regime(team, h)) for team in ("transport", "cleaning")}


TPH_ = 4


def job(arg):
    part, s, out, k_force = arg
    from hospitalos.howm.keys import key, u
    from hospitalos.howmint import actions as A
    from hospitalos.howmint import features as F
    from hospitalos.howmint import loop as L

    p = Path(out) / part / f"s{s:05d}.npz"
    if p.exists():
        return 0
    t_all = time.time()
    n = size_of(part, s)
    sp = train_structure(part, s, n)
    K = k_force if k_force else (8 if s % 20 == 0 else 2)
    hz, iv = (72, 24) if n == 2 else (24, 6)
    arrays: dict[str, list] = {k: [] for k in ("unit", "res", "glob", "uu", "states", "costs", "n24", "U", "R", "C", "desc", "sit", "seq_ok")}
    meta = {"part": part, "structure": s, "n": n, "units": sp.units, "family": sp.family, "regime": sp.regime, "bottlenecks": list(sp.bottlenecks),
            "K": K, "horizon_h": hz, "interval_h": iv, "situations": [], "totals": []}
    for e in range(3):
        sp_e = __import__("hospitalos.howmint.world", fromlist=["x"]).episode(sp, e)
        h0 = h0_of(part, s, e, n)
        kk = key("INT-prov", part, s, e)
        x = u(kk, 0, "prov", "")
        prov_name = "historical" if x < 0.4 else ("exploratory" if x < 0.8 else "robust")
        n_prior = int(u(kk, 0, "prior", "") * 3)
        pre, eng, pe, g, anchor, prior, t_start = situation(sp_e, n, h0, prov_name, n_prior, iv)
        cat = A.catalogue(pe, sp.units)
        adm = [A.admissible(pe, a, n, t_start) for a in cat]
        seqs = L.sequences(cat, adm)
        if n > 2 and len(seqs) > 20:  # keep none, coord and a keyed sample of the others
            rest = list(range(2, len(seqs)))
            order = sorted(rest, key=lambda i: u(kk, 0, "seqpick", i))
            seqs = seqs[:2] + [seqs[i] for i in sorted(order[:18])]
        sit = {"episode": e, "h0": h0, "t": int(eng.tick), "t_start": int(t_start), "provenance": prov_name, "prior_actions": prior,
               "seqs": [[a["id"] if a else None for a in sq] for sq in seqs]}
        meta["situations"].append(sit)
        tot_s = []
        for sq in seqs:
            sch = F.schedule(sq, sp.units, eng.tick, hz // 2, iv, sp.drop)
            st_k, co_k, n24_k, tot_k = [], [], [], []
            for r in range(1, K + 1):
                b = L.branch(pre, sp_e, eng, sq, r, hz, iv, anchor)
                st_k.append(b["states"])
                co_k.append(b["step_costs"])
                n24_k.append(b["n24"])
                tot_k.append({k: b[k] for k in ("wait_patient_min", "uncovered_care_min", "rejected", "rupture_minutes", "terminal_queue",
                                                 "terminal_max_wait_min", "staff_hours")})
            for k_, v in (("unit", g["unit"]), ("res", g["res"]), ("glob", g["glob"]), ("uu", g["uu"]), ("U", sch["U"]), ("R", sch["R"]),
                          ("C", sch["C"]), ("desc", F.seq_descriptor(sq, eng.tick)), ("states", np.stack(st_k).astype(np.float16)),
                          ("costs", np.stack(co_k).astype(np.float32)), ("n24", np.stack(n24_k).astype(np.int16))):
                arrays[k_].append(v)
            arrays["sit"].append(e)
            arrays["seq_ok"].append(1)
            tot_s.append(tot_k)
        meta["totals"].append(tot_s)
    meta["seconds"] = time.time() - t_all
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.stem + ".tmp.npz")
    np.savez_compressed(tmp, **{k: np.stack(v) for k, v in arrays.items()})
    tmp.replace(p)
    (p.with_suffix(".json")).write_text(json.dumps(meta))
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="INT_TRAIN")
    ap.add_argument("--s0", type=int, default=0)
    ap.add_argument("--s1", type=int, default=10)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--par", type=int, default=4)
    ap.add_argument("--budget", type=float, default=470.0)
    ap.add_argument("--K", type=int, default=0, help="force K futures for every structure (VAL: 4)")
    a = ap.parse_args()
    todo = [(a.part, s, a.out, a.K) for s in range(a.s0, a.s1) if not (Path(a.out) / a.part / f"s{s:05d}.npz").exists()]
    t0, n = time.time(), 0
    with get_context("fork").Pool(a.par, maxtasksperchild=50) as pool:
        pending, it = [], iter(todo)
        while True:
            while len(pending) < a.par * 2 and time.time() - t0 < a.budget:
                nxt = next(it, None)
                if nxt is None:
                    break
                pending.append(pool.apply_async(job, (nxt,)))
            if not pending:
                break
            time.sleep(0.2)
            for r in [r for r in pending if r.ready()]:
                n += r.get()
                pending.remove(r)
    d = Path(a.out) / a.part
    print(json.dumps({"part": a.part, "done_now": n, "files": len(list(d.glob("*.npz"))) if d.exists() else 0, "seconds": round(time.time() - t0, 1)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
