#!/usr/bin/env python3
"""Decision n.8 (B-FRAG 2 closure + pilot W) scientific package: git archive HEAD + evidence/howm2_bfrag2 + ledger + RESTORE.md + SHA256SUMS;
verified in a fresh directory."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad/howm2_packages")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    name = sys.argv[1]
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "src", "scripts", "tests", "docs/howm2"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty:
        raise SystemExit("uncommitted source changes:\n" + dirty)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    OUT.mkdir(parents=True, exist_ok=True)
    st = Path(tempfile.mkdtemp(prefix="pkgbw_", dir=OUT))
    subprocess.run(["git", "archive", "--format=tar.gz", "-o", str(st / "source_tree.tar.gz"), "HEAD"], cwd=ROOT, check=True)
    shutil.copytree(ROOT / "evidence/howm2_bfrag2", st / "evidence_howm2_bfrag2")
    shutil.copytree(ROOT / "evidence/howm2_bfrag2w", st / "evidence_howm2_bfrag2w")
    for f in ("BUDGET_LEDGER_HOWM2_B.jsonl", "BUDGET_LEDGER_HOWM2_B.anchor.json"):
        (st / "ledger").mkdir(exist_ok=True)
        shutil.copy(ROOT / "evidence/howm2_bfrag" / f, st / "ledger" / f)
    shutil.copy(ROOT / "evidence/howm1/venv_howm_freeze.txt", st / "venv_howm_freeze.txt")
    (st / "RESTORE.md").write_text(
        f"# Decision n.8 package {name}\n\n1. `sha256sum -c SHA256SUMS`\n2. `tar -xzf source_tree.tar.gz` (commit {head}); copy evidence_howm2_bfrag2/ and evidence_howm2_bfrag2w/ to evidence/\n"
        "3. Python 3.11.18 + venv_howm_freeze.txt (torch 2.15.0+cpu, scikit-learn 1.8.0)\n4. Tests: `python -m pytest tests/bfrag2w tests/bfrag2`\n"
        "5. Closure: `python scripts/bf2w_decompose.py`\n6. Learning: `python scripts/bf2w_models.py train_d`; `python scripts/bf2w_models.py train_w --seeds 0,1,2`\n"
        "7. Analysis: `python scripts/bf2w_analyse.py`\n8. One evaluation decision: delete evidence/howm2_bfrag2w/runs/eval/s<sss>_e<e>.json and run "
        "`python scripts/bf2w_data.py eval --s0 s --s1 s+1 --E 12 --Md 32 --par 1` (the file's own E and Md); one TRAIN origin: `python scripts/bf2w_data.py train --s0 s --s1 s+1 --K 2 --par 1`\n")
    files = sorted(p for p in st.rglob("*") if p.is_file())
    (st / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(st)}\n" for p in files))
    z = OUT / f"HOWM2_P2_{name}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(st.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(st))
    shutil.rmtree(st)
    fresh = Path(tempfile.mkdtemp(prefix="vbw_", dir=OUT))
    with zipfile.ZipFile(z) as zf:
        zf.extractall(fresh)
    bad = [rel for h, rel in (ln.split("  ", 1) for ln in (fresh / "SHA256SUMS").read_text().splitlines()) if sha(fresh / rel) != h]
    shutil.rmtree(fresh)
    res = {"package": z.name, "sha256": sha(z), "bytes": z.stat().st_size, "head": head, "files": len(files), "bad": bad}
    (ROOT / "evidence/howm2_bfrag2w_receipt").mkdir(exist_ok=True)
    (ROOT / f"evidence/howm2_bfrag2w_receipt/PACKAGE_{name}.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
