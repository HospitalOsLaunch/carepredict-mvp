#!/usr/bin/env python3
"""Descriptive base rates of a B-FRAG 2 features run (no method, no comparison)."""
import collections
import glob
import json
import sys

import numpy as np

tag, part = sys.argv[1], sys.argv[2]
rows = []
for f in sorted(glob.glob(f"evidence/howm2_bfrag2/runs/{tag}/{part}/*.json")):
    d = json.load(open(f))
    for o in d["origins"]:
        L = o["labels"]
        rows.append((d["structure"], d["family"], o["hour"], L["active"], L["censored"], L["y72"], L["y24"], o["manifest"]))
el = [r for r in rows if not r[3] and not r[4]]
fam = collections.defaultdict(list)
for r in el:
    fam[r[1]].append(r[5])
st = collections.defaultdict(set)
for r in el:
    st[r[0]].add(r[5])
out = {"tag": tag, "part": part, "origins": len(rows), "active": sum(r[3] for r in rows), "censored": sum(r[4] for r in rows),
       "eligible": len(el), "y72_rate": float(np.mean([r[5] for r in el])), "y24_rate": float(np.mean([r[6] for r in el])),
       "manifest_rate": float(np.mean([r[7] for r in el])),
       "y72_rate_non_manifest": float(np.mean([r[5] for r in el if not r[7]])),
       "structures_with_pairs": sum(1 for v in st.values() if v == {0, 1}), "structures": len(st),
       "by_family": {k: {"n": len(v), "y72_rate": float(np.mean(v))} for k, v in sorted(fam.items())}}
print(json.dumps(out, indent=1))
