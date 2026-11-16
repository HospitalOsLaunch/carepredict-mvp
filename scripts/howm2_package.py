#!/usr/bin/env python3
"""HOWM-2 P2 package: exact source tree (git archive HEAD), HOWM-2 ledger + evidence, freeze, SHA256SUMS;
verified by extraction into a fresh directory."""

import hashlib, json, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(
    "/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad/howm2_packages"
)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    name = sys.argv[1]
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "src", "scripts", "tests", "docs/howm2"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise SystemExit("uncommitted source changes:\n" + dirty)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    OUT.mkdir(parents=True, exist_ok=True)
    st = Path(tempfile.mkdtemp(prefix="pkg2_", dir=OUT))
    subprocess.run(
        ["git", "archive", "--format=tar.gz", "-o", str(st / "source_tree.tar.gz"), "HEAD"],
        cwd=ROOT,
        check=True,
    )
    shutil.copytree(ROOT / "evidence" / "howm2", st / "evidence_howm2")
    shutil.copy(ROOT / "evidence" / "howm1" / "venv_howm_freeze.txt", st / "venv_howm_freeze.txt")
    (st / "RESTORE.md").write_text(
        f"# HOWM-2 package {name}\n\n1. `sha256sum -c SHA256SUMS`\n2. `tar -xzf source_tree.tar.gz` (commit {head})\n"
        "3. Python 3.11.18 + venv_howm_freeze.txt\n4. ladder results: evidence_howm2/ladder/<partition>/<idx>.json;"
        " regenerate one with `python scripts/howm2_ladder.py run --partition HOWM2_REF --start i --stop i+1` in a fresh tree\n"
    )
    files = sorted(p for p in st.rglob("*") if p.is_file())
    (st / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(st)}\n" for p in files))
    z = OUT / f"HOWM2_P2_{name}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(st.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(st))
    shutil.rmtree(st)
    fresh = Path(tempfile.mkdtemp(prefix="v2_", dir=OUT))
    with zipfile.ZipFile(z) as zf:
        zf.extractall(fresh)
    bad = [
        rel
        for h, rel in (ln.split("  ", 1) for ln in (fresh / "SHA256SUMS").read_text().splitlines())
        if sha(fresh / rel) != h
    ]
    shutil.rmtree(fresh)
    res = {"package": z.name, "sha256": sha(z), "bytes": z.stat().st_size, "head": head, "bad": bad}
    (ROOT / "evidence" / "howm2" / "packages").mkdir(exist_ok=True)
    (ROOT / "evidence" / "howm2" / "packages" / f"{name}.json").write_text(
        json.dumps(res, indent=1) + "\n"
    )
    print(json.dumps(res))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
