#!/usr/bin/env python3
"""HOWM-INT-1 POST-HOC descriptive tables on the completed MAIN panel (not in the frozen analysis; no verdict).

Written after the frozen analysis showed that B* (historical rule, chosen on the VAL closed-loop panel) is the
WORST reference on MAIN while D-HGB is the best. To read the primary result correctly, this script reports, with
the same per-structure means and the same cluster bootstrap (B = 2000, seed 20261117):
  - every guardrail metric for every MAIN policy (mean, 95 % CI);
  - paired W-M minus D-HGB on every metric (wait and guardrails);
  - the relative gain of W-M over D-HGB (ratio bootstrap);
  - the wait difference historical minus W-M and D-HGB minus W-M by family.
Writes evidence/howm_int1/POSTHOC_MAIN.json. Descriptive only: 95 % CIs without multiplicity correction."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/int1"))
import analyse as AN  # noqa: E402

import numpy as np  # noqa: E402

METRICS = ("wait_patient_min",) + AN.GUARD


def main() -> int:
    recs = AN.load("MAIN")
    pols = sorted({p for r in recs for f in r["futures"].values() for p in f})
    out = {"status": "POST_HOC_DESCRIPTIF", "policies": pols,
           "by_policy": {m: {p: AN.boot(AN.per_struct(recs, p, m)) for p in pols} for m in METRICS},
           "W_M_minus_D_hgb": {m: AN.boot(AN.diff(recs, "W_M", "D_hgb", m)) for m in METRICS},
           "relative_gain_W_M_over_D_hgb": AN.ratio_boot(AN.per_struct(recs, "D_hgb"), AN.per_struct(recs, "W_M"))}
    fam = {r["structure"]: r["family"] for r in recs}
    byf = {}
    for ref in ("historical", "D_hgb"):
        d = AN.diff(recs, ref, "W_M")
        for f in sorted(set(fam.values())):
            v = [d[s] for s in d if fam[s] == f]
            byf.setdefault(f, {"structures": len(v)})[f"{ref}_minus_W_M"] = float(np.mean(v))
    out["by_family"] = byf
    sub = AN.load("SUB32")  # F/R1 files of the 32 sub-panel structures; the other policies come from MAIN (same structures)
    subs = {r["structure"] for r in sub}
    pm = {p: {k: v for k, v in AN.per_struct(recs, p).items() if k in subs} for p in pols}
    pm |= {p: AN.per_struct(sub, p) for p in ("F", "R1")}
    out["SUB32_descriptive"] = {"structures": len(subs),
                                "F_minus_R1": AN.boot({s_: pm["F"][s_] - pm["R1"][s_] for s_ in subs}),
                                "historical_minus_W_M": AN.boot({s_: pm["historical"][s_] - pm["W_M"][s_] for s_ in subs}),
                                "D_hgb_minus_W_M": AN.boot({s_: pm["D_hgb"][s_] - pm["W_M"][s_] for s_ in subs}),
                                "F_minus_historical": AN.boot({s_: pm["F"][s_] - pm["historical"][s_] for s_ in subs})}
    (ROOT / "evidence/howm_int1/POSTHOC_MAIN.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({"W_M_minus_D_hgb": out["W_M_minus_D_hgb"], "rel": out["relative_gain_W_M_over_D_hgb"], "by_family": byf}, indent=1))
    for m in ("uncovered_care_min", "staff_hours", "rupture_minutes"):
        print(m, {p: round(v["mean"], 1) for p, v in out["by_policy"][m].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
