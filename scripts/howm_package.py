#!/usr/bin/env python3
"""P2 recoverable package (NORM N5): self-contained source tree of HEAD, checkpoints, ledger,
G0 + corpus manifest (+ corpus if < 50 MB), environment freeze, RESTORE.md, howm_restore.py,
SHA256SUMS. Verified by extraction into a fresh directory (hashes + weights_only load).

    howm_package.py <name> [--corpus] [--runs RUN ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hospitalos.howm.corpus import CORPUS  # noqa: E402

OUT = Path(
    "/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad/howm1_packages"
)
EVID = ROOT / "evidence" / "howm1"

RESTORE_MD = """# HOWM-1 — restauration d'un paquet P2

1. `sha256sum -c SHA256SUMS` dans ce dossier.
2. `mkdir tree && tar -xzf source_tree.tar.gz -C tree` : arbre exact du commit `{head}` (aucune base requise).
3. Environnement : Python 3.11.18, `pip install -r tree/evidence/howm1/venv_howm_freeze.txt`
   (torch 2.15.0+cpu depuis l'index CPU officiel) ; couple attendu dans `ENVIRONMENT.json`.
4. Corpus : soit `corpus/` (joint si < 50 Mo), soit régénération exacte :
   `PYTHONPATH=tree/src HOWM_CORPUS=$PWD/corpus_regen python tree/scripts/howm_restore.py regen --partition TRAIN --index 0`
   puis comparaison à `tree/evidence/howm1/CORPUS_MANIFEST.json`.
5. Checkpoints : `checkpoints/<run>/{{last,best}}.pt` (poids, optimiseur, ordonnanceur, RNG, position) ;
   chargement uniquement `torch.load(..., weights_only=True)` après vérification de l'empreinte
   (`state.json`). Reprise : `python tree/scripts/howm_r1.py train ...` après avoir placé `checkpoints/<run>`
   sous `tree/evidence/howm1/train/<run>`.
6. Vérification autonome : `python tree/scripts/howm_restore.py verify --package .`
"""


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build(name: str, with_corpus: bool, runs: list[str]) -> Path:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "src", "scripts", "tests", "docs/howm1"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise SystemExit(f"uncommitted source changes: commit before packaging\n{dirty}")
    OUT.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f"pkg_{name}_", dir=OUT))
    subprocess.run(
        ["git", "archive", "--format=tar.gz", "-o", str(stage / "source_tree.tar.gz"), "HEAD"],
        cwd=ROOT,
        check=True,
    )
    shutil.copy(EVID / "BUDGET_LEDGER_HOWM1.jsonl", stage / "BUDGET_LEDGER_HOWM1.jsonl")
    if (EVID / "BUDGET_LEDGER_HOWM1.anchor.json").exists():
        shutil.copy(
            EVID / "BUDGET_LEDGER_HOWM1.anchor.json", stage / "BUDGET_LEDGER_HOWM1.anchor.json"
        )
    for f in ("COMMITMENT_G0.json", "CORPUS_MANIFEST.json", "venv_howm_freeze.txt"):
        shutil.copy(EVID / f, stage / f)
    env = json.loads(
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "howm_budget_run.py"), "--env"],
            capture_output=True,
            text=True,
        ).stdout
    )
    (stage / "ENVIRONMENT.json").write_text(json.dumps(env, indent=1))
    if with_corpus:
        shutil.copytree(CORPUS, stage / "corpus")
    for r in runs:
        src = EVID / "train" / r
        dst = stage / "checkpoints" / r
        dst.mkdir(parents=True)
        for f in ("last.pt", "best.pt", "state.json"):
            if (src / f).exists():
                shutil.copy(src / f, dst / f)
    (stage / "RESTORE.md").write_text(RESTORE_MD.format(head=head))
    shutil.copy(ROOT / "scripts" / "howm_restore.py", stage / "howm_restore.py")
    files = sorted(p for p in stage.rglob("*") if p.is_file())
    (stage / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(stage)}\n" for p in files))
    (stage / "PACKAGE.json").write_text(
        json.dumps(
            {"name": name, "head": head, "runs": runs, "corpus": with_corpus, "files": len(files)},
            indent=1,
        )
    )
    zpath = OUT / f"HOWM1_P2_{name}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(stage))
    shutil.rmtree(stage)
    return zpath


def verify(zpath: Path) -> dict:
    """Fresh-directory check: hashes, source tree extract, weights_only load of a checkpoint."""
    import torch

    fresh = Path(tempfile.mkdtemp(prefix="verify_", dir=OUT))
    with zipfile.ZipFile(zpath) as z:
        z.extractall(fresh)
    bad = []
    for line in (fresh / "SHA256SUMS").read_text().splitlines():
        h, rel = line.split("  ", 1)
        if sha(fresh / rel) != h:
            bad.append(rel)
    with tarfile.open(fresh / "source_tree.tar.gz") as t:
        names = t.getnames()
    loaded = []
    for st in (
        sorted((fresh / "checkpoints").glob("*/state.json"))
        if (fresh / "checkpoints").exists()
        else []
    ):
        meta = json.loads(st.read_text())
        for which, key in (("last.pt", "last_sha256"), ("best.pt", "best_sha256")):
            p = st.parent / which
            if p.exists() and key in meta:
                if sha(p) != meta[key]:
                    bad.append(str(p.relative_to(fresh)))
                    continue
                obj = torch.load(p, weights_only=True)
                loaded.append({"ckpt": str(p.relative_to(fresh)), "keys": sorted(obj)})
    out = {
        "package": zpath.name,
        "sha256": sha(zpath),
        "bytes": zpath.stat().st_size,
        "bad": bad,
        "tree_files": len(names),
        "checkpoints_loaded_weights_only": loaded,
    }
    shutil.rmtree(fresh)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--corpus", action="store_true")
    ap.add_argument("--runs", nargs="*", default=[])
    a = ap.parse_args()
    z = build(a.name, a.corpus, a.runs)
    res = verify(z)
    (EVID / "packages").mkdir(exist_ok=True)
    (EVID / "packages" / f"{a.name}.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res))
    return 0 if not res["bad"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
