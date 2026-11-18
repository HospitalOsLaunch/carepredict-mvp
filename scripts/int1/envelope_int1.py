#!/usr/bin/env python3
"""HOWM-INT-1 closure envelope (decision n.9): intact scientific archive + fresh-environment receipt (external to
the archive) + rehearsal summary + report, protocol, demo, decision + final ledger + manifest. Verified after zipping.

    envelope_int1.py NAME   (NAME = the archive name given to package_int1.py)"""

import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad/int1_packages")
REC = ROOT / "evidence/howm_int1_receipt"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main() -> int:
    name = sys.argv[1]
    pk = json.loads((REC / f"PACKAGE_{name}.json").read_text())
    z0 = OUT / pk["package"]
    if sha(z0) != pk["sha256"]:
        raise SystemExit("scientific archive hash mismatch")
    rc = json.loads((REC / "RESTORE_RECEIPT_INT1.json").read_text())
    if rc["archive_sha256"] != pk["sha256"]:
        raise SystemExit("receipt was not made on this archive")
    items = {"scientific_archive/" + z0.name: z0,
             "receipt/RESTORE_RECEIPT_INT1.json": REC / "RESTORE_RECEIPT_INT1.json",
             "receipt/REHEARSAL_SUMMARY.json": REC / "REHEARSAL_SUMMARY.json",
             f"receipt/PACKAGE_{name}.json": REC / f"PACKAGE_{name}.json",
             "docs/RAPPORT_INT1.md": ROOT / "docs/howm_int1/RAPPORT_INT1.md",
             "docs/PROTOCOLE_INT1.md": ROOT / "docs/howm_int1/PROTOCOLE_INT1.md",
             "docs/DEMO.md": ROOT / "docs/howm_int1/DEMO.md",
             "docs/AVANCEMENT.md": ROOT / "docs/howm_int1/AVANCEMENT.md",
             "docs/ESTIMATION_FIN.md": ROOT / "docs/howm_int1/ESTIMATION_FIN.md",
             "docs/HOWM2_DECISION_9.json": ROOT / "docs/howm2/HOWM2_DECISION_9.json",
             "docs/MANDAT_HOWM2_DECISION_9_HOWM_INT_1.md": ROOT / "docs/howm2/inputs/MANDAT_HOWM2_DECISION_9_HOWM_INT_1.md",
             "results/RESULTS_INT1.json": ROOT / "evidence/howm_int1/RESULTS_INT1.json",
             "results/POSTHOC_MAIN.json": ROOT / "evidence/howm_int1/POSTHOC_MAIN.json",
             "results/FREEZE_INT1.json": ROOT / "evidence/howm_int1/FREEZE_INT1.json",
             "ledger/LEDGER_INT1.jsonl": ROOT / "evidence/howm_int1/LEDGER_INT1.jsonl",
             "ledger/LEDGER_INT1.anchor.json": ROOT / "evidence/howm_int1/LEDGER_INT1.anchor.json"}
    man = {"envelope": "HOWM_INT1_CLOSURE_ENVELOPE", "decision": "n.9 (HOWM-INT-1)",
           "status": "PROTOTYPE_UNVALIDATED; clinical_validation=false; G2=NO-GO",
           "scientific_archive": {"file": "scientific_archive/" + z0.name, "sha256": pk["sha256"], "intact": True, "commit": pk["head"]},
           "receipt": {"ok": rc["ok"], "made_on_archive_sha256": rc["archive_sha256"], "external_to_archive": True,
                       "sections": {k: rc[k].get("ok") for k in ("setup", "tests", "load", "analysis", "regen", "refit")}},
           "previous_envelope": "HOWM2_BW_CLOSURE_ENVELOPE.zip (decision n.8, unchanged)",
           "note": "the ledger copy and report here may be later than the archive (receipt, envelope and delivery records); no push, no external publication",
           "files": {k: {"sha256": sha(v), "bytes": Path(v).stat().st_size} for k, v in items.items()}}
    st = Path(tempfile.mkdtemp(prefix="envint1_", dir=OUT))
    for k, v in items.items():
        (st / k).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(v, st / k)
    (st / "MANIFEST.json").write_text(json.dumps(man, indent=1) + "\n")
    z = OUT / "HOWM_INT1_CLOSURE_ENVELOPE.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for p in sorted(st.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(st))
    shutil.rmtree(st)
    fresh = Path(tempfile.mkdtemp(prefix="venvint1_", dir=OUT))
    with zipfile.ZipFile(z) as zf:
        zf.extractall(fresh)
    m = json.loads((fresh / "MANIFEST.json").read_text())
    bad = [k for k, v in m["files"].items() if sha(fresh / k) != v["sha256"]]
    shutil.rmtree(fresh)
    res = {"envelope": z.name, "sha256": sha(z), "bytes": z.stat().st_size, "bad": bad}
    (REC / "CLOSURE_ENVELOPE_INT1.json").write_text(json.dumps({**res, "manifest": man}, indent=1) + "\n")
    print(json.dumps(res))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
