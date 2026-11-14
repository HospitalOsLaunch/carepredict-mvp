"""Development smoke: generate 2 establishments, print basic statistics (no model)."""
import time, json, sys
from collections import Counter
from hospitalos.howm.generator import establishment, generate
for part, i in (("TRAIN", 0), ("DIAG_DEV", 0)):
    t0 = time.time(); ep = generate(establishment(part, i), keep_instants=True); dt = time.time() - t0
    kinds = Counter(o[2] for o in ep.observations)
    occ = [h["A"]["occupancy"] + h["B"]["occupancy"] for h in ep.hourly]
    unc = sum(max(0, d - 60 * ep.capacity.get(k, 0)) for k, d in ep.demand.items())
    deps = sum(1 for s in ep.stays.values() if s["departed"] is not None)
    print(json.dumps({"part": part, "sec": round(dt, 2), "beds": ep.spec.beds, "c_tr": ep.spec.c_tr, "c_cl": ep.spec.c_cl, "mech": ep.spec.mech,
        "rejected": ep.rejections, "obs": len(ep.observations), "occ_min_max_mean": [min(occ), max(occ), round(sum(occ)/len(occ), 1)],
        "departures": deps, "uncovered_total": round(unc), "instants": sorted(ep.instants), "kinds": dict(kinds)}))
