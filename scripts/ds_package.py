#!/usr/bin/env python3
"""Build and seal the restorable P0-P4 delivery package (stdlib + git, no network).

    python3 scripts/ds_package.py build --reference <user's reprise package dir> --out delivery
    python3 scripts/ds_package.py seal --out delivery --receipt <RESTORE_RECEIPT.json> \
        --checks <PACKAGE_CHECKS.json>

build: exact HEAD source tree (git archive; the session clone is shallow), patch series from
the base, the user's reference plan package (unchanged), evidence, docs, configs, contracts,
STATUS.json, restore.sh and SHA256SUMS.
seal (after the restore test and package checks): copies the COMPLETE budget ledger and its
anchor, writes LEDGER_TERMINAL.json and SHA256SUMS.post. No budgeted command may run after the
seal, so the counter restored from the package equals the final receipt.
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
NAME = "HospitalOS_DS_P0-P4_20261114_v4"
LEDGER = ROOT / "evidence/decision_support/BUDGET_LEDGER.jsonl"

RESTORE = r"""#!/bin/sh
# Restore the HospitalOS decision-support P0-P4 work and verify it.
#   sh restore.sh <new_empty_dir>   full: integrity, ledger terminal, tests, regenerated results
#   sh restore.sh --verify-only      integrity of both manifests + ledger terminal only
# Optional env PYTEST_PATH = site-packages holding pytest.
# Source: exact tree of HEAD (source_head.tar; the session clone was shallow). With history:
#   git checkout -b __BRANCH__ __BASE__ && git am patches/*.patch
set -eu
PKG=$(cd "$(dirname "$0")" && pwd)
MODE=full
if [ "${1:-}" = "--verify-only" ]; then MODE=verify; fi
cd "$PKG"
if ! sha256sum -c SHA256SUMS --quiet; then
  echo "ABORT: main manifest check failed; nothing restored or executed" >&2; exit 2
fi
SEALED=no
if [ -f SHA256SUMS.post ]; then
  if ! sha256sum -c SHA256SUMS.post --quiet; then
    echo "ABORT: detached manifest SHA256SUMS.post check failed" >&2; exit 2
  fi
  SEALED=yes
fi
if [ "$SEALED" = yes ]; then
  mkdir -p "$PKG/.verify"
  tar -xf "$PKG/source_head.tar" -C "$PKG/.verify" scripts/ds_budget_run.py
  if ! python3 - "$PKG" <<'PY'
import importlib.util, json, sys
from pathlib import Path
pkg = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("b", pkg / ".verify/scripts/ds_budget_run.py")
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
terminal = json.loads((pkg / "LEDGER_TERMINAL.json").read_text())
ledger = pkg / "ledger/BUDGET_LEDGER.jsonl"
records = b.read_ledger(ledger)  # verifies hash chain + anchor
used = round(b.used_seconds(records), 3)
ok = (len(records) == terminal["records"]
      and records[-1]["record_sha256"] == terminal["last_record_sha256"]
      and used == terminal["used_wall_seconds"])
print(json.dumps({"ledger_records": len(records), "restored_used_wall_seconds": used,
                  "terminal_used_wall_seconds": terminal["used_wall_seconds"],
                  "remaining_wall_seconds": round(600 - used, 3), "match": ok}))
sys.exit(0 if ok else 1)
PY
  then
    rm -rf "$PKG/.verify"; echo "ABORT: ledger terminal mismatch" >&2; exit 6
  fi
  rm -rf "$PKG/.verify"
else
  echo "UNSEALED: ledger terminal not yet written (pre-seal restore test)"
fi
if [ "$MODE" = verify ]; then echo "VERIFY-ONLY: OK (sealed=$SEALED)"; exit 0; fi
TARGET=${1:?usage: sh restore.sh <new_empty_dir> | --verify-only}
if [ -e "$TARGET" ] && [ -n "$(ls -A "$TARGET" 2>/dev/null)" ]; then
  echo "ABORT: target directory is not empty" >&2; exit 3
fi
mkdir -p "$TARGET"
tar -xf "$PKG/source_head.tar" -C "$TARGET"
cd "$TARGET"
HEAD=$(cat "$PKG/HEAD.txt")
export PYTHONPATH="${PYTEST_PATH:+$PYTEST_PATH:}src:."
python3 -m pytest -q -p no:cacheprovider tests/decision_support > restore_pytest.log 2>&1 \
  && T=pass || T=fail
python3 -m hospitalos.decision_support export --out restore_results > /dev/null
python3 - "$PKG" "$TARGET" "$HEAD" "$T" "$SEALED" <<'PY'
import hashlib, json, sys
from pathlib import Path
pkg, target, head, tests, sealed = Path(sys.argv[1]), Path(sys.argv[2]), *sys.argv[3:]
index = json.loads((pkg / "evidence/results/index.json").read_text())
def digest(name):
    return hashlib.sha256((target / "restore_results" / name).read_bytes()).hexdigest()
diff = [f["file"] for f in index["files"] if digest(f["file"]) != f["sha256"]]
summary = (target / "restore_pytest.log").read_text().strip().splitlines()[-1]
receipt = {"test": "T30", "restored_tree_of_head": head, "method": "source_head.tar",
           "package_sealed_at_restore": sealed == "yes", "tests": tests, "pytest": summary,
           "results_compared": len(index["files"]), "results_differing": diff,
           "status": "PASS" if tests == "pass" and not diff else "FAIL"}
(target / "RESTORE_RECEIPT.json").write_text(json.dumps(receipt, indent=1) + "\n")
print(json.dumps(receipt))
sys.exit(0 if receipt["status"] == "PASS" else 1)
PY
"""


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def budget():
    sys.path.insert(0, str(ROOT / "scripts"))
    import ds_budget_run

    return ds_budget_run


def build(reference: Path, out: Path) -> int:
    if git("status", "--porcelain", "--untracked-files=no"):
        print("refusing: tracked changes are not committed", file=sys.stderr)
        return 2
    pkg = out / NAME
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir(parents=True)
    head = git("rev-parse", "HEAD")
    git("archive", "--format=tar", "-o", str(pkg / "source_head.tar"), "HEAD")
    git("format-patch", "-q", "--binary", f"{BASE}..HEAD", "-o", str(pkg / "patches"))
    (pkg / "HEAD.txt").write_text(head + "\n")
    (pkg / "BASE.txt").write_text(
        f"base {BASE} (origin/claude/cockpit-web, linear descendant of main bfa1fa7)\n"
        f"branch {BRANCH}\ncode_commit {head}\nnot pushed\n"
        "session clone is shallow: no self-contained history bundle; source_head.tar + patches\n"
        "evidence commit (ledger identical to LEDGER_TERMINAL.json) follows this code commit\n"
    )
    shutil.copytree(reference, pkg / "reference")
    shutil.copytree(ROOT / "evidence/decision_support", pkg / "evidence")
    shutil.copytree(ROOT / "docs/decision_support", pkg / "docs")
    for name in ("configs/decision_support", "contracts/decision_support"):
        shutil.copytree(ROOT / name, pkg / name.split("/")[0])
    (pkg / "restore.sh").write_text(RESTORE.replace("__BRANCH__", BRANCH).replace("__BASE__", BASE))
    junit = ET.parse(ROOT / "evidence/decision_support/pytest_decision_support.xml").getroot()
    suite = junit if junit.tag == "testsuite" else junit[0]
    e2e = json.loads((ROOT / "evidence/decision_support/e2e_result.json").read_text())
    e2e_react = json.loads((ROOT / "evidence/decision_support/e2e_react_result.json").read_text())
    py311 = ET.parse(ROOT / "evidence/decision_support/pytest_py311.xml").getroot()
    py311 = py311 if py311.tag == "testsuite" else py311[0]
    status = {
        "schema": "HOSPITALOS_DS_STATUS_2",
        "delivery_status": "PARTIAL_WITH_CHECKPOINT",
        "open_gates": [
            "exact Python 3.11.9 patch level: the full suite passes under 3.11.18 (163/163, "
            "results identical); downloading a 3.11.9 interpreter is not covered by the "
            "authorisations",
            "independent re-audit of the P2/P3bis corrections (A01-A10 now pass locally)",
        ],
        "scientific_status": "PROTOTYPE_UNVALIDATED",
        "clinical_validation": False,
        "G2": "NO-GO",
        "synthetic_data_only": True,
        "lots": {
            "P0": "PASS", "P1": "PASS", "P2": "PASS_AFTER_P2BIS", "P3": "PASS_AFTER_P3BIS",
            "P4": "PASS_REACT_INTEGRATED", "P5": "CLOSED", "P6": "CLOSED",
        },
        "audit": {
            "input": "HospitalOS_DS_P0-P4_20261114.zip sha256 431e2e44...cda4e (tree d7844ea)",
            "findings_fixed": ["F01", "F02", "F03", "F04", "F05", "F06", "F07", "F08"],
            "independent_tests_A01_A10": "red 9/10 failing on d7844ea and on b5d09be; "
            "green 10/10 after correction (file kept byte for byte)",
        },
        "branch": BRANCH, "base": BASE, "code_commit": head, "pushed": False,
        "tests": {
            "python_suite_ds_plus_86_hybrid": {
                k: suite.get(k) for k in ("tests", "failures", "errors")
            },
            "e2e_playwright_standalone": {"checks": len(e2e["checks"]), "failed": e2e["failed"]},
            "e2e_playwright_react_cockpit": {
                "checks": len(e2e_react["checks"]), "failed": e2e_react["failed"]
            },
            "cockpit_vitest": "72 passed (66 pre-existing + 6 new; runlog in ledger)",
            "python_3_11_18_full_suite": {
                **{k: py311.get(k) for k in ("tests", "failures", "errors", "skipped")},
                "venv": "isolated; pydantic 2.14.3, numpy 2.4.6, pytest 8.4.2, jsonschema "
                "4.26.0 (installs authorised by the user, charged to the ledger)",
                "results_regenerated_identical": "11/11 byte for byte",
            },
            "T30_restore": "RESTORE_RECEIPT.json (sealed later, SHA256SUMS.post)",
        },
        "budget_at_build": budget().status(LEDGER),
        "archives": {
            "PRIMARY": "completed, criteria failed (documented, not re-evaluated)",
            "A_detached": "authenticated at 2000 for seeds 11/23/37; final 6000 not attested; "
            "not a scientific failure",
        },
        "limits": [
            "npm ci in web/ and the Python 3.11 venv installs were performed under the user's "
            "explicit authorisations; restore.sh replays the Python suite only",
            "tests/hybrid/test_decision_guard.py not run: fit_benchmark fits models (training)",
            "mypy --strict not run",
            "browser e2e run by the author, not independently revalidated",
            "all parameters synthetic; no interviews; no calibration",
        ],
        "not_executed": ["training", "weight loading", "AJ-H inference", "lots B/C",
                         "statistical campaign", "paid API/GPU", "unauthorised network install", "push",
                         "merge", "rebase", "SIH action", "background process"],
    }
    (pkg / "STATUS.json").write_text(json.dumps(status, indent=1, ensure_ascii=False) + "\n")
    files = sorted(p for p in pkg.rglob("*") if p.is_file())
    (pkg / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(pkg)}\n" for p in files))
    print(json.dumps({"package": str(pkg), "files": len(files) + 1, "code_commit": head}))
    return 0


def seal(out: Path, receipt: Path, checks: Path) -> int:
    pkg = out / NAME
    b = budget()
    records = b.read_ledger(LEDGER)  # chain + anchor verified
    (pkg / "ledger").mkdir(exist_ok=True)
    shutil.copy2(LEDGER, pkg / "ledger/BUDGET_LEDGER.jsonl")
    shutil.copy2(b.anchor_path(LEDGER), pkg / "ledger" / b.anchor_path(LEDGER).name)
    shutil.copy2(receipt, pkg / "RESTORE_RECEIPT.json")
    shutil.copy2(checks, pkg / "PACKAGE_CHECKS.json")
    terminal = {
        "records": len(records),
        "commands": sum(r.get("kind") == "command" for r in records),
        "last_record_sha256": records[-1]["record_sha256"],
        "used_wall_seconds": round(b.used_seconds(records), 3),
        "limit_wall_seconds": 600.0,
        "remaining_wall_seconds": round(600.0 - b.used_seconds(records), 3),
        "ledger_file_sha256": sha(LEDGER),
        "rule": "no budgeted command after this seal; the repository evidence commit carries the "
        "same ledger",
    }
    (pkg / "LEDGER_TERMINAL.json").write_text(json.dumps(terminal, indent=1) + "\n")
    post = ["RESTORE_RECEIPT.json", "PACKAGE_CHECKS.json", "LEDGER_TERMINAL.json",
            "ledger/BUDGET_LEDGER.jsonl", f"ledger/{b.anchor_path(LEDGER).name}", "SHA256SUMS"]
    (pkg / "SHA256SUMS.post").write_text("".join(f"{sha(pkg / f)}  {f}\n" for f in post))
    print(json.dumps(terminal))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    pb = sub.add_parser("build")
    pb.add_argument("--reference", type=Path, required=True)
    pb.add_argument("--out", type=Path, required=True)
    ps = sub.add_parser("seal")
    ps.add_argument("--out", type=Path, required=True)
    ps.add_argument("--receipt", type=Path, required=True)
    ps.add_argument("--checks", type=Path, required=True)
    args = parser.parse_args()
    if args.cmd == "build":
        return build(args.reference, args.out)
    return seal(args.out, args.receipt, args.checks)


if __name__ == "__main__":
    raise SystemExit(main())
