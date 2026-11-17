"""INT-1 regime qualification on DEV under FIXED reference policies (none, historical rule); no learned model.
Per structure: origin saturation, ruptures, wait, and whether a simple rule is (near) best among all single
admissible actions (paired branch, 2 futures)."""
import json, sys, time
from multiprocessing import get_context
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from hospitalos.howmint import world as W, loop as L, actions as A  # noqa: E402
from hospitalos.howm.keys import key, u  # noqa: E402


def h0_of(sp, e, n):
    k = key("INT-h0", sp.part, sp.idx, e)
    return (36 + 6 * int(u(k, 0, "h0", "") * 7)) if n == 2 else (36 + int(u(k, 0, "h0", "") * 48))


def job(arg):
    n, s = arg
    sp = W.episode(W.structure("INT_DEV", s, n), 0)
    h0 = h0_of(sp, 0, n)
    pre = L.prefix(sp, h0)
    hz, nd, iv = (168, 7, 24) if n == 2 else (24, 4, 6)
    eng0 = pre["eng"]
    sat = {"queue_t0": sum(len(q) for q in eng0.queue.values()), "q24_units_t0": sum(1 for un in sp.units if any(
        (eng0.tick - r.arrival) * 15 >= 1440 for r in eng0.queue.get(un, []))), "occ_t0": sum(b.state == "occ" for b in eng0.beds.values()) / len(eng0.beds)}
    pol = {"none": lambda **k: k["cat"][0], "hist": lambda **k: k["cat"][1] if k["adm"][1] else k["cat"][0]}
    res = {p: [L.closed_loop(sp, pre, r, f, nd, iv, hz) for r in (1, 2)] for p, f in pol.items()}
    cat = A.catalogue(eng0, sp.units)
    adm = [A.admissible(eng0, a, n, eng0.tick) for a in cat]
    loss = []
    for a, ok in zip(cat, adm):
        if ok:
            loss.append((a["id"], float(np.mean([L.branch(pre, sp, eng0, [a, None], r, 48 if n == 2 else 24, iv, pre["anchor"])["wait_patient_min"] for r in (1, 2)]))))
    best = min(l for _i, l in loss)
    lnone = dict(loss)["none"]
    lhist = dict(loss).get("coord", lnone)
    return {"n": n, "s": s, "family": sp.family, "regime": sp.regime, "bottlenecks": list(sp.bottlenecks), "h0": h0, **sat,
            "wait_none": float(np.mean([x["wait_patient_min"] for x in res["none"]])), "wait_hist": float(np.mean([x["wait_patient_min"] for x in res["hist"]])),
            "ruptures_none": float(np.mean([x["rupture_onsets"] for x in res["none"]])), "rupture_min_none": float(np.mean([x["rupture_minutes"] for x in res["none"]])),
            "uncovered_none": float(np.mean([x["uncovered_care_min"] for x in res["none"]])),
            "best_single": min(loss, key=lambda x: x[1])[0], "gap_none_best_rel": (lnone - best) / max(1.0, lnone),
            "gap_hist_best_rel": (lhist - best) / max(1.0, lnone), "beds": sum(sp.beds.values())}


if __name__ == "__main__":
    todo = [(2, s) for s in range(60)] + [(4, s) for s in range(60)] + [(8, s) for s in range(60)] + [(12, s) for s in range(24)]
    t = time.time()
    with get_context("fork").Pool(4) as pool:
        rows = pool.map(job, todo, chunksize=2)
    out = {"rows": rows, "seconds": time.time() - t}
    summ = {}
    for n in (2, 4, 8, 12):
        for reg in ("nominal", "tense", "fragile"):
            rr = [r for r in rows if r["n"] == n and r["regime"] == reg]
            if not rr:
                continue
            summ[f"{n}|{reg}"] = {"structures": len(rr), "rupture_struct_frac": float(np.mean([r["ruptures_none"] > 0 for r in rr])),
                                  "q24_at_t0_frac": float(np.mean([r["q24_units_t0"] > 0 for r in rr])), "occ_t0": float(np.mean([r["occ_t0"] for r in rr])),
                                  "wait_none_per_bed_h": float(np.mean([r["wait_none"] / r["beds"] / 60 for r in rr])),
                                  "simple_rule_suffices_frac(<1%)": float(np.mean([min(r["gap_none_best_rel"], r["gap_hist_best_rel"]) < 0.01 for r in rr])),
                                  "gap_none_best_rel_mean": float(np.mean([r["gap_none_best_rel"] for r in rr]))}
    out["summary"] = summ
    (ROOT / "evidence/howm_int1/QUALIFICATION_DEV.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(summ, indent=1))
