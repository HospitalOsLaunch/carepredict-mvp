#!/usr/bin/env python3
"""P5A-D02 RESUME (adopted): method v2 on selection indices 47-49 only (lot P5.3).

    seal       write the resume procedure (new identity), before any check
    check      run v2 on the 3 resumed episodes; refused cleanly (code 4 + receipt) if the
               procedure is missing, unrecorded or changed - before any reconstruction or test
    summary    47 (method v1, historical) + 3 (method v2) without silent mixing

The historical directory (procedure, 47 receipts, ISOLATION_FAILURE.json) is read, never written.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import p5_budget_run as runner  # noqa: E402

from hospitalos.decision_support.planner import Settings  # noqa: E402
from hospitalos.decision_support.snapshot import load_profile  # noqa: E402
from hospitalos.p5 import integrity  # noqa: E402
from hospitalos.p5 import isolation50 as I1  # noqa: E402
from hospitalos.p5 import isolation50_v2 as I2  # noqa: E402
from hospitalos.p5.pilot import RuntimeRefused, check_runtime, running_environment, structure_id  # noqa: E402

P5 = ROOT / "evidence" / "decision_support" / "p5"
OLD = P5 / "p5a" / "isolation50"
OUT = P5 / "p5a" / "isolation50_resume"
EVAL_RUN = P5 / "p5a" / "P5a_eval" / "runs" / "ece90db4e6159a03bf84"
EVAL_RECORDS_SHA = "445cf7de829c0ab69fd7c92c84247b0191ee417291687507d95d587423c64347"
OLD_SELECTION_SHA = "d4522515dc9b3e1565b1a33bdf893590318651f139193b930fd85a3a269be993"
KIND = "isolation_resume_procedure"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def module_sha() -> str:
    return sha((ROOT / "src/hospitalos/p5/isolation50_v2.py").read_bytes())


def refuse(reason: str) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "REFUSALS.jsonl").open("a") as fh:
        fh.write(json.dumps({"at_utc": datetime.now(UTC).isoformat(), "reason": reason}) + "\n")
    print(f"refused: {reason}", file=sys.stderr)
    return 4


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["seal", "check", "summary"])
    args = ap.parse_args()
    try:
        commitment = integrity.verify(integrity.effective_commitment())
        env = running_environment()
        ledger = runner.base.read_ledger(runner.LEDGER)
        check_runtime(env, runner.approved_environments(ledger))
    except (integrity.IntegrityError, RuntimeRefused) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 3
    cid = commitment["commitment_id"]
    old_proc = json.loads((OLD / "ISOLATION_PROCEDURE.json").read_text())
    if old_proc["selection_sha256"] != OLD_SELECTION_SHA:
        return refuse("historical_selection_changed")
    proc_path = OUT / "RESUME_PROCEDURE.json"
    if args.cmd == "seal":
        if proc_path.exists():
            return refuse("resume_procedure_already_sealed")
        OUT.mkdir(parents=True, exist_ok=True)
        episodes = [old_proc["selection"][i] for i in I2.RESUME_INDICES]
        body = {"schema": "HOSPITALOS_P5_ISOLATION50_RESUME_1", "method": I2.METHOD,
                "qualification": "POST-FREEZE resume; method v2 differs from the 47 historical v1 receipts (v1 conditioned the pair on HABITUAL-1); does not raise the exploratory verdict",
                "procedure": inspect.getdoc(I2), "module": "src/hospitalos/p5/isolation50_v2.py", "module_sha256": module_sha(),
                "script_sha256": sha((ROOT / "scripts/p5_isolation50_resume.py").read_bytes()),
                "commitment": {"stage": commitment["stage"], "commitment_id": cid},
                "historical": {"procedure_sha256": sha((OLD / "ISOLATION_PROCEDURE.json").read_bytes()), "selection_sha256": OLD_SELECTION_SHA,
                               "receipts_sha256": sha((OLD / "ISOLATION_RECEIPTS.jsonl").read_bytes()),
                               "failure_sha256": sha((OLD / "ISOLATION_FAILURE.json").read_bytes())},
                "resume_indices": list(I2.RESUME_INDICES), "episodes": episodes,
                "population": {"records_sha256": EVAL_RECORDS_SHA}}
        proc_path.write_text(json.dumps(body, indent=1) + "\n")
        print(json.dumps({"sealed": episodes, "module_sha256": body["module_sha256"]}))
        return 0
    ok, reason = I2.require_recorded_procedure(proc_path, ledger, KIND, module_sha())
    if not ok:
        return refuse(reason)
    proc = json.loads(proc_path.read_text())
    receipts = OUT / "RESUME_RECEIPTS.jsonl"
    failure = OUT / "RESUME_FAILURE.json"
    if args.cmd == "summary":
        old = [json.loads(x) for x in (OLD / "ISOLATION_RECEIPTS.jsonl").read_text().splitlines()]
        new = [json.loads(x) for x in receipts.read_text().splitlines()] if receipts.exists() else []
        body = {
            "selection": 50, "selection_sha256": OLD_SELECTION_SHA,
            "method_v1_historical": {"episodes_with_receipt": len(old), "T03_passed": len(old),
                                     "T04a_detected": len(old), "T04bcd_passed": len(old),
                                     "note": "pair chosen on HABITUAL-1; T03-b against one B; stop at index 47 (precondition)"},
            "method_v2_resume": {"episodes_with_receipt": len(new),
                                 "T03_passed": sum(r["T03a"] == "pass" and r["T03b"] == "pass" for r in new),
                                 "T04a_detected": sum(r["T04a"] == "DETECTED" for r in new),
                                 "T04a_non_informatif": sum(r["T04a"] == "NON_INFORMATIF" for r in new),
                                 "T04bcd_passed": sum(r["T04b"] == r["T04c"] == r["T04d"] == "pass" for r in new),
                                 "identical_truths_flags": {f"{r['structure_id']}/{r['parent_index']}": r["identical_truths"] for r in new}},
            "coverage": len(old) + len(new), "true_failures": 1 if failure.exists() else 0,
            "historical_stop_kept": json.loads((OLD / "ISOLATION_FAILURE.json").read_text()),
            "closure_criterion_P5A_D02": "unchanged; any acceptance of NON_INFORMATIF T04-a episodes requires an explicit decision",
        }
        body["all_50_covered_without_true_failure"] = body["coverage"] == 50 and not failure.exists()
        (OUT / "RESUME_SUMMARY.json").write_text(json.dumps(body, indent=1) + "\n")
        print(json.dumps({k: body[k] for k in ("coverage", "true_failures", "all_50_covered_without_true_failure")} | {"v2": body["method_v2_resume"]}))
        return 0
    if failure.exists():
        return refuse("resume_failure_recorded")
    raw = (EVAL_RUN / "pilot_parents.jsonl").read_bytes()
    if sha(raw) != EVAL_RECORDS_SHA:
        return refuse("reserved_records_changed")
    records = {(r["structure_id"], int(r["parent_index"])): r for r in map(json.loads, raw.decode().splitlines())}
    done = set()
    if receipts.exists():
        done = {(r["structure_id"], r["parent_index"]) for r in map(json.loads, receipts.read_text().splitlines())}
    todo = [tuple(x) for x in proc["episodes"] if tuple(x) not in done]
    seeds = json.loads((P5 / "SEEDS_SEALED.json").read_text())["partitions"]["P5a_eval"]
    seed_of = {structure_id("P5a_eval", s): s for s in seeds}
    settings = Settings.default()
    try:
        episodes = I1.reconstruct(todo, seed_of, records, load_profile())
        for key in todo:
            receipt = I2.check_episode_v2(episodes[key], records[key], settings, cid)
            with receipts.open("a") as fh:
                fh.write(json.dumps(receipt, sort_keys=True) + "\n")
    except I1.IsolationFailure as fail:
        failure.write_text(json.dumps({"kind": fail.kind, "detail": fail.detail, "method": I2.METHOD}, indent=1) + "\n")
        print(f"STOP: {fail}", file=sys.stderr)
        return 6
    print(json.dumps({"checked_now": len(todo)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
