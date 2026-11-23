#!/usr/bin/env python3
"""HOWM-2 A3(c): exactness of the regime posterior used by L4 (theta fixed to the truth).

(1) direct enumeration of every regime path on 12-hour prefixes (2^12 paths, z_0 = 0);
(2) an independent log-space forward-backward with plain loops and its own emission computation,
    on 200 items at full length. Both compared with Ladder._hmm to 1e-9.
"""

from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hospitalos.howm import generator as G  # noqa: E402
from hospitalos.howm2 import laws as Lw  # noqa: E402
from hospitalos.howm2 import space  # noqa: E402
from hospitalos.howm2.filter import Ladder, PublicState  # noqa: E402

SIG = {"transport": 0.4, "cleaning": 0.35}
KEY = {"transport": "tr_min", "cleaning": "cl_min"}


def p_k(k: int, med: float, sig: float) -> float:
    """Independent P(K=k), K = max(1, ceil(X/15))."""
    if k >= Lw.KM:
        return 1.0 - norm.cdf((math.log(15 * (Lw.KM - 1)) - math.log(med)) / sig)
    hi = norm.cdf((math.log(15 * k) - math.log(med)) / sig)
    lo = norm.cdf((math.log(15 * (k - 1)) - math.log(med)) / sig) if k > 1 else 0.0
    return hi - lo


def emis_indep(
    done: list[tuple[int, int]], H: int, med: float, slow: float, sig: float
) -> list[list[float]]:
    e = [[0.0, 0.0] for _ in range(H)]
    for s, k in done:
        h = s // 4
        if h < H:
            e[h][0] += math.log(max(p_k(k, med, sig), 1e-300))
            e[h][1] += math.log(max(p_k(k, med * slow, sig), 1e-300))
    return e


def lse(xs: list[float]) -> float:
    m = max(xs)
    return m if m == -math.inf else m + math.log(sum(math.exp(x - m) for x in xs))


def fb_indep(e: list[list[float]]) -> tuple[float, list[float]]:
    lT = [[math.log(1 - Lw.P01), math.log(Lw.P01)], [math.log(Lw.P10), math.log(1 - Lw.P10)]]
    H = len(e)
    al = [[0.0, 0.0] for _ in range(H)]
    al[0] = [0.0 + e[0][0], -math.inf]
    for h in range(1, H):
        for z2 in (0, 1):
            al[h][z2] = lse([al[h - 1][z] + lT[z][z2] for z in (0, 1)]) + e[h][z2]
    be = [[0.0, 0.0] for _ in range(H)]
    for h in range(H - 2, -1, -1):
        for z in (0, 1):
            be[h][z] = lse([lT[z][z2] + e[h + 1][z2] + be[h + 1][z2] for z2 in (0, 1)])
    logZ = lse(al[H - 1])
    post = [math.exp(al[h][1] + be[h][1] - logZ) for h in range(H)]
    return logZ, post


def enumerate_paths(e: list[list[float]]) -> tuple[float, list[float]]:
    H = len(e)
    lT = [[math.log(1 - Lw.P01), math.log(Lw.P01)], [math.log(Lw.P10), math.log(1 - Lw.P10)]]
    tot = -math.inf
    acc = [-math.inf] * H
    for rest in itertools.product((0, 1), repeat=H - 1):
        z = (0, *rest)
        lp = e[0][0] + sum(lT[z[h - 1]][z[h]] + e[h][z[h]] for h in range(1, H))
        tot = lse([tot, lp])
        for h in range(H):
            if z[h]:
                acc[h] = lse([acc[h], lp])
    return tot, [math.exp(a - tot) for a in acc]


def main() -> int:
    space.register()
    rows_enum, rows_fb = [], []
    max_enum = max_fb = max_reloc = 0.0
    rows_reloc: list = []
    n_items = 0
    for idx in range(200):
        spec = G.establishment("HOWM2_REF", idx)
        if not spec.mech["m2"]:
            continue
        ep = G.generate(spec)
        static = next(o[5] for o in ep.observations if o[2] == "static")
        truth = {
            "theta": spec.theta,
            "mech": spec.mech,
            "regimes": ep.regimes,
            "stays": {},
            "roster": {},
        }
        lad = Ladder("REF", static, dict(spec.beds), truth)
        for f in ("transport", "cleaning"):
            med = spec.theta[KEY[f]]
            tab = lad.true_tab[f]  # [1, 2, KM] at the true theta (same laws module, grid of size 1)
            # (1) 12-hour prefix, enumeration
            pub = PublicState("REF", dict(spec.beds))
            pub.ingest([o for o in ep.observations if o[1] <= 12 * 60])
            H = 13
            E = lad._emissions(pub, f, H, tab)
            logZ, post = lad._hmm(E, H)
            e_ind = emis_indep(pub.done[f], H, med, spec.mech["slow"], SIG[f])
            lz2, post2 = enumerate_paths(e_ind)
            d = max(abs(logZ[0] - lz2), max(abs(post[h, 0] - post2[h]) for h in range(H)))
            max_enum = max(max_enum, d)
            rows_enum.append(
                {"index": idx, "family": f, "items": len(pub.done[f]), "max_abs_diff": float(d)}
            )
            # (1b) non-trivial enumeration: real completed items of the episode relocated into hours 0..12
            pubx = PublicState("REF", dict(spec.beds))
            pubx.ingest(ep.observations)
            reloc = [((i % 13) * 4 + 1, k) for i, (_s, k) in enumerate(pubx.done[f][:26])]
            pubr = PublicState("REF", dict(spec.beds))
            pubr.done[f] = reloc
            Er = lad._emissions(pubr, f, H, tab)
            lzr, postr = lad._hmm(Er, H)
            lz3, post3 = enumerate_paths(emis_indep(reloc, H, med, spec.mech["slow"], SIG[f]))
            dr = max(abs(lzr[0] - lz3), max(abs(postr[h, 0] - post3[h]) for h in range(H)))
            max_reloc = max(max_reloc, dr)
            rows_reloc.append(
                {"index": idx, "family": f, "items": len(reloc), "max_abs_diff": float(dr)}
            )
            # (2) full length at origin t = 100 h (independent forward-backward)
            pub2 = PublicState("REF", dict(spec.beds))
            pub2.ingest([o for o in ep.observations if o[1] <= 100 * 60])
            H2 = 101
            E2 = lad._emissions(pub2, f, H2, tab)
            lz, ps_ = lad._hmm(E2, H2)
            lzi, psi = fb_indep(emis_indep(pub2.done[f], H2, med, spec.mech["slow"], SIG[f]))
            starts = sorted(
                {s // 4 for s in pub2.starts[f].values()} | {s // 4 for s, _ in pub2.done[f]}
            )
            for h in starts[:6]:
                if n_items >= 200:
                    break
                dd = max(abs(ps_[h, 0] - psi[h]), abs(lz[0] - lzi))
                max_fb = max(max_fb, dd)
                rows_fb.append({"index": idx, "family": f, "hour": h, "abs_diff": float(dd)})
                n_items += 1
        if n_items >= 200 and len(rows_enum) >= 20:
            break
    out = {
        "enumeration": {
            "cases": len(rows_enum),
            "max_abs_diff": max_enum,
            "pass": bool(max_enum <= 1e-9),
            "note": "real 12-hour prefixes contain no completed item: prior-only check",
        },
        "enumeration_relocated_items": {
            "cases": len(rows_reloc),
            "items_per_case": 26,
            "max_abs_diff": max_reloc,
            "pass": bool(max_reloc <= 1e-9),
            "note": "real completed items relocated into hours 0..12 (non-trivial data)",
        },
        "independent_forward_backward": {
            "items": n_items,
            "max_abs_diff": max_fb,
            "pass": bool(max_fb <= 1e-9 and n_items >= 200),
        },
        "rows_enum": rows_enum,
        "rows_reloc": rows_reloc,
        "rows_fb": rows_fb,
    }
    (ROOT / "evidence/howm2/VALIDATION_C.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: v for k, v in out.items() if not k.startswith("rows")}))
    ok = (
        out["enumeration"]["pass"]
        and out["enumeration_relocated_items"]["pass"]
        and out["independent_forward_backward"]["pass"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
