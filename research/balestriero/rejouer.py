"""Restore the native simulator, rerun the three sealed experiments and verify their digests."""
import argparse
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
ARCHIVE = "HospitalOS_Actions_Ciblees_J7_Code_Poids_Donnees.zip"
EXPECTED = "7adb566b03fb48661984bab010be9965360ab3195a43281f54c9128a790d1c15"


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def restore(parent_archive):
    if digest(parent_archive) != EXPECTED:
        raise ValueError("Unexpected native source ZIP")
    with ZipFile(parent_archive) as archive:
        members = {name.split("/", 1)[1]: name for name in archive.namelist()}
        entries = archive.read(members["MANIFESTE_SHA256.txt"]).decode().splitlines()
        inventory = {name: value for value, name in (entry.split("  ", 1) for entry in entries)}
        if set(inventory) | {"MANIFESTE_SHA256.txt"} != set(members):
            raise ValueError("Native archive inventory changed")
        for name, member in members.items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe archive path")
            contents = archive.read(member)
            checksum = sha256(contents).hexdigest()
            if name in inventory and checksum != inventory[name]:
                raise ValueError(f"Native data corrupted at {name}")
            target = ROOT / "base" / relative
            if target.exists():
                if digest(target) != checksum:
                    raise ValueError(f"Refusing to overwrite a different baseline at {name}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)


def verify_release():
    lines = (ROOT / "MANIFESTE_SHA256.txt").read_text().splitlines()
    for line in lines:
        expected, name = line.split("  ", 1)
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or digest(ROOT / relative) != expected:
            raise ValueError(f"Unexpected release file {name}")
    return len(lines)


def execute(*args, cwd=ROOT):
    subprocess.run([sys.executable, "-m", *args], cwd=cwd, check=True)


def replay_census(module, receipts, workers):
    chain = ["--lock", receipts["gel"]]
    for stage in ("public", "factuel", "verite"):
        execute(module, stage, *chain, "--workers", str(workers))
        chain.extend(["--" + stage, receipts[stage]])


def score_census(module_command, receipts):
    execute(*module_command, "--lock", receipts["gel"], "--public", receipts["public"],
            "--factuel", receipts["factuel"], "--verite", receipts["verite"])


def replay_plans(receipts, workers):
    # The native stage runner resumes completed receipts. Use a fresh directory to force a blind replay.
    with tempfile.TemporaryDirectory(prefix="hospitalos_rejeu_", dir=ROOT.parent) as scratch:
        fresh = Path(scratch)
        shutil.copytree(ROOT / "base", fresh / "base", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "hierarchie", fresh / "hierarchie",
                        ignore=shutil.ignore_patterns("resultats", "__pycache__"))
        output = fresh / "hierarchie/resultats"
        output.mkdir()
        for name in ("poids.npz", "ajustement.json", "validation_dev.json", "gel.json", "gel.sha256"):
            shutil.copyfile(ROOT / "hierarchie/resultats" / name, output / name)
        execute("hierarchie.trial", "assign", "--lock", receipts["gel"], "--workers", str(workers), cwd=fresh)
        if digest(output / "recu_assign.json") != receipts["affectations"]:
            raise ValueError("Recomputed plan assignments differ before outcomes are generated")
        execute("hierarchie.trial", "reveal", "--lock", receipts["gel"], "--assign", receipts["affectations"],
                "--workers", str(workers), cwd=fresh)
        if digest(output / "recu_reveal.json") != receipts["issues"]:
            raise ValueError("Recomputed plan consequences differ")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regenerer", action="store_true", help="Recreate public assignments and all physical trajectories")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--source", type=Path, default=ROOT / "source" / ARCHIVE)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    os.environ["PYTHONPATH"] = ".:base:base/parent"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    print("Fichiers authentifiés", verify_release(), flush=True)
    restore(args.source)
    anchors = json.loads((ROOT / "empreintes.json").read_text())
    cf, plan, projected = (anchors[name] for name in ("contrefactuel", "hierarchie", "projection"))
    for suite, extra in (("cf/tests", []), ("hierarchie", ["-t", "."]), ("contraintes/tests", []), ("revue", ["-t", "."])):
        execute("unittest", "discover", "-s", suite, *extra, "-q")
    if args.regenerer:
        replay_census("cf.experience", cf, args.workers)
        replay_plans(plan, args.workers)
        replay_census("contraintes.essai", projected, args.workers)
    score_census(["cf.mesures"], cf)
    execute("hierarchie.trial", "verdict", "--lock", plan["gel"], "--assign", plan["affectations"],
            "--reveal", plan["issues"])
    score_census(["contraintes.essai", "score"], projected)
    for path, expected in (("cf/resultats/resultats.json", cf["analyse"]),
                           ("hierarchie/resultats/verdict.json", plan["verdict"]),
                           ("contraintes/resultats/verdict.json", projected["verdict"])):
        if digest(ROOT / path) != expected:
            raise ValueError(f"Scientific verdict differs from the retained digest at {path}")
    print("Vérification finale", verify_release(), flush=True)


if __name__ == "__main__":
    main()
