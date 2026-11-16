import json, sys, time
from hospitalos.howm.b0 import B0Params
from hospitalos.howm2 import space
from hospitalos.howm2.ladder import run_establishment, level_L, CRITERION_FAMILIES
space.register()
p = B0Params.from_json(json.load(open("evidence/howm1/B0_PARAMS.json")))
for part in ("HOWM2_REF", "HOWM2_DIAG"):
    r = run_establishment(part, 0, p)
    print(part, r["seconds"], r["timing"], r["mech"])
    for h in ("1", "6", "24"):
        print(" h", h, {lv: round(level_L(r, lv, h, CRITERION_FAMILIES), 4) for lv in r["acc"]})
    print(" fam h24", {lv: {f: (round(v[0] / v[1], 3) if v[1] else None, v[1]) for f, v in r["acc"][lv]["24"].items()} for lv in r["acc"]})
