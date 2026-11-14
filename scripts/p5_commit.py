#!/usr/bin/env python3
"""P5.0 — seed draw (once) and E0/E_k commitment (P5-PROTO-2 § 7). Generates no episode.

* Structure seeds per partition are drawn ONCE with ``secrets`` and sealed in
  evidence/decision_support/p5/SEEDS_SEALED.json (never redrawn; refused if it exists for E0).
* The commitment records SHA-256 of each sorted seed list + salt, the bootstrap seed hash, the
  P5 code, the static feature schema, the protocol/decision documents, and checks that the v6
  engine and its configs are byte-identical to the v6 commit (856a57c).

    python scripts/p5_commit.py --stage E0
    python scripts/p5_commit.py --stage E1 --reason "generator fix after test X"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hospitalos.p5 import GENERATOR_VERSION, P5_PACKAGE_VERSION  # noqa: E402
from hospitalos.p5.features import schema_fingerprint, static_names  # noqa: E402

P5 = ROOT / "evidence" / "decision_support" / "p5"
SEEDS = P5 / "SEEDS_SEALED.json"
V6_COMMIT = "856a57c65fb0d55190addf6c39a45c57913eac07"
PARTITIONS = {"P5a_dev": 10, "P5a_eval": 30, "P5b_train": 24, "P5b_val": 8, "P5b_eval": 30}
RESERVED_ENGINE_SEEDS = {101, 102, 103, 104, 901, 902, 903, 904}
CODE = [
    "src/hospitalos/p5/__init__.py",
    "src/hospitalos/p5/generator.py",
    "src/hospitalos/p5/truth.py",
    "src/hospitalos/p5/eval_adapter.py",
    "src/hospitalos/p5/features.py",
    "src/hospitalos/p5/analysis.py",
    "src/hospitalos/p5/integrity.py",
    "src/hospitalos/p5/pilot.py",
    "scripts/p5_budget_run.py",
    "scripts/p5_commit.py",
    "scripts/p5_pilot.py",
]
DOCS = [
    "docs/decision_support/P5_PROTOCOL_v2.md",
    "docs/decision_support/P5_PROTOCOL_PARAMS_v2.json",
    "docs/decision_support/P5_CHANGES_v1_to_v2.md",
    "docs/decision_support/P5_DECISIONS_v2.json",
    "docs/decision_support/P5_PROTOCOL_v3.md",
    "docs/decision_support/P5_PROTOCOL_PARAMS_v3.json",
]


def sha_file(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def draw_seeds() -> dict[str, object]:
    used: set[int] = set(RESERVED_ENGINE_SEEDS)
    out: dict[str, object] = {"drawn_at_utc": datetime.now(UTC).isoformat(), "method": "secrets.randbits(62)"}
    parts = {}
    for name, n in PARTITIONS.items():
        seeds = []
        while len(seeds) < n:
            s = secrets.randbits(62)
            if s not in used:
                used.add(s)
                seeds.append(s)
        parts[name] = seeds
    out["partitions"] = parts
    out["bootstrap_seed"] = secrets.randbits(62)
    out["salt"] = secrets.token_hex(16)
    return out


def commitment(seeds: dict[str, object]) -> dict[str, object]:
    salt = str(seeds["salt"])
    parts = seeds["partitions"]
    assert isinstance(parts, dict)
    hashes = {
        name: hashlib.sha256((json.dumps(sorted(v)) + salt).encode()).hexdigest() for name, v in parts.items()
    }
    boot = hashlib.sha256((str(seeds["bootstrap_seed"]) + salt).encode()).hexdigest()
    cid = hashlib.sha256(json.dumps({"partitions": hashes, "bootstrap": boot}, sort_keys=True).encode()).hexdigest()
    return {"seed_list_sha256": hashes, "bootstrap_seed_sha256": boot, "commitment_id": cid,
            "sizes": {k: len(v) for k, v in parts.items()}}


def v6_unchanged() -> dict[str, object]:
    diff = subprocess.run(
        ["git", "diff", "--quiet", V6_COMMIT, "--", "src/hospitalos/decision_support", "configs/decision_support"],
        cwd=ROOT,
    )
    untracked = subprocess.run(
        ["git", "status", "--porcelain", "--", "src/hospitalos/decision_support", "configs/decision_support"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", f"{V6_COMMIT}:src/hospitalos/decision_support"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    return {"v6_commit": V6_COMMIT, "decision_support_tree_at_v6": tree,
            "working_tree_identical_to_v6": diff.returncode == 0 and not untracked}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--reason", default="")
    args = ap.parse_args()
    P5.mkdir(parents=True, exist_ok=True)
    if (P5 / f"COMMITMENT_{args.stage}.json").exists():
        print(f"COMMITMENT_{args.stage}.json exists: commitments are never rewritten", file=sys.stderr)
        return 2
    if args.stage == "E0":
        if SEEDS.exists():
            print("SEEDS_SEALED.json already exists: E0 seeds are never redrawn", file=sys.stderr)
            return 2
        SEEDS.write_text(json.dumps(draw_seeds(), indent=1, sort_keys=True) + "\n")
    elif not SEEDS.exists():
        print("no sealed seeds: run E0 first", file=sys.stderr)
        return 2
    seeds = json.loads(SEEDS.read_text())
    v6 = v6_unchanged()
    body = {
        "stage": args.stage,
        "reason": args.reason or ("initial commitment before any generation" if args.stage == "E0" else ""),
        "at_utc": datetime.now(UTC).isoformat(),
        "p5_package": P5_PACKAGE_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seeds": commitment(seeds),
        "seeds_file_sha256": sha_file(str(SEEDS.relative_to(ROOT))),
        "code_sha256": {c: sha_file(c) for c in CODE},
        "feature_schema_sha256": schema_fingerprint(),
        "feature_counts": {"M_agg": len(static_names("M_agg")), "M_ent": len(static_names("M_ent"))},
        "documents_sha256": {d: sha_file(d) for d in DOCS if (ROOT / d).exists()},
        "previous_commitments": sorted(p.name for p in P5.glob("COMMITMENT_E*.json") if p.stem != f"COMMITMENT_{args.stage}"),
        "v6": v6,
    }
    out = P5 / f"COMMITMENT_{args.stage}.json"
    out.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
    print(json.dumps(body, indent=1, sort_keys=True))
    return 0 if v6["working_tree_identical_to_v6"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
