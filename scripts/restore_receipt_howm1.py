#!/usr/bin/env python3
"""HOWM-1 restoration receipt (NORM N5): restore the END-of-R1 P2 package into a fresh directory and
re-run, from the package only: (1) hash checks, (2) the HOWM test suite (resume == continuous,
weights_only checkpoints, guards), (3) exact regeneration of 2 DEVTEST corpus files, (4) the full
evaluation of those 2 establishments (all 120 origins) compared with the delivered results.
Not named howm_*.py on purpose: it is not part of the F1-frozen code set.

    restore_receipt_howm1.py <R1_END.zip> <G0.zip> <out_receipt.json>
The corpus BYTES come from the delivered G0 package; the recipe is checked by regenerating 2 files
and comparing their decompressed content (gzip headers carry an mtime/filename, so file hashes differ).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

PY = sys.executable
IGNORE = {"seconds_per_system", "seconds_total"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def strip(x):
    if isinstance(x, dict):
        return {k: strip(v) for k, v in x.items() if k not in IGNORE}
    if isinstance(x, list):
        return [strip(v) for v in x]
    return x


def main() -> int:
    pkg, g0pkg, out_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    t0 = time.time()
    fresh = Path(tempfile.mkdtemp(prefix="howm1_restore_"))
    rec: dict = {"package": pkg.name, "package_sha256": sha(pkg), "fresh_dir": str(fresh)}
    with zipfile.ZipFile(pkg) as z:
        z.extractall(fresh / "pkg")
    bad = [
        rel
        for h, rel in (
            ln.split("  ", 1) for ln in (fresh / "pkg" / "SHA256SUMS").read_text().splitlines()
        )
        if sha(fresh / "pkg" / rel) != h
    ]
    rec["hash_check_bad"] = bad
    tree = fresh / "tree"
    tree.mkdir()
    with tarfile.open(fresh / "pkg" / "source_tree.tar.gz") as t:
        t.extractall(tree, filter="data")
    for run in sorted((fresh / "pkg" / "checkpoints").iterdir()):
        dst = tree / "evidence" / "howm1" / "train" / run.name
        dst.mkdir(parents=True, exist_ok=True)
        for f in run.iterdir():
            if (dst / f.name).exists() and sha(dst / f.name) != sha(f):
                rec.setdefault("checkpoint_mismatch", []).append(str(f))
            shutil.copy(f, dst / f.name)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
    env.update(PYTHONPATH=f"{tree / 'src'}:{tree}", HOWM_CORPUS=str(fresh / "corpus"))
    tests = subprocess.run(  # -rf lists failures
        [
            PY,
            "-m",
            "pytest",
            "-q",
            "-rf",
            "--no-header",
            "-p",
            "no:cacheprovider",
            "-W",
            "ignore::UserWarning",
            "tests/howm",
        ],
        cwd=tree,
        env=env,
        capture_output=True,
        text=True,
    )
    lines = tests.stdout.strip().splitlines()
    rec["tests_in_fresh_tree"] = lines[-1] if lines else tests.stderr[-500:]
    rec["tests_failed"] = [ln for ln in lines if ln.startswith("FAILED")]
    rec["tests_note"] = "T-V0-01 runs 'git diff 856a57c' and needs a git repository; a package tree is not one (checked in the workspace instead)"
    import gzip

    with zipfile.ZipFile(g0pkg) as z:
        names = [n for n in z.namelist() if n.startswith("corpus/")]
        z.extractall(fresh / "g0", members=names)
    rec["g0_package"] = {"name": g0pkg.name, "sha256": sha(g0pkg), "corpus_files": len(names)}
    (fresh / "regen").mkdir()
    regen = []
    for i in (0, 1):
        env_r = dict(env, HOWM_CORPUS=str(fresh / "regen"))
        r = subprocess.run(
            [
                PY,
                "-c",
                f"import json;from hospitalos.howm import corpus as C;print(json.dumps(C.write_establishment('DEVTEST', {i})))",
            ],
            cwd=tree,
            env=env_r,
            capture_output=True,
            text=True,
        )
        json.loads(r.stdout.strip().splitlines()[-1])
        a = gzip.decompress((fresh / "regen" / "DEVTEST" / f"{i:03d}.pkl.gz").read_bytes())
        b = gzip.decompress((fresh / "g0" / "corpus" / "DEVTEST" / f"{i:03d}.pkl.gz").read_bytes())
        regen.append(
            {
                "file": f"DEVTEST/{i:03d}",
                "content_sha256_regenerated": hashlib.sha256(a).hexdigest(),
                "content_sha256_delivered": hashlib.sha256(b).hexdigest(),
                "identical": a == b,
            }
        )
    rec["corpus_regeneration"] = regen
    shutil.copytree(fresh / "g0" / "corpus", fresh / "corpus")
    originals = {}
    for i in (0, 1):
        f = tree / "evidence" / "howm1" / "eval" / "DEVTEST" / f"{i:03d}.json"
        originals[i] = json.loads(f.read_text())
        f.unlink()
    ev = subprocess.run(
        [
            PY,
            "scripts/howm_eval.py",
            "run",
            "--partition",
            "DEVTEST",
            "--start",
            "0",
            "--stop",
            "2",
        ],
        cwd=tree,
        env=env,
        capture_output=True,
        text=True,
    )
    rec["eval_rerun_returncode"] = ev.returncode
    if ev.returncode != 0:
        rec["eval_rerun_stderr_tail"] = ev.stderr[-1500:]
        out_path.write_text(json.dumps(rec, indent=1) + "\n")
        print(json.dumps(rec))
        return 1
    comp = []
    for i in (0, 1):
        new = json.loads(
            (tree / "evidence" / "howm1" / "eval" / "DEVTEST" / f"{i:03d}.json").read_text()
        )
        comp.append(
            {"establishment": i, "identical_excluding_timings": strip(new) == strip(originals[i])}
        )
    rec["metric_recompute"] = comp
    rec["used_workspace"] = False
    rec["seconds"] = round(time.time() - t0, 1)
    rec["ok"] = (
        not bad
        and all(x["identical"] for x in regen)
        and all(x["identical_excluding_timings"] for x in comp)
        and ev.returncode == 0
        and all("T_V0_01" in f for f in rec["tests_failed"])
        and "checkpoint_mismatch" not in rec
    )
    out_path.write_text(json.dumps(rec, indent=1) + "\n")
    print(json.dumps(rec))
    shutil.rmtree(fresh)
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
