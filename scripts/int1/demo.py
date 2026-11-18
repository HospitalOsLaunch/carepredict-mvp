#!/usr/bin/env python3
"""HOWM-INT-1 replayable local demonstration (ILLUSTRATIONS, not aggregate results).

Two fixed DEV cases with reproducible randomness (structure, episode and future keys fixed below):
  (1) two units, one week, daily decisions: W (primary system) and B* side by side;
  (2) eight units, 24 h, decisions every 6 h: W and B*.
For each decision: the action chosen by each policy, W's top-3 candidate sequences with predicted lookahead cost,
and the TRUE state per unit (occupancy, queue, patients waiting >= 24 h) observed afterwards; cumulative wait.
Writes docs/howm_int1/DEMO.md and evidence/howm_int1/DEMO.json. Same inputs -> same outputs."""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts/int1"))
import eval_campaign as EC  # noqa: E402

from hospitalos.howmint import loop as L  # noqa: E402
from hospitalos.howmint import world as W  # noqa: E402
from hospitalos.howm.world import TPH  # noqa: E402

CASES = [{"name": "2 unités, 1 semaine", "n": 2, "part": "INT_DEV", "s": 901, "e": 0, "r": 1, "h0": 48, "nd": 7, "iv": 24, "hz": 168},
         {"name": "8 unités, 24 h", "n": 8, "part": "INT_DEV", "s": 902, "e": 0, "r": 1, "h0": 48, "nd": 4, "iv": 6, "hz": 24}]


def run_case(c, fr):
    sp = W.episode(W.structure(c["part"], c["s"], c["n"]), c["e"])
    pre = L.prefix(sp, c["h0"])
    timing, antic = {}, []
    pols = EC.build_policies(fr, "MAIN", c["n"], c["iv"], timing, antic)
    out = {"case": c, "family": sp.family, "regime": sp.regime, "bottlenecks": list(sp.bottlenecks), "units": sp.units, "policies": {}}
    for name in (fr["W_primary"], fr["B_star"]):
        log = []
        res = L.closed_loop(sp, pre, c["r"], pols[name], c["nd"], c["iv"], c["hz"], log=log)
        out["policies"][name] = {"choices": res["choices"], "wait_patient_min": res["wait_patient_min"], "wait_by_unit": res["wait_by_unit"],
                                 "uncovered_care_min": res["uncovered_care_min"], "rupture_minutes": res["rupture_minutes"],
                                 "staff_hours": res["staff_hours"], "decisions": log}
    # true state trajectory under W (per decision interval end), replayed with the same future
    eng, prov, rec = L.start_future(pre, sp, c["r"])
    states = []
    for k in range(c["nd"]):
        ps, pe = L.public_view(pre, rec, eng.tick)
        a = pols[fr["W_primary"]](ps=ps, peng=pe, cat=None, adm=None, t=eng.tick, t_start=pre["t0"], spec=sp,
                                  view=lambda tt, rec=rec: L.public_view(pre, rec, tt))
        from hospitalos.howmint import actions as A

        A.apply(eng, a, W._Cal(prov, sp.drop))
        for _ in range(c["iv"] * TPH):
            eng.step(prov)
        states.append({"t_h": (eng.tick - pre["t0"]) / TPH, "action": a["id"],
                       "units": {un: {"occ": sum(eng.beds[b].state == "occ" for b in eng.units[un].beds), "beds": len(eng.units[un].beds),
                                      "queue": len(eng.queue.get(un, [])),
                                      "q24": sum(1 for r in eng.queue.get(un, []) if (eng.tick - r.arrival) * 15 >= 1440)} for un in sp.units}})
    out["W_true_states"] = states
    return out


def main() -> int:
    fr = json.loads((ROOT / "evidence/howm_int1/FREEZE_INT1.json").read_text())
    res = [run_case(c, fr) for c in CASES]
    (ROOT / "evidence/howm_int1/DEMO.json").write_text(json.dumps(res, indent=1, default=float))
    md = ["# Démonstration rejouable HOWM-INT-1 (illustrations)", "",
          "Les cas montrés sont des **illustrations**. Ils ne remplacent pas les résultats agrégés du rapport.",
          "Rejouer : `python scripts/int1/demo.py`. Mêmes clés de structure, d'épisode et de futur donnent les mêmes sorties.", ""]
    for r in res:
        c = r["case"]
        md += [f"## {c['name']} — famille {r['family']}, régime {r['regime']}", "",
               f"Unités : {', '.join(r['units'])}. Décisions toutes les {c['iv']} h sur {c['hz']} h.", ""]
        md += ["| Politique | Attente cumulée (patients-minutes) | Soins non couverts (min) | Minutes de rupture | Heures-agents | Choix successifs |",
               "|---|---|---|---|---|---|"]
        for name, p in r["policies"].items():
            md.append(f"| {name} | {p['wait_patient_min']:.0f} | {p['uncovered_care_min']:.0f} | {p['rupture_minutes']:.0f} | {p['staff_hours']:.0f} | "
                      f"{', '.join(p['choices'])} |")
        md += ["", f"États vrais sous {fr['W_primary']} à la fin de chaque intervalle :", ""]
        for s in r["W_true_states"]:
            md.append(f"- t = {s['t_h']:.0f} h, action `{s['action']}` : " + " ; ".join(
                f"{un} {v['occ']}/{v['beds']} lits occupés, file {v['queue']} (≥ 24 h : {v['q24']})" for un, v in s["units"].items()))
        md.append("")
    (ROOT / "docs/howm_int1/DEMO.md").write_text("\n".join(md) + "\n")
    print("\n".join(md)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
