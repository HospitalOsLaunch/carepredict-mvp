#!/usr/bin/env python3
"""HOWM-2 A restoration receipt: extract the P2 package into a fresh directory, verify SHA256SUMS,
unpack the source tree, run tests/howm2, regenerate two ladder establishments (HOWM2_REF 0 and
HOWM2_DIAG 0) and the analysis from the packaged evidence, and compare with the packaged results."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def close(a, b, tol=1e-9) -> bool:
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(close(a[k], b[k], tol) for k in a)
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            return a is b
        if math.isnan(a) and math.isnan(b):
            return True
        return abs(a - b) <= tol * max(1.0, abs(a))
    return a == b


def main() -> int:
    z = Path(sys.argv[1])
    py = sys.argv[2]
    t0 = time.time()
    fresh = Path(tempfile.mkdtemp(prefix="restore2_", dir=z.parent))
    out = {"package": z.name, "package_sha256": sha(z)}
    with zipfile.ZipFile(z) as zf:
        zf.extractall(fresh)
    bad = [rel for h, rel in (ln.split("  ", 1) for ln in (fresh / "SHA256SUMS").read_text().splitlines())
           if sha(fresh / rel) != h]
    out["sha256sums_bad"] = bad
    tree = fresh / "tree"
    tree.mkdir()
    with tarfile.open(fresh / "source_tree.tar.gz") as tf:
        tf.extractall(tree, filter="data")
    shutil.copytree(fresh / "evidence_howm2", tree / "evidence" / "howm2", dirs_exist_ok=True)
    r = subprocess.run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/howm2"], cwd=tree,
                       capture_output=True, text=True)
    out["tests_howm2"] = {"exit": r.returncode, "tail": r.stdout.strip().splitlines()[-1:]}
    regen = {}
    for part in ("HOWM2_REF", "HOWM2_DIAG"):
        f = tree / "evidence/howm2/ladder" / part / "000.json"
        ref = json.loads(f.read_text())
        f.unlink()
        rr = subprocess.run([py, "scripts/howm2_ladder.py", "run", "--partition", part, "--start", "0",
                             "--stop", "1", "--workers", "1", "--budget", "200"], cwd=tree,
                            capture_output=True, text=True)
        new = json.loads(f.read_text()) if f.exists() else None
        same = new is not None and all(close(ref[k], new[k]) for k in ("acc", "pits", "mech", "population"))
        regen[part] = {"exit": rr.returncode, "identical_acc_pits": bool(same)}
    out["ladder_regenerated"] = regen
    pk = json.loads((tree / "evidence/howm2/LADDER_A.json").read_text())
    ra = subprocess.run([py, "scripts/howm2_analyse.py"], cwd=tree, capture_output=True, text=True)
    nw = json.loads((tree / "evidence/howm2/LADDER_A.json").read_text())
    out["analysis"] = {"exit": ra.returncode, "verdict_packaged": pk["criterion"]["verdict"],
                       "verdict_restored": nw["criterion"]["verdict"],
                       "criterion_identical": bool(close(pk["criterion"], nw["criterion"])),
                       "whole_file_identical": bool(close(pk, nw))}
    out["seconds"] = round(time.time() - t0, 1)
    out["ok"] = (not bad and out["tests_howm2"]["exit"] == 0
                 and all(v["identical_acc_pits"] for v in regen.values())
                 and out["analysis"]["criterion_identical"])
    shutil.rmtree(fresh)
    (ROOT / "evidence/howm2/RESTORE_RECEIPT_A.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
