#!/usr/bin/env python3
"""HOWM-INT-1 propagation on DEV (paired, single-channel controls; common futures; no learned model).

Channels: (a) bed holding during internal transfers (control: the origin bed is released at the transfer request;
the transfer still happens, flows and capacities unchanged); (b) external downstream slots (control: unlimited
slots; the stays flagged 'aval' still leave through the same route). Outcome: wait change per unit over 72 h,
split upstream (first half of the units) / downstream. Positive = the channel adds wait (base - control)."""
import json
import sys
from multiprocessing import get_context
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts/int1"))


def run(sp, pre, r, control):
    from hospitalos.howmint import loop as L
    from hospitalos.howm.world import TPH

    eng, prov, _ = L.start_future(pre, sp, r)
    if control == "no_bed_hold":
        eng.hold_bed = False
    if control == "aval_unlimited":
        eng.spec_meta = dict(eng.spec_meta, aval_slots=10**6)
    w0 = dict(eng.waiting_ticks)
    for _ in range(72 * TPH):
        eng.step(prov)
    return {un: 15.0 * (eng.waiting_ticks.get(un, 0) - w0.get(un, 0)) for un in sp.units}


def job(arg):
    n, s, bn = arg
    import corpus as CO

    from hospitalos.howmint import loop as L
    from hospitalos.howmint import world as W

    sp = W.episode(W.n_unit_structure("INT_DEV", s, n, regime="fragile", bottlenecks=bn), 0)
    pre = L.prefix(sp, CO.h0_of("INT_DEV", s, 0, n))
    up = sp.units[: max(1, n // 2)]
    out = {"n": n, "s": s, "bottlenecks": list(bn)}
    for control in ("no_bed_hold", "aval_unlimited"):
        d_up, d_down = [], []
        for r in (1, 2):
            b, c = run(sp, pre, r, None), run(sp, pre, r, control)
            d_up.append(sum(b[u] - c[u] for u in sp.units if u in up))
            d_down.append(sum(b[u] - c[u] for u in sp.units if u not in up))
        out[control] = {"upstream": float(np.mean(d_up)), "downstream": float(np.mean(d_down))}
    return out


def main() -> int:
    todo = [(n, 100 + k, bn) for n in (4, 8) for k, bn in enumerate([("transfer",), ("aval",), ("transfer", "aval"), ("cleaning",)] * 6)]
    with get_context("fork").Pool(4) as pool:
        rows = pool.map(job, todo)
    summ = {}
    for n in (4, 8):
        for bn in sorted({tuple(r["bottlenecks"]) for r in rows}):
            rr = [r for r in rows if r["n"] == n and tuple(r["bottlenecks"]) == bn]
            summ[f"n{n}|{'+'.join(bn)}"] = {c: {side: {"mean": float(np.mean([r[c][side] for r in rr])),
                                                      "se": float(np.std([r[c][side] for r in rr]) / np.sqrt(len(rr)))}
                                                for side in ("upstream", "downstream")} for c in ("no_bed_hold", "aval_unlimited")} | {"structures": len(rr)}
    out = {"rows": rows, "summary": summ, "note": "single-channel paired controls; positive = channel adds wait (base - control) over 72 h"}
    (ROOT / "evidence/howm_int1/PROPAGATION_DEV.json").write_text(json.dumps(out, indent=1))
    for k, v in summ.items():
        print(k, json.dumps({c: {s: round(x["mean"]) for s, x in v[c].items()} for c in ("no_bed_hold", "aval_unlimited")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
