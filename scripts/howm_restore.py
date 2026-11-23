#!/usr/bin/env python3
"""Autonomous restore checks for a HOWM-1 P2 package (no access to the original workspace).

howm_restore.py verify --package DIR        hashes of every file in SHA256SUMS
howm_restore.py regen --partition P --index I   regenerate one corpus file into $HOWM_CORPUS and
                                                compare its SHA-256 with the manifest of the tree
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--package", default=".")
    ap.add_argument("--partition", default="TRAIN")
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--manifest", default="")
    a = ap.parse_args()
    if a.cmd == "verify":
        d = Path(a.package)
        bad = [
            rel
            for h, rel in (ln.split("  ", 1) for ln in (d / "SHA256SUMS").read_text().splitlines())
            if sha(d / rel) != h
        ]
        print(json.dumps({"bad": bad}))
        return 1 if bad else 0
    if a.cmd == "regen":
        from hospitalos.howm import corpus as C

        entry = json.loads(Path(a.manifest or C.MANIFEST).read_text())["files"][
            f"{a.partition}/{a.index:03d}"
        ]
        got = C.write_establishment(a.partition, a.index)
        ok = got["sha256"] == entry["sha256"]
        print(
            json.dumps(
                {
                    "file": entry["file"],
                    "expected": entry["sha256"],
                    "regenerated": got["sha256"],
                    "identical": ok,
                }
            )
        )
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
