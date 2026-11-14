#!/usr/bin/env python3
"""P5A-D02 isolation check on 50 P5a episodes (adopted; POST-FREEZE; lot P5.3).

    select                       procedure + selection (ids only), written before any check
    check --from i --to j        episodes i..j-1 of the recorded selection (resumable, < 30 s)
    summary                      aggregate receipts

Before anything: effective commitment verified, in-process (Python, freeze) pair approved.
`check` refuses unless the ledger holds an `isolation_procedure` note matching the procedure
file, the selection and the current module; any failure writes ISOLATION_FAILURE.json and
blocks further checks (no correction, no substitution).
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import p5_budget_run as runner  # noqa: E402

from hospitalos.decision_support.planner import Settings  # noqa: E402
from hospitalos.decision_support.snapshot import load_profile  # noqa: E402
from hospitalos.p5 import integrity  # noqa: E402
from hospitalos.p5 import isolation50 as I  # noqa: E402
from hospitalos.p5.pilot import RuntimeRefused, check_runtime, running_environment, structure_id  # noqa: E402

P5 = ROOT / "evidence" / "decision_support" / "p5"
OUT = P5 / "p5a" / "isolation50"
EVAL_RUN = P5 / "p5a" / "P5a_eval" / "runs" / "ece90db4e6159a03bf84"
EVAL_RECORDS_SHA = "445cf7de829c0ab69fd7c92c84247b0191ee417291687507d95d587423c64347"


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def module_sha() -> str:
    return sha_bytes((ROOT / "src/hospitalos/p5/isolation50.py").read_bytes())


def load_records() -> dict:
    raw = (EVAL_RUN / "pilot_parents.jsonl").read_bytes()
    if sha_bytes(raw) != EVAL_RECORDS_SHA:
        raise SystemExit("refused: reserved records differ from ledger #54 hash")
    recs = [json.loads(x) for x in raw.decode().splitlines()]
    return {(r["structure_id"], int(r["parent_index"])): r for r in recs}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["select", "check", "summary"])
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--to", dest="stop", type=int, default=I.N_SELECT)
    args = ap.parse_args()
    try:
        commitment = integrity.verify(integrity.effective_commitment())
        env = running_environment()
        ledger = runner.base.read_ledger(runner.LEDGER)
        check_runtime(env, runner.approved_environments(ledger))
    except (integrity.IntegrityError, RuntimeRefused) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 3
    OUT.mkdir(parents=True, exist_ok=True)
    cid = commitment["commitment_id"]
    proc_path = OUT / "ISOLATION_PROCEDURE.json"
    if args.cmd == "select":
        if proc_path.exists():
            print("refused: procedure already written (never rewritten)", file=sys.stderr)
            return 2
        records = load_records()
        selection = I.select(sorted(records), cid)
        sel_text = json.dumps([[s, p] for s, p in selection])
        body = {"schema": "HOSPITALOS_P5_ISOLATION50_PROCEDURE_1", "qualification": "POST-FREEZE check (after F_a and after the P5a reading); does not raise the exploratory verdict",
                "procedure": inspect.getdoc(I), "module": "src/hospitalos/p5/isolation50.py", "module_sha256": module_sha(),
                "commitment": {"stage": commitment["stage"], "commitment_id": cid},
                "population": {"run": "P5a_eval/ece90db4e6159a03bf84", "records_sha256": EVAL_RECORDS_SHA, "parents": len(records)},
                "selection_rule": f"salt {I.SALT}; structure order sha256(salt|commitment|structure_id); parent order sha256(salt|commitment|structure_id|parent); round-robin to {I.N_SELECT}; ids only, no outcome read",
                "selection": [[s, p] for s, p in selection], "selection_sha256": sha_bytes(sel_text.encode()),
                "structures_covered": len({s for s, _ in selection}),
                "truth_A": list(I.TRUTH_A), "truth_B_order": [list(x) for x in I.TRUTH_B_ORDER]}
        proc_path.write_text(json.dumps(body, indent=1) + "\n")
        print(json.dumps({"selected": len(selection), "structures": body["structures_covered"], "selection_sha256": body["selection_sha256"]}))
        return 0
    proc = json.loads(proc_path.read_text())
    notes = [r for r in ledger if r.get("kind") == "isolation_procedure"]
    if not notes or notes[-1]["payload"] != proc or proc["module_sha256"] != module_sha():
        print("refused: procedure not recorded in the ledger, or module/procedure changed since", file=sys.stderr)
        return 4
    receipts_path = OUT / "ISOLATION_RECEIPTS.jsonl"
    failure_path = OUT / "ISOLATION_FAILURE.json"
    if args.cmd == "summary":
        recs = [json.loads(x) for x in receipts_path.read_text().splitlines()] if receipts_path.exists() else []
        body = {"episodes_checked": len(recs), "selected": len(proc["selection"]), "failure": failure_path.exists(),
                "all_passed": len(recs) == len(proc["selection"]) and not failure_path.exists(),
                "plans_checked_T03b": sum(r["T03b_plans_checked"] for r in recs),
                "T04a_detector_fired_on_plans": sum(r["T04a_detector_fired_on_plans"] for r in recs),
                "truth_B_used": sorted({tuple(r["truth_B"]) for r in recs}), "structures": len({r["structure_id"] for r in recs}),
                "qualification": proc["qualification"]}
        (OUT / "ISOLATION_SUMMARY.json").write_text(json.dumps(body, indent=1) + "\n")
        print(json.dumps(body))
        return 0 if body["all_passed"] else 6
    if failure_path.exists():
        print("refused: a failure was recorded; no further checks", file=sys.stderr)
        return 6
    records = load_records()
    selection = [tuple(x) for x in proc["selection"]][args.start:args.stop]
    done = set()
    if receipts_path.exists():
        done = {(r["structure_id"], r["parent_index"]) for r in map(json.loads, receipts_path.read_text().splitlines())}
    seeds = json.loads((P5 / "SEEDS_SEALED.json").read_text())["partitions"]["P5a_eval"]
    seed_of = {structure_id("P5a_eval", s): s for s in seeds}
    todo = [x for x in selection if x not in done]
    settings = Settings.default()
    try:
        episodes = I.reconstruct(todo, seed_of, records, load_profile())
        for key in todo:
            receipt = I.check_episode(episodes[key], records[key], settings, cid)
            with receipts_path.open("a") as fh:
                fh.write(json.dumps(receipt, sort_keys=True) + "\n")
    except I.IsolationFailure as failure:
        failure_path.write_text(json.dumps({"kind": failure.kind, "detail": failure.detail, "procedure_sha256": sha_bytes(proc_path.read_bytes())}, indent=1) + "\n")
        print(f"STOP: {failure}", file=sys.stderr)
        return 6
    print(json.dumps({"checked_now": len(todo), "total": len(done) + len(todo)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
