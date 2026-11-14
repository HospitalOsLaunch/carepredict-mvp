#!/usr/bin/env python3
"""Read-only completeness check of the ORIGINAL P5a run folders (redelivery, no new experiment).

Reads only JSON files: imports no HospitalOS module, generates and simulates nothing.

    python -I scripts/p5_complement_check.py --root .                 # repository copy
    python -I scripts/p5_complement_check.py --root <extracted package> # fresh extraction
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

DEV = "evidence/decision_support/p5/p5a/P5a_dev/runs/0108da5768b4c2023181"
EVAL = "evidence/decision_support/p5/p5a/P5a_eval/runs/ece90db4e6159a03bf84"
REQUIRED = [f"{run}/{f}" for run in (DEV, EVAL) for f in ("RUN_IDENTITY.json", "pilot_parents.jsonl", "structures.jsonl")] + [
    "evidence/decision_support/p5/p5a/F_a.json",
    "evidence/decision_support/p5/p5a/RESULTS_P5a.json",
    "evidence/decision_support/p5/p5a/PRECISION_DEV.json",
]
LEDGER_54 = {  # hashes recorded in the P5 ledger (record 54) before the first delivery
    f"{EVAL}/pilot_parents.jsonl": "445cf7de829c0ab69fd7c92c84247b0191ee417291687507d95d587423c64347",
    f"{EVAL}/structures.jsonl": "3d965995e291ffbcc41a87bb83e9e34ee38288876a975acf286a967eaa968c89",
    "evidence/decision_support/p5/p5a/RESULTS_P5a.json": "1a7974176def47c24c6ee929e357de56824a43cf77ffa78148bbd2cc15d85c89",
    "evidence/decision_support/p5/p5a/F_a.json": "055a4d2692472f6a6f64f51bea876bd5be808acc90c50bb9891f606af9b7a6bc",
}
EXPECTED = {DEV: {"partition": "P5a_dev", "structures": 10, "parents": 100}, EVAL: {"partition": "P5a_eval", "structures": 30, "parents": 300}}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check_run(root: Path, run: str) -> dict:
    d = root / run
    ident = json.loads((d / "RUN_IDENTITY.json").read_text())
    recs = [json.loads(x) for x in (d / "pilot_parents.jsonl").read_text().splitlines()]
    meta = [json.loads(x) for x in (d / "structures.jsonl").read_text().splitlines()]
    exp = EXPECTED[run]
    problems = []
    if ident["run_id"] != run.rsplit("/", 1)[1]:
        problems.append("run_id_differs_from_folder")
    if ident["partition"] != exp["partition"] or int(ident["K"]) != 3 or ident["regimes"] != ["R1", "R2"]:
        problems.append("identity_parameters")
    if len(recs) != exp["parents"] or len(meta) != exp["structures"]:
        problems.append(f"dimensions:{len(recs)}/{len(meta)}")
    if {r["run_id"] for r in recs} != {ident["run_id"]} or {m["run_id"] for m in meta} != {ident["run_id"]}:
        problems.append("foreign_run_id_in_records")
    if {m["structure_id"] for m in meta} != set(ident["structures"]) or {r["structure_id"] for r in recs} != set(ident["structures"]):
        problems.append("structure_ids_differ_from_identity")
    keys = {(r["structure_id"], r["parent_index"]) for r in recs}
    if len(keys) != len(recs):
        problems.append("duplicate_parent")
    per_structure = {}
    for r in recs:
        per_structure[r["structure_id"]] = per_structure.get(r["structure_id"], 0) + 1
        n = r["n_plans"]
        if len(r["plans"]) != n or not 0 <= r["chosen_index"] < n or r["plans"][0]["class"] != "H":
            problems.append(f"plan_shape:{r['structure_id']}:{r['parent_index']}")
        for reg in ("R1", "R2"):
            U = r["outcomes"][reg]["U"]
            if len(U) != 3 or any(len(row) != n for row in U):
                problems.append(f"outcome_shape:{reg}:{r['structure_id']}:{r['parent_index']}")
    if set(per_structure.values()) != {10}:
        problems.append("parents_per_structure")
    supports = {c: sum(any(p["class"] == c for p in r["plans"]) for r in recs) for c in ("C", "R", "CR")}
    chosen = {}
    for r in recs:
        c = r["plans"][r["chosen_index"]]["class"]
        chosen[c] = chosen.get(c, 0) + 1
    cand = sum(m["candidates"] for m in meta)
    excl = sum(sum(m["exclusions"].values()) for m in meta)
    return {"run": run, "identity": {k: ident[k] for k in ("run_id", "partition", "K", "regimes", "n_parents", "commitment_stage")},
            "parents": len(recs), "structures": len(meta), "regimes": ["R1", "R2"], "K": 3,
            "candidates": cand, "excluded": excl,
            "class_support_parents": supports, "chosen_class_counts": chosen,
            "abstentions": sum(bool(r["abstention_as_habitual"]) for r in recs),
            "problems": problems}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    root = Path(args.root)
    missing = [f for f in REQUIRED if not (root / f).is_file()]
    hashes = {f: sha(root / f) for f in REQUIRED if (root / f).is_file()}
    ledger_check = {f: {"expected": h, "actual": hashes.get(f), "ok": hashes.get(f) == h} for f, h in LEDGER_54.items()}
    runs = [check_run(root, r) for r in (DEV, EVAL)] if not missing else []
    ok = not missing and all(v["ok"] for v in ledger_check.values()) and all(not r["problems"] for r in runs)
    body = {"schema": "HOSPITALOS_P5a_COMPLETENESS_1", "root": str(root.resolve()) if args.root != "." else ".",
            "required_files": REQUIRED, "missing": missing, "sha256": hashes, "ledger_54_hashes": ledger_check,
            "runs": runs, "complete_and_matching": ok}
    text = json.dumps(body, indent=1, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    print(json.dumps({"complete_and_matching": ok, "missing": missing,
                      "runs": [{k: r[k] for k in ("parents", "structures", "class_support_parents", "problems")} for r in runs]}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
