#!/usr/bin/env python3
"""Build the restorable P0-P4 delivery package (stdlib + git, no network).

    python3 scripts/ds_package.py --reference <dir of the user's reprise package> --out delivery

Contents: exact HEAD source tree (git archive), format-patch series from the base, the user's
reference plan package (unchanged), evidence, docs, STATUS.json, restore.sh and SHA256SUMS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "claude/hospitalos-auto-first-p0-p4-s2dywn"
BASE = "a5e737eec2cfdf0f52a68f41b523f928181c03e6"
NAME = "HospitalOS_DS_P0-P4_20261114"

RESTORE = r"""#!/bin/sh
# Restore the HospitalOS decision-support P0-P4 work into a NEW directory and replay it.
# Usage: sh restore.sh <new_empty_dir>   (optional env PYTEST_PATH = site-packages holding pytest)
# Path A (default): exact source tree of HEAD from source_head.tar (the session clone is shallow,
#   so a self-contained git bundle of the whole history cannot be produced).
# Path B (with history): in a clone containing __BASE__, run
#   git checkout -b __BRANCH__ __BASE__ && git am patches/*.patch
set -eu
PKG=$(cd "$(dirname "$0")" && pwd)
TARGET=${1:?usage: sh restore.sh <new_empty_dir>}
cd "$PKG"
if ! sha256sum -c SHA256SUMS --quiet; then
  echo "ABORT: package integrity check failed; nothing restored or executed" >&2
  exit 2
fi
if [ -e "$TARGET" ] && [ -n "$(ls -A "$TARGET" 2>/dev/null)" ]; then
  echo "ABORT: target directory is not empty" >&2; exit 3
fi
mkdir -p "$TARGET"
tar -xf "$PKG/source_head.tar" -C "$TARGET"
cd "$TARGET"
HEAD=$(cat "$PKG/HEAD.txt")
export PYTHONPATH="${PYTEST_PATH:+$PYTEST_PATH:}src:."
python3 -m pytest -q -p no:cacheprovider tests/decision_support > restore_pytest.log 2>&1 && T=pass || T=fail
python3 -m hospitalos.decision_support export --out restore_results > /dev/null
python3 - "$PKG" "$TARGET" "$HEAD" "$T" <<'PY'
import hashlib, json, sys
from pathlib import Path
pkg, target, head, tests = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
index = json.loads((pkg / "evidence/results/index.json").read_text())
diff = [f["file"] for f in index["files"]
        if hashlib.sha256((target / "restore_results" / f["file"]).read_bytes()).hexdigest() != f["sha256"]]
receipt = {"test": "T30", "restored_tree_of_head": head, "method": "source_head.tar",
           "tests": tests, "results_compared": len(index["files"]), "results_differing": diff,
           "status": "PASS" if tests == "pass" and not diff else "FAIL"}
(target / "RESTORE_RECEIPT.json").write_text(json.dumps(receipt, indent=1) + "\n")
print(json.dumps(receipt))
sys.exit(0 if receipt["status"] == "PASS" else 1)
PY
"""


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True,
                          text=True).stdout.strip()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if git("status", "--porcelain", "--untracked-files=no"):
        print("refusing: tracked changes are not committed", file=sys.stderr)
        return 2
    pkg = args.out / NAME
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir(parents=True)
    head = git("rev-parse", "HEAD")
    # The session clone is shallow: a full-history bundle is not self-contained. Ship the exact
    # HEAD tree (git archive) plus the patch series from the base instead.
    git("archive", "--format=tar", "-o", str(pkg / "source_head.tar"), "HEAD")
    git("format-patch", "-q", "--binary", f"{BASE}..HEAD", "-o", str(pkg / "patches"))
    (pkg / "HEAD.txt").write_text(head + "\n")
    (pkg / "BASE.txt").write_text(
        f"base {BASE} (origin/claude/cockpit-web, linear descendant of main bfa1fa7)\n"
        f"branch {BRANCH}\nhead {head}\nnot pushed\n"
        "session clone is shallow: no self-contained history bundle; source_head.tar + patches\n")
    shutil.copytree(args.reference, pkg / "reference")
    shutil.copytree(ROOT / "evidence/decision_support", pkg / "evidence")
    shutil.copytree(ROOT / "docs/decision_support", pkg / "docs")
    for name in ("configs/decision_support", "contracts/decision_support"):
        shutil.copytree(ROOT / name, pkg / name.split("/")[0])
    (pkg / "restore.sh").write_text(RESTORE.replace("__BRANCH__", BRANCH).replace("__BASE__", BASE))

    sys.path.insert(0, str(ROOT / "scripts"))
    import ds_budget_run as budget

    junit = ET.parse(ROOT / "evidence/decision_support/pytest_decision_support.xml").getroot()
    suite = junit if junit.tag == "testsuite" else junit[0]
    e2e = json.loads((ROOT / "evidence/decision_support/e2e_result.json").read_text())
    status = {
        "schema": "HOSPITALOS_DS_STATUS_1",
        "delivery_status": "P0_P4_TECHNICAL_PASS",
        "scientific_status": "PROTOTYPE_UNVALIDATED",
        "clinical_validation": False,
        "G2": "NO-GO",
        "synthetic_data_only": True,
        "lots": {"P0": "PASS", "P1": "PASS", "P2": "PASS", "P3": "PASS",
                 "P4": "PASS_WITH_DECLARED_LIMIT", "P5": "CLOSED", "P6": "CLOSED"},
        "branch": BRANCH, "base": BASE, "head": head, "pushed": False,
        "tests": {
            "decision_support_pytest": {k: suite.get(k) for k in ("tests", "failures", "errors")},
            "e2e_playwright": {"checks": len(e2e["checks"]), "failed": e2e["failed"]},
            "preexisting_hybrid_non_regression": "86 passed (runlog in ledger)",
            "T30_restore": "see RESTORE_RECEIPT.json (produced after packaging)",
        },
        "budget_at_packaging": budget.status(budget.DEFAULT_LEDGER),
        "archives": {
            "PRIMARY": "completed, criteria failed (documented, not re-evaluated)",
            "A_detached": "authenticated at 2000 for seeds 11/23/37; final 6000 not attested; "
                          "not a scientific failure",
        },
        "limits": [
            "React integration of the view not done: npm ci requires an unauthorised network "
            "install; existing 66 Vitest cockpit tests not re-run",
            "tests/hybrid/test_decision_guard.py not runnable (scikit-learn absent)",
            "mypy --strict not run",
            "Python 3.13 used; repository pins 3.11.9",
            "all parameters synthetic; no interviews; no calibration; out-of-sample seeds are "
            "model-based, not real-world performance",
        ],
        "not_executed": ["training", "weight loading", "AJ-H inference", "lots B/C",
                         "statistical campaign", "paid API/GPU", "network install", "push",
                         "SIH action", "background process"],
    }
    (pkg / "STATUS.json").write_text(json.dumps(status, indent=1, ensure_ascii=False) + "\n")
    files = sorted(p for p in pkg.rglob("*") if p.is_file())
    (pkg / "SHA256SUMS").write_text(
        "".join(f"{sha(p)}  {p.relative_to(pkg)}\n" for p in files))
    print(json.dumps({"package": str(pkg), "files": len(files) + 1, "head": head}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
