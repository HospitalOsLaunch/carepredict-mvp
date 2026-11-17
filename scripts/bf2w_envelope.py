#!/usr/bin/env python3
"""Decision n.8 closure envelope: intact scientific package + external receipt + report + ledger + manifest."""

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
    pk = json.loads((ROOT / "evidence/howm2_bfrag2w_receipt/PACKAGE_BW_FINAL.json").read_text())
    z0 = OUT / pk["package"]
    if sha(z0) != pk["sha256"]:
        raise SystemExit("scientific package hash mismatch")
    items = {"scientific_package/" + z0.name: z0,
             "receipt/RESTORE_RECEIPT_BW.json": ROOT / "evidence/howm2_bfrag2w_receipt/RESTORE_RECEIPT_BW.json",
             "docs/RAPPORT_PILOTE_W.md": ROOT / "docs/howm2/bfrag/RAPPORT_PILOTE_W.md",
             "docs/PROTOCOLE_PILOTE_W.md": ROOT / "docs/howm2/bfrag/PROTOCOLE_PILOTE_W.md",
             "docs/ADDENDUM_BFRAG2_CLOTURE.md": ROOT / "docs/howm2/bfrag/ADDENDUM_BFRAG2_CLOTURE.md",
             "docs/VERIFICATION_NUMERIQUE_BFRAG2.md": ROOT / "docs/howm2/bfrag/VERIFICATION_NUMERIQUE_BFRAG2.md",
             "docs/HOWM2_DECISION_8.json": ROOT / "docs/howm2/HOWM2_DECISION_8.json",
             "ledger/BUDGET_LEDGER_HOWM2_B.jsonl": ROOT / "evidence/howm2_bfrag/BUDGET_LEDGER_HOWM2_B.jsonl",
             "ledger/BUDGET_LEDGER_HOWM2_B.anchor.json": ROOT / "evidence/howm2_bfrag/BUDGET_LEDGER_HOWM2_B.anchor.json"}
    man = {"envelope": "HOWM2_BW_CLOSURE_ENVELOPE", "decision": "n.8",
           "scientific_package": {"file": "scientific_package/" + z0.name, "sha256": pk["sha256"], "intact": True},
           "receipt_is_external": True, "previous_envelope": "HOWM2_BFRAG2_CLOSURE_ENVELOPE.zip (B-FRAG 2, decision n.7, unchanged)",
           "note": "the ledger copy and the report here are later than the scientific package (package, receipt, delivery section)",
           "files": {k: {"sha256": sha(v), "bytes": Path(v).stat().st_size} for k, v in items.items()}}
    st = Path(tempfile.mkdtemp(prefix="envbw_", dir=OUT))
    for k, v in items.items():
        (st / k).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(v, st / k)
    (st / "MANIFEST.json").write_text(json.dumps(man, indent=1) + "\n")
    z = OUT / "HOWM2_BW_CLOSURE_ENVELOPE.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for p in sorted(st.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(st))
    shutil.rmtree(st)
    fresh = Path(tempfile.mkdtemp(prefix="venvbw_", dir=OUT))
    with zipfile.ZipFile(z) as zf:
        zf.extractall(fresh)
    m = json.loads((fresh / "MANIFEST.json").read_text())
    bad = [k for k, v in m["files"].items() if sha(fresh / k) != v["sha256"]]
    shutil.rmtree(fresh)
    res = {"envelope": z.name, "sha256": sha(z), "bytes": z.stat().st_size, "bad": bad}
    (ROOT / "evidence/howm2_bfrag2w_receipt/CLOSURE_ENVELOPE_BW.json").write_text(json.dumps({**res, "manifest": man}, indent=1) + "\n")
    print(json.dumps(res))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
