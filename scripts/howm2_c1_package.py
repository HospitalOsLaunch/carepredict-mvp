#!/usr/bin/env python3
"""HOWM-2 C1 palier 1 P2 package: exact source tree (git archive HEAD), evidence/howm2_c1 (ledger,
manifests, selection, F-C1, final per-establishment scores, results, checkpoints best/last + state),
evidence/howm2 ledger (decision n.5 notes), freeze, RESTORE.md, SHA256SUMS; verified in a fresh
directory. The training data shards (~270 MB, scratchpad) are NOT packaged: they are regenerable
from the key space (manifest hashes included)."""

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
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "src", "scripts", "tests", "docs/howm2"],
                           cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty:
        raise SystemExit("uncommitted source changes:\n" + dirty)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    OUT.mkdir(parents=True, exist_ok=True)
    st = Path(tempfile.mkdtemp(prefix="pkgc1_", dir=OUT))
    subprocess.run(["git", "archive", "--format=tar.gz", "-o", str(st / "source_tree.tar.gz"), "HEAD"], cwd=ROOT, check=True)
    shutil.copytree(ROOT / "evidence" / "howm2_c1", st / "evidence_howm2_c1")
    (st / "evidence_howm2").mkdir()
    for f in ("BUDGET_LEDGER_HOWM2.jsonl", "BUDGET_LEDGER_HOWM2.anchor.json", "L2C_PARAMS.json"):
        shutil.copy(ROOT / "evidence/howm2" / f, st / "evidence_howm2" / f)
    shutil.copy(ROOT / "evidence/howm1/venv_howm_freeze.txt", st / "venv_howm_freeze.txt")
    (st / "RESTORE.md").write_text(
        f"# HOWM-2 C1 palier 1 package {name}\n\n"
        "1. `sha256sum -c SHA256SUMS`\n"
        f"2. `tar -xzf source_tree.tar.gz` (commit {head}); copy `evidence_howm2_c1/` to `evidence/howm2_c1/`\n"
        "3. Python 3.11.18 + venv_howm_freeze.txt (torch CPU)\n"
        "4. Checkpoints: evidence/howm2_c1/train/<run>/best.pt (hashes in F_C1.json); load with "
        "`hospitalos.howm2.c1.new_model(system, b0(), seed)` + `load_state_dict`\n"
        "5. Analysis: `python scripts/howm2_c1_final.py analyse` (reads evidence/howm2_c1/final)\n"
        "6. Final scores of one establishment: `python scripts/howm2_c1_final.py run --part HOWM2_CEVAL --start i --stop i+1`\n"
        "7. Training data: `python scripts/howm2_c1.py gen --part HOWM2_CTRAIN --shards 0 ... 9` and "
        "`--part HOWM2_CVAL --shards 0` regenerate the shards; compare with DATA_MANIFEST.json (ekeys_sha256)\n"
        "8. Re-training (not part of the receipt): `python scripts/howm2_c1.py train --runs SYS:N:SEED`\n")
    files = sorted(p for p in st.rglob("*") if p.is_file())
    (st / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(st)}\n" for p in files))
    z = OUT / f"HOWM2_P2_{name}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(st.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(st))
    shutil.rmtree(st)
    fresh = Path(tempfile.mkdtemp(prefix="vc1_", dir=OUT))
    with zipfile.ZipFile(z) as zf:
        zf.extractall(fresh)
    bad = [rel for h, rel in (ln.split("  ", 1) for ln in (fresh / "SHA256SUMS").read_text().splitlines()) if sha(fresh / rel) != h]
    shutil.rmtree(fresh)
    res = {"package": z.name, "sha256": sha(z), "bytes": z.stat().st_size, "head": head, "bad": bad}
    (ROOT / "evidence/howm2_c1/packages").mkdir(exist_ok=True)
    (ROOT / f"evidence/howm2_c1/packages/{name}.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
