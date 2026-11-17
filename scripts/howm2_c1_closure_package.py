#!/usr/bin/env python3
"""C1 closure envelope (decision n.6): original scientific package (intact, hash-checked), final
report, correctif, C1 ledger + anchor, existing receipt, exploratory logs, MANIFEST.json."""

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad/howm2_packages")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    orig = OUT / "HOWM2_P2_C1_P1_FINAL.zip"
    rec = json.loads((ROOT / "evidence/howm2_c1/packages/C1_P1_FINAL.json").read_text())
    if sha(orig) != rec["sha256"]:
        raise SystemExit("original C1 package hash mismatch")
    items = {
        "scientific_package/HOWM2_P2_C1_P1_FINAL.zip": orig,
        "docs/RAPPORT_C1_PALIER1.md": ROOT / "docs/howm2/c1/RAPPORT_C1_PALIER1.md",
        "docs/NORME_C1_PALIER1.md": ROOT / "docs/howm2/c1/NORME_C1_PALIER1.md",
        "docs/CORRECTIF_C1_CLOTURE.md": ROOT / "docs/howm2/c1/CORRECTIF_C1_CLOTURE.md",
        "ledger/BUDGET_LEDGER_HOWM2_C1.jsonl": ROOT / "evidence/howm2_c1/BUDGET_LEDGER_HOWM2_C1.jsonl",
        "ledger/BUDGET_LEDGER_HOWM2_C1.anchor.json": ROOT / "evidence/howm2_c1/BUDGET_LEDGER_HOWM2_C1.anchor.json",
        "receipt/RESTORE_RECEIPT_C1_P1.json": ROOT / "evidence/howm2_c1/RESTORE_RECEIPT_C1_P1.json",
        "exploratory/C1_LOGS_EXPLORATORY.json": ROOT / "evidence/howm2_c1_closure/C1_LOGS_EXPLORATORY.json",
    }
    man = {"envelope": "HOWM2_C1_CLOSURE_ENVELOPE", "decision": "n.6",
           "scientific_package_intact": {"file": "scientific_package/HOWM2_P2_C1_P1_FINAL.zip", "sha256": rec["sha256"],
                                         "recorded_in": "evidence/howm2_c1/packages/C1_P1_FINAL.json"},
           "note": "the scientific package does not contain its own receipt; the envelope joins them. Training is not reproduced.",
           "files": {k: {"sha256": sha(v), "bytes": Path(v).stat().st_size} for k, v in items.items()}}
    st = Path(tempfile.mkdtemp(prefix="envc1_", dir=OUT))
    for k, v in items.items():
        (st / k).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(v, st / k)
    (st / "MANIFEST.json").write_text(json.dumps(man, indent=1) + "\n")
    z = OUT / "HOWM2_C1_CLOSURE_ENVELOPE.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for p in sorted(st.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(st))
    shutil.rmtree(st)
    fresh = Path(tempfile.mkdtemp(prefix="venvc1_", dir=OUT))
    with zipfile.ZipFile(z) as zf:
        zf.extractall(fresh)
    m = json.loads((fresh / "MANIFEST.json").read_text())
    bad = [k for k, v in m["files"].items() if sha(fresh / k) != v["sha256"]]
    shutil.rmtree(fresh)
    res = {"envelope": z.name, "sha256": sha(z), "bytes": z.stat().st_size, "bad": bad, "manifest": man}
    (ROOT / "evidence/howm2_c1_closure/CLOSURE_ENVELOPE.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps({k: res[k] for k in ("envelope", "sha256", "bytes", "bad")}))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
