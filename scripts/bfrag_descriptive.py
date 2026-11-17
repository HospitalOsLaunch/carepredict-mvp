#!/usr/bin/env python3
"""B-FRAG CONF descriptive complements (after the frozen primary analysis; NOT primary, no verdict):
F vs R0 anticipation (Delta AUC with world-clustered CI), per-family AUC72 and losses, plan choices of F,
manifests of partitions and public fields."""

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import bfrag_analyse as A  # noqa: E402

EV = ROOT / "evidence/howm2_bfrag"


def main() -> int:
    from hospitalos.howm.keys import key
    from hospitalos.howm.world import candidates

    rng = np.random.default_rng(A.seed())
    recs = A.load("CONF_D2", "BFRAG_CONF")
    ra = [r for r in recs if not A.active(r)]
    out = {"status": "descriptive complements, computed after the frozen primary analysis; no verdict"}
    d = (A.auc(ra, "F", "72") or 0) - (A.auc(ra, "R0", "72") or 0)
    out["delta_auc72_F_minus_R0"] = {"estimate": d, "ci95": A.boot(ra, lambda i: (A.auc(ra, "F", "72", i) or 0) - (A.auc(ra, "R0", "72", i) or 0), rng)}
    out["delta_auc72_O_minus_F"] = {"estimate": (A.auc(ra, "O", "72") or 0) - (A.auc(ra, "F", "72") or 0)}
    fam = {}
    for f in sorted({r["family"] for r in recs}):
        rf = [r for r in ra if r["family"] == f]
        fam[f] = {"n": len(rf), "rupture72_ref": float(np.mean([y for r in rf for y in A.labels(r, "72")])),
                  "auc72": {m: A.auc(rf, m, "72") for m in A.SCORED},
                  "mean_loss": {m: float(np.mean([A.loss(r, m) for r in rf])) for m in A.DEC},
                  "gain_R0_minus_F": float(np.mean([A.loss(r, "R0") - A.loss(r, "F") for r in rf]))}
    out["per_family"] = fam
    cands = candidates()
    out["plans_chosen"] = {m: {cands[int(k)].cid: int(v) for k, v in zip(*np.unique([r["plans"][m] for r in recs], return_counts=True))} for m in ("R0", "R2", "F", "O")}
    leads = [row["rupture"]["first_onset_tick"] / 4 for r in ra for row in r["eval"]["0"] if row["rupture"]["within"]["168"]]
    out["onset_hours_after_t0_ref"] = {"n": len(leads), "quantiles": [float(np.quantile(leads, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)] if leads else None}
    (EV / "CONF_DESCRIPTIVE.json").write_text(json.dumps(out, indent=1) + "\n")
    # manifests
    parts = {}
    for p, n in (("BFRAG_DEV", 8), ("BFRAG_TUNE", 48), ("BFRAG_CONF", 96)):
        parts[p] = {"size": n, "keys": f"key('HOWM1','{p}',i)", "ekeys_sha256": __import__("hashlib").sha256(json.dumps([key("HOWM1", p, i) for i in range(n)]).encode()).hexdigest(),
                    "use": {"BFRAG_DEV": "operating-range scans (reference policy only) and cost pilot; no comparison",
                            "BFRAG_TUNE": "design iteration 1 (D2), thresholds and competitor choice",
                            "BFRAG_CONF": "single confirmation campaign after FREEZE_BFRAG"}[p]}
    (EV / "MANIFEST_PARTITIONS.json").write_text(json.dumps({"partitions": parts, "disjoint_from": "G0, HOWM2_REF/DIAG, C1 partitions (distinct partition names in the key)"}, indent=1) + "\n")
    pub = {"public_inputs_R0_R1_R2_F": ["observations with avail_min < 15*t0 (strict)", "static description (units, beds incl. buffer beds, rosters, c_tr, c_cl)",
                                         "nominal planned capacity per unit", "public calendar of planned cleaning-capacity reduction",
                                         "B0 parameters fitted on HOWM-1 TRAIN 0-31 (R1)", "REF priors (F)"],
           "simulation_keys_public_methods": "derived from a hash of the public history (core.public_key)",
           "never_in_public_inputs": ["world seed / ekey", "partition and index", "scenario family", "true theta, mechanism, regime", "rupture markers / labels", "evaluation realisations"],
           "privileged_O": ["true engine state at t0", "true theta and mechanism", "true regime at t0"], "tests": ["T-B1", "T-B2", "T-B2b"]}
    (EV / "MANIFEST_PUBLIC_FIELDS.json").write_text(json.dumps(pub, indent=1) + "\n")
    print(json.dumps({k: out[k] for k in ("delta_auc72_F_minus_R0", "delta_auc72_O_minus_F", "plans_chosen", "onset_hours_after_t0_ref")}, indent=1))
    print(json.dumps({f: {"rupt72": round(v["rupture72_ref"], 2), "auc72": {m: (round(a, 2) if a is not None else None) for m, a in v["auc72"].items()}, "gain_R0_minus_F": round(v["gain_R0_minus_F"])} for f, v in fam.items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
