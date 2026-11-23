#!/usr/bin/env python3
"""HOWM-2 A' step 1: re-verify the facts of programme section 1 (and the section 2 / 6 code claims)
in the delivered files. Reads A and HOWM-1 evidence, the generator and HOWM2 decision instants
(VAL 0-11 and HOWM2_REF 0-11, day 5, 07/11/15/19 h) for the pending-event census (truth side only,
no L4-N)."""

from __future__ import annotations

import inspect
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hospitalos.howm import dataset, generator as G, nets  # noqa: E402
from hospitalos.howm.generator import EVAL_DAY, INSTANT_HOURS  # noqa: E402
from hospitalos.howm.world import TPD, TPH, candidates  # noqa: E402
from hospitalos.howm2 import space  # noqa: E402

EV = ROOT / "evidence"


def main() -> int:
    dec = json.loads((EV / "howm2/DECISION_A.json").read_text())
    pre = json.loads((EV / "howm1/PRECHECK.json").read_text())
    lad = json.loads((EV / "howm2/LADDER_A.json").read_text())
    cov = json.loads((EV / "howm2/DIAG_COVERAGE.json").read_text())
    out: dict = {}
    m = dec["means"]
    cp = [ins["value"]["C_param"] for i in range(12) for ins in json.loads((EV / f"howm1/precheck/VAL_{i:03d}.json").read_text())["instants"]]
    cs = [ins["value"]["C_pub_snap"] for i in range(12) for ins in json.loads((EV / f"howm1/precheck/VAL_{i:03d}.json").read_text())["instants"]]
    out["F1_public_planners"] = {"L4": m["U_L4"], "C_param": float(np.mean(cp)), "C_pub_snap": float(np.mean(cs)),
                                 "claimed": {"L4": 5002.8, "C_param": 5007.0, "C_pub_snap": 4999.5}}
    out["F2_C_full_rule"] = {"C_full": m["U_C_full"], "L4_minus_C_full": m["U_L4"] - m["U_C_full"], "rule": m["U_rule"],
                             "claimed": {"C_full": 4945.2, "gap": 58, "rule": 4974.1}}
    pi = [p for p in pre["per_instant"]]
    out["F3_V_latent"] = {"V_latent": pre["V_latent"], "V_param": pre["V_param"],
                          "recomputed_mean_C_param_minus_C_full": float(np.mean([p["C_param"] - p["C_full"] for p in pi])),
                          "definition_note": "C_param = PUBLIC engine + true theta + stationary regime; C_full = TRUE engine + true current regime: V_latent mixes regime, pending events and every other public-vs-true state difference",
                          "claimed": 61.8}
    hs = lad["hidden_state"]
    out["F4_pi"] = {f: {h: hs[f][h].get("pi_recovered") for h in hs[f]} for f in ("transport", "cleaning")}
    out["F5_coverage_H1"] = {"public": cov["summary"]["public"]["1"]["coverage90"], "true": cov["summary"]["true"]["1"]["coverage90"], "claimed": [0.573, 0.877]}
    src = inspect.getsource(G.establishment)
    out["F6_lag"] = {"draw": "lag_min ~ U(0, 60) REF, U(0, 120) DIAG (theta, per establishment)" if 'r("lag", 0.0, 60.0 if pop == "REF" else 120.0)' in src else "NOT FOUND",
                     "per_event_law": "lag = floor(-lag_min * log(1 - 0.999999 u)) minutes: exponential with MEAN lag_min, unbounded (not a 0-60 lag)",
                     "zero_lag_kinds": sorted(G.ZERO_LAG)}
    tab = lad["family_table_REF"]["24"]
    fam = {f: {"L2": tab[f]["L2"], "L4": tab[f]["L4"], "L2_minus_L4": tab[f]["L2"] - tab[f]["L4"]}
           for f in ("ready", "confirmation", "care", "arrivals") if f in tab}
    fam["presence_in_table"] = "presence" in tab
    out["F7_M_pub_families_H24"] = {"by_family": fam, "claimed": {"ready": 0.242, "confirmation": 0.299, "care": 0.021, "arrivals": 0.001}}
    cands = candidates()
    ch = Counter(r["L4_choice"] for r in dec["rows"])
    out["F8_objlex_coordination"] = {"L4_choices_with_coordination": sum(v for k, v in ch.items() if cands[k].coordinate),
                                     "L4_choices_total": len(dec["rows"]),
                                     "rule_choices_with_coordination": sum(cands[r["rule_choice"]].coordinate for r in dec["rows"])}
    out["S6_H1_no_window_stats"] = {"nets_has_window_only_b2": "b2_window" in inspect.getsource(nets) and "local_deltas" not in inspect.getsource(nets),
                                    "note": "H1 inputs are the hourly entity graph; B2 uses b2_window; neither uses B0 window statistics"}
    wsrc = inspect.getsource(dataset._window)
    out["S2_window_confirmation_transport_only"] = {"starts_has_transport_requested": '"confirmation": "transport_requested"' in wsrc,
                                                    "offer_in_window": "offer_requested" in wsrc}
    # census of the public/true difference at the 96 decision instants (truth side only)
    space.register()
    census: Counter = Counter()
    at_t: Counter = Counter()
    n_inst = 0
    for part in ("VAL", "HOWM2_REF"):
        for i in range(12):
            ep = G.generate(G.establishment(part, i))
            for hh in INSTANT_HOURS:
                t = (EVAL_DAY * TPD + hh * TPH) * 15
                n_inst += 1
                for ev, av, kind, _s, _u, _v in ep.observations:
                    if ev < t < av:
                        census[kind] += 1
                    elif ev == t and av <= t:
                        at_t[kind] += 1
    out["S2_pending_census_96_instants"] = {"instants": n_inst, "pending_per_instant_by_kind": {k: v / n_inst for k, v in census.most_common()},
                                            "published_at_t_not_in_true_state_per_instant": {k: v / n_inst for k, v in at_t.most_common()},
                                            "note": "true engines at an instant are cloned BEFORE step(t0): events at ev_min == t with lag 0 are public but not yet true"}
    (EV / "howm2/FACTS_CHECK_A2.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
