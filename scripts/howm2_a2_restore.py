#!/usr/bin/env python3
"""HOWM-2 A' restoration receipt: extract the P2 package into a fresh directory, verify SHA256SUMS,
run tests/howm2, regenerate A2.DEC for VAL 0 and HOWM2_REF 0, the L4-N validation, A2.COV and the
L2c score of HOWM2_REF 0, re-run the analyses, and compare with the packaged evidence."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from howm2_restore import close  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    z, py = Path(sys.argv[1]), sys.argv[2]
    t0 = time.time()
    fresh = Path(tempfile.mkdtemp(prefix="restoreA2_", dir=z.parent))
    out = {"package": z.name, "package_sha256": sha(z)}
    with zipfile.ZipFile(z) as zf:
        zf.extractall(fresh)
    out["sha256sums_bad"] = [rel for h, rel in (ln.split("  ", 1) for ln in (fresh / "SHA256SUMS").read_text().splitlines())
                             if sha(fresh / rel) != h]
    tree = fresh / "tree"
    tree.mkdir()
    with tarfile.open(fresh / "source_tree.tar.gz") as tf:
        tf.extractall(tree, filter="data")
    shutil.copytree(fresh / "evidence_howm2", tree / "evidence" / "howm2", dirs_exist_ok=True)
    ev = tree / "evidence/howm2"
    run = lambda *a: subprocess.run([py, *a], cwd=tree, capture_output=True, text=True)  # noqa: E731
    r = run("-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/howm2")
    out["tests_howm2"] = {"exit": r.returncode, "tail": r.stdout.strip().splitlines()[-1:]}
    checks = {}
    for f in ("a2_dec/VAL_000.json", "a2_dec/HOWM2_REF_000.json", "l2c/HOWM2_REF/000.json"):
        ref = json.loads((ev / f).read_text())
        (ev / f).unlink()
        checks[f] = ref
    keep = {k: json.loads((ev / k).read_text()) for k in ("DECISION_A2.json", "L2C_A2.json", "VALIDATION_L4N.json", "COVERAGE_A2.json")}
    run("scripts/howm2_a2_dec.py", "run", "--part", "VAL")
    run("scripts/howm2_a2_dec.py", "run", "--part", "HOWM2_REF")
    run("scripts/howm2_a2_l2c.py", "score")
    regen = {f: bool((ev / f).exists() and close(ref, json.loads((ev / f).read_text()))) for f, ref in checks.items()}
    run("scripts/howm2_a2_dec.py", "analyse")
    run("scripts/howm2_a2_l2c.py", "analyse")
    run("scripts/howm2_a2_valid.py")
    run("scripts/howm2_a2_cov.py")
    same = {k: bool(close(v, json.loads((ev / k).read_text()))) for k, v in keep.items()}
    out.update({"regenerated_identical": regen, "analyses_identical": same,
                "verdict_restored": json.loads((ev / "DECISION_A2.json").read_text())["verdict"]})
    out["seconds"] = round(time.time() - t0, 1)
    out["ok"] = (not out["sha256sums_bad"] and out["tests_howm2"]["exit"] == 0 and all(regen.values()) and all(same.values()))
    shutil.rmtree(fresh)
    (ROOT / "evidence/howm2/RESTORE_RECEIPT_A2.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
