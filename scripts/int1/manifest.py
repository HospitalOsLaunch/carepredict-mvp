#!/usr/bin/env python3
"""HOWM-INT-1 corpus manifests (partitions, scenarios, collection policies, hashes)."""
import collections, glob, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")
out = {}
for part in ("INT_TRAIN", "INT_VAL"):
    rows, agg = [], collections.defaultdict(collections.Counter)
    for f in sorted(glob.glob(str(S / "int1_corpus" / part / "s*.npz"))):
        m = json.loads(Path(f).with_suffix(".json").read_text())
        rows.append({"s": m["structure"], "n": m["n"], "family": m["family"], "regime": m["regime"], "bottlenecks": m["bottlenecks"], "K": m["K"],
                     "situations": [{k: x[k] for k in ("episode", "h0", "t", "provenance", "prior_actions")} | {"n_seqs": len(x["seqs"])} for x in m["situations"]],
                     "sha256": hashlib.sha256(Path(f).read_bytes()).hexdigest()})
        agg["n"][m["n"]] += 1
        agg["regime"][m["regime"]] += 1
        for x in m["situations"]:
            agg["provenance"][x["provenance"]] += 1
            agg["h0"][x["h0"]] += 1
    out[part] = {"structures": len(rows), "summary": {k: dict(v) for k, v in agg.items()}, "tier1": "s 0-999", "tier2": "s 0-9999", "rows": rows}
blob = json.dumps(out)
(ROOT / "evidence/howm_int1/MANIFEST_CORPUS.json").write_text(blob)
print(json.dumps({p: {"structures": v["structures"], "summary": v["summary"]} for p, v in out.items()})[:2500], hashlib.sha256(blob.encode()).hexdigest())
