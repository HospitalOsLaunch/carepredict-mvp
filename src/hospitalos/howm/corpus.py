"""Corpus files, manifest, G0 commitment and read guards.

Files live outside git (regenerable from G0 + code); each file's SHA-256 is in the manifest and is
checked before every load (pickles are self-produced; never loaded unless the hash matches).
DEVTEST / DIAG_DEV may be generated at G0 but are READ only after F1 (guard), exactly once.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import pickle
from pathlib import Path
from typing import Any

from .generator import PARTITION_SIZES, SEALED, establishment, generate
from .keys import key

ROOT = Path(__file__).resolve().parents[3]
EVID = ROOT / "evidence" / "howm1"
CORPUS = Path(
    os.environ.get(
        "HOWM_CORPUS",
        "/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad/howm1_corpus",
    )
)
MANIFEST = EVID / "CORPUS_MANIFEST.json"
F1_FILE = EVID / "F1.json"
ORIGINS = {
    "TRAIN": list(range(24, 166, 3)),
    "VAL": list(range(24, 144)),
    "DEVTEST": list(range(24, 144)),
    "DIAG_DEV": list(range(24, 144)),
}
GUARDED = {"DEVTEST", "DIAG_DEV"}


class GuardError(RuntimeError):
    pass


def sha_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def code_hashes() -> dict[str, str]:
    files = sorted((ROOT / "src" / "hospitalos" / "howm").glob("*.py")) + sorted(
        (ROOT / "scripts").glob("howm_*.py")
    )
    return {str(f.relative_to(ROOT)): sha_file(f) for f in files}


def sealed_seed_digest() -> str:
    ek = [str(key("HOWM1", p, i)) for p in sorted(SEALED) for i in range(PARTITION_SIZES[p])]
    return hashlib.sha256("|".join(ek).encode()).hexdigest()


def corpus_path(partition: str, index: int) -> Path:
    return CORPUS / partition / f"{index:03d}.pkl.gz"


def write_establishment(partition: str, index: int) -> dict[str, Any]:
    from .dataset import build

    if partition in SEALED:
        raise GuardError("sealed partition")
    ep = generate(establishment(partition, index), keep_instants=partition != "TRAIN")
    est = build(ep, ORIGINS[partition])
    p = corpus_path(partition, index)
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wb", compresslevel=3) as f:
        pickle.dump({"episode": ep, "data": est}, f, protocol=pickle.HIGHEST_PROTOCOL)
    return {
        "file": str(p.relative_to(CORPUS)),
        "sha256": sha_file(p),
        "bytes": p.stat().st_size,
        "rejected_actions": ep.rejections,
        "population": ep.spec.population,
        "mech": ep.spec.mech,
    }


def manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text())


def f1_recorded() -> bool:
    if not F1_FILE.exists():
        return False
    from .ledger import notes

    return any(r.get("kind") == "F1" for r in notes())


def load(partition: str, index: int, allow_guarded: bool = False) -> dict[str, Any]:
    if partition in SEALED:
        raise GuardError("sealed partition")
    if partition in GUARDED and not (allow_guarded and f1_recorded()):
        raise GuardError(
            f"{partition} cannot be read before F1 (and only by the evaluation command)"
        )
    entry = manifest()["files"][f"{partition}/{index:03d}"]
    p = CORPUS / entry["file"]
    if sha_file(p) != entry["sha256"]:
        raise GuardError(f"corpus file hash mismatch: {p}")
    with gzip.open(p, "rb") as f:
        return pickle.load(f)  # self-produced file, hash-checked against the manifest
