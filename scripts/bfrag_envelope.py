#!/usr/bin/env python3
"""B-FRAG closure envelope: intact scientific package + external receipt + report + ledger + manifest."""

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
    pk = json.loads((ROOT / "evidence/howm2_bfrag/packages/BFRAG_FINAL.json").read_text())
    z0 = OUT / pk["package"]
    if sha(z0) != pk["sha256"]:
        raise SystemExit("scientific package hash mismatch")
    items = {"scientific_package/" + z0.name: z0,
             "receipt/RESTORE_RECEIPT_BFRAG.json": ROOT / "evidence/howm2_bfrag_receipt/RESTORE_RECEIPT_BFRAG.json",
             "docs/RAPPORT_BFRAG.md": ROOT / "docs/howm2/bfrag/RAPPORT_BFRAG.md",
             "docs/PROTOCOLE_BFRAG.md": ROOT / "docs/howm2/bfrag/PROTOCOLE_BFRAG.md",
             "ledger/BUDGET_LEDGER_HOWM2_B.jsonl": ROOT / "evidence/howm2_bfrag/BUDGET_LEDGER_HOWM2_B.jsonl",
             "ledger/BUDGET_LEDGER_HOWM2_B.anchor.json": ROOT / "evidence/howm2_bfrag/BUDGET_LEDGER_HOWM2_B.anchor.json"}
    man = {"envelope": "HOWM2_BFRAG_CLOSURE_ENVELOPE", "decision": "n.6",
           "scientific_package": {"file": "scientific_package/" + z0.name, "sha256": pk["sha256"], "intact": True},
           "receipt_is_external": True, "c1_closure_envelope": "HOWM2_C1_CLOSURE_ENVELOPE.zip (separate, see evidence/howm2_c1_closure/CLOSURE_ENVELOPE.json)",
           "note": "the ledger copy here may contain records written after the scientific package was built (package, receipt)",
           "files": {k: {"sha256": sha(v), "bytes": Path(v).stat().st_size} for k, v in items.items()}}
    st = Path(tempfile.mkdtemp(prefix="envbf_", dir=OUT))
    for k, v in items.items():
        (st / k).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(v, st / k)
    (st / "MANIFEST.json").write_text(json.dumps(man, indent=1) + "\n")
    z = OUT / "HOWM2_BFRAG_CLOSURE_ENVELOPE.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for p in sorted(st.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(st))
    shutil.rmtree(st)
    fresh = Path(tempfile.mkdtemp(prefix="venvbf_", dir=OUT))
    with zipfile.ZipFile(z) as zf:
        zf.extractall(fresh)
    m = json.loads((fresh / "MANIFEST.json").read_text())
    bad = [k for k, v in m["files"].items() if sha(fresh / k) != v["sha256"]]
    shutil.rmtree(fresh)
    res = {"envelope": z.name, "sha256": sha(z), "bytes": z.stat().st_size, "bad": bad}
    (ROOT / "evidence/howm2_bfrag_receipt/CLOSURE_ENVELOPE_BFRAG.json").write_text(json.dumps({**res, "manifest": man}, indent=1) + "\n")
    print(json.dumps(res))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
