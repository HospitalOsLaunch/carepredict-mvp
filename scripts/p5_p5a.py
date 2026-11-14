#!/usr/bin/env python3
"""P5a under authorisation (ii). Every sub-command runs under the P5 counter (lot P5.3 or P5.5).

    run --partition P5a_dev --from 0 --to 10      development (10 structures x 10 parents)
    precision                                     projection from development (no gain is reported)
    freeze                                        writes F_a (recorded by a ledger note afterwards)
    run --partition P5a_eval --from 0 --to 10     reserved evaluation, refused without a valid F_a
    analyse                                       final analysis of the reserved run (R1 primary, R2 robustness)

Before any generation: effective commitment verified, in-process (Python, freeze) pair approved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import p5_budget_run as runner  # noqa: E402

from hospitalos.decision_support.planner import Settings  # noqa: E402
from hospitalos.decision_support.snapshot import CONFIG_DIR, load_json, load_profile  # noqa: E402
from hospitalos.p5 import integrity  # noqa: E402
from hospitalos.p5 import p5a as X  # noqa: E402
from hospitalos.p5 import p5a_analysis as A  # noqa: E402
from hospitalos.p5.pilot import (  # noqa: E402
    PilotStop,
    ResumeRefused,
    RuntimeRefused,
    check_runtime,
    run_identity,
    running_environment,
)

P5 = ROOT / "evidence" / "decision_support" / "p5"
OUT = P5 / "p5a"
N_PARENTS, K_EVAL, REGIMES = 10, 3, ("R1", "R2")
SIZES = {"P5a_dev": 10, "P5a_eval": 30}


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def guarded() -> tuple[dict, dict, list]:
    commitment = integrity.verify(integrity.effective_commitment())
    env = running_environment()
    records = runner.base.read_ledger(runner.LEDGER)
    check_runtime(env, runner.approved_environments(records))
    return commitment, env, records


def identity_for(partition: str, commitment: dict, env: dict) -> dict:
    seeds = json.loads((P5 / "SEEDS_SEALED.json").read_text())["partitions"][partition]
    code = hashlib.sha256((ROOT / "src/hospitalos/p5/p5a.py").read_bytes() + (ROOT / "scripts/p5_p5a.py").read_bytes()).hexdigest()
    return run_identity(commitment, partition, seeds, N_PARENTS, K_EVAL, REGIMES, env, code), seeds


def run_dir(identity: dict) -> Path:
    return OUT / identity["partition"] / "runs" / identity["run_id"]


def load_run(path: Path) -> tuple[list, list]:
    recs = [json.loads(x) for x in (path / "pilot_parents.jsonl").read_text().splitlines()]
    meta = [json.loads(x) for x in (path / "structures.jsonl").read_text().splitlines()]
    return recs, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "precision", "freeze", "analyse"])
    ap.add_argument("--partition", choices=list(SIZES), default="P5a_dev")
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--to", dest="stop", type=int, default=None)
    args = ap.parse_args()
    try:
        commitment, env, ledger = guarded()
    except (integrity.IntegrityError, RuntimeRefused) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 3
    if args.cmd == "run":
        if args.partition == "P5a_eval":
            try:
                X.require_freeze(ledger, {f: sha(f) for f in X.F_A_FILES})
            except X.FreezeMissing as error:
                print(f"refused: {error}", file=sys.stderr)
                return 4
        identity, seeds = identity_for(args.partition, commitment, env)
        stop = args.stop if args.stop is not None else SIZES[args.partition]
        try:
            out = X.run_segment(out_dir=OUT / args.partition, identity=identity, seeds=seeds,
                                indices=range(args.start, min(stop, SIZES[args.partition])),
                                profile=load_profile(), settings=Settings.default(),
                                score=load_json(CONFIG_DIR / "PRESSURE_SCORE_CONFIG.json"))
        except (PilotStop, ResumeRefused) as error:
            print(f"STOP: {error}", file=sys.stderr)
            return 6
        print(json.dumps(out))
        return 0
    seeds_file = json.loads((P5 / "SEEDS_SEALED.json").read_text())
    if args.cmd == "precision":
        identity, _ = identity_for("P5a_dev", commitment, env)
        recs, meta = load_run(run_dir(identity))
        if len(recs) != SIZES["P5a_dev"] * N_PARENTS:
            print(f"refused: development incomplete ({len(recs)} parents)", file=sys.stderr)
            return 5
        _, structs = A.group(recs, "R1")
        proj = A.precision_projection(structs, SIZES["P5a_eval"])
        # smoke run of the frozen analysis code path on development data (results discarded, not read)
        for reg in REGIMES:
            A.analyse(recs, meta, reg, 0, 50, True, primary=(reg == "R1"))
        cand = sum(m["candidates"] for m in meta)
        excl = sum(sum(m["exclusions"].values()) for m in meta)
        body = {"partition": "P5a_dev", "run_id": identity["run_id"], "parents": len(recs), "projection": proj,
                "dev_exclusions": {"candidates": cand, "excluded": excl},
                "dev_abstentions": sum(r["abstention_as_habitual"] for r in recs),
                "analysis_code_smoke_on_dev": "ok (outputs discarded, not read)",
                "note": "development: only the precision projection and sanity counts are read; no gain is reported"}
        (OUT / "PRECISION_DEV.json").write_text(json.dumps(body, indent=1) + "\n")
        print(json.dumps(body["projection"]))
        return 0
    if args.cmd == "freeze":
        prec = json.loads((OUT / "PRECISION_DEV.json").read_text())
        body = {"stage": "F_a", "effective_commitment": {"stage": commitment["stage"], "ledger_record": commitment["ledger_record_sha256"]},
                "files_sha256": {f: sha(f) for f in X.F_A_FILES},
                "delta": A.DELTA, "tolerance": A.TOLERANCE, "harm_max": A.HARM_MAX, "exclusion_max": A.EXCLUSION_MAX,
                "half_width_max": A.HALF_WIDTH_MAX, "bootstrap_resamples": 2000,
                "bootstrap_seed_sha256_committed_E0": json.loads((P5 / "COMMITMENT_E0.json").read_text())["seeds"]["bootstrap_seed_sha256"],
                "precision_projection": prec["projection"], "declared_reading": prec["projection"]["declared_reading"],
                "dev_run_id": prec["run_id"], "reserved": {"partition": "P5a_eval", "structures": 30, "parents": 10,
                "regimes": list(REGIMES), "K_eval": K_EVAL}, "P5b_frozen": False}
        (OUT / "F_a.json").write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
        print(json.dumps({"declared_reading": body["declared_reading"], "files": len(body["files_sha256"])}))
        return 0
    # analyse (reserved run)
    try:
        freeze = X.require_freeze(ledger, {f: sha(f) for f in X.F_A_FILES})
    except X.FreezeMissing as error:
        print(f"refused: {error}", file=sys.stderr)
        return 4
    identity, _ = identity_for("P5a_eval", commitment, env)
    recs, meta = load_run(run_dir(identity))
    if len(recs) != SIZES["P5a_eval"] * N_PARENTS:
        print(f"refused: reserved run incomplete ({len(recs)} parents)", file=sys.stderr)
        return 5
    seed = int(seeds_file["bootstrap_seed"])
    salt = seeds_file["salt"]
    if hashlib.sha256((str(seed) + salt).encode()).hexdigest() != freeze["bootstrap_seed_sha256_committed_E0"]:
        print("refused: bootstrap seed does not match its E0 commitment", file=sys.stderr)
        return 7
    precise = freeze["precision_projection"]["precision_sufficient"]
    res = {"partition": "P5a_eval", "run_id": identity["run_id"], "F_a_declared_reading": freeze["declared_reading"],
           "R1": A.analyse(recs, meta, "R1", seed, 2000, precise, primary=True),
           "R2": A.analyse(recs, meta, "R2", seed, 2000, precise, primary=False)}
    res["class_minima_mean_over_parents_descriptive"] = {reg: {c: (sum(v for v in vals if v is not None) / len([v for v in vals if v is not None])
                                          if any(v is not None for v in vals) else None)
                                      for c, vals in zip(("C", "R", "CR"), zip(*[[A.class_minima(r, reg)[c] for c in ("C", "R", "CR")] for r in recs]), strict=True)}
                                for reg in REGIMES}
    (OUT / "RESULTS_P5a.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    print(json.dumps({reg: {"verdict": res[reg]["verdict"], "gain": res[reg]["point"]["gain"], "ci95": res[reg]["ci95"]["gain"]} for reg in REGIMES}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
