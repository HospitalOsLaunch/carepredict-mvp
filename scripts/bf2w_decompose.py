#!/usr/bin/env python3
"""Decision n.8 s.3: descriptive decomposition of the recorded B-FRAG 2 F-R1 decision gain into exclusive
groups, from the recorded CONF-S files only (no new evaluation). Contribution of a group = sum over its
decisions of (loss_R1 - loss_F) / (n_structures * 3); the sum over groups must equal the recorded mean."""

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import bfrag2_lib as L  # noqa: E402

COORD = "hist_coord_compat"


def parse(aid):
    if aid in ("none", COORD):
        return aid, None, None
    res, w = aid.split("+1_w")
    return "reinforce", res, int(w)


def group(fa, ra):
    if fa == ra:
        return "G1_same_action"
    if fa == COORD:
        return "G2_F_coord_R1_other"
    if ra == COORD:
        return "G3_R1_coord_F_other"
    kf, rf, wf = parse(fa)
    kr, rr, wr = parse(ra)
    if "none" in (fa, ra):
        return "G4a_one_is_none"
    if rf == rr:
        return "G4b_same_resource_other_slot"
    if wf == wr:
        return "G4c_other_resource_same_slot"
    return "G4d_other_resource_other_slot"


def main() -> int:
    res = json.loads((ROOT / "evidence/howm2_bfrag2/RESULTS_BFRAG2_CONF.json").read_text())
    eps = [e for e in L.load("S", "BF2_CONF") if e["structure"] in res["conf_s_structures"]]
    n_s = len({e["structure"] for e in eps})
    rows = []
    for ep in eps:
        acts = ep["decision"]["actions"]
        ids = [a["id"] for a in acts]
        loss = L.eval_loss(ep)
        f, r = ep["decision"]["plans"]["F_planner"]["choice"], ep["decision"]["plans"]["R1_planner"]["choice"]
        rows.append({"structure": ep["structure"], "episode": ep["episode"], "family": ep["family"], "F": ids[f], "R1": ids[r],
                     "group": group(ids[f], ids[r]), "gain": float(loss[r] - loss[f]),
                     "staff_F": acts[f]["staff_hours"], "staff_R1": acts[r]["staff_hours"]})
    per_dec = n_s * 3
    out = {"source": "evidence/howm2_bfrag2/runs/S/BF2_CONF (recorded CONF-S, Mr/Md/E as recorded per file)",
           "recorded_primary_mean": res["C"]["primary_Dstar_minus_F"]["mean"], "n_structures": n_s, "n_decisions": len(rows), "groups": {}}
    for g in sorted({r["group"] for r in rows}):
        rr = [r for r in rows if r["group"] == g]
        out["groups"][g] = {"decisions": len(rr), "structures": len({r["structure"] for r in rr}),
                            "gain_sum_patient_min": float(sum(r["gain"] for r in rr)),
                            "gain_mean_per_decision": float(np.mean([r["gain"] for r in rr])),
                            "contribution_to_primary": float(sum(r["gain"] for r in rr) / per_dec),
                            "staff_hours_F_sum": int(sum(r["staff_F"] for r in rr)), "staff_hours_R1_sum": int(sum(r["staff_R1"] for r in rr)),
                            "decisions_with_F_better": sum(r["gain"] > 0 for r in rr), "decisions_with_R1_better": sum(r["gain"] < 0 for r in rr)}
    tot = sum(g["contribution_to_primary"] for g in out["groups"].values())
    out["sum_of_contributions"] = tot
    out["abs_error_vs_recorded"] = abs(tot - out["recorded_primary_mean"])
    out["check_ok"] = out["abs_error_vs_recorded"] < 1e-6
    out["decisions"] = rows
    out["note"] = "descriptive explanation of the recorded gap; not a new confirmatory test; choice counts do not attribute benefit"
    (ROOT / "evidence/howm2_bfrag2w/DECOMPOSITION_F_R1.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "decisions"}, indent=1))
    return 0 if out["check_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
