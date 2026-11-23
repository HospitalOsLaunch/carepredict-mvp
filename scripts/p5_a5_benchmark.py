#!/usr/bin/env python3
"""A5 timing benchmark for ONE family (D15). Run under the P5 counter, lot P5.2:

    python3 scripts/p5_budget_run.py --lot P5.2 --label "A5 M_agg" -- \
        env OMP_NUM_THREADS=1 <venv311>/bin/python -I scripts/p5_a5_benchmark.py --family M_agg

Before any fit: effective commitment verified (sources, sealed seeds, v6 engine); in-process
(Python, freeze) pair must be approved; OMP_NUM_THREADS must be 1; the family must not have been
measured already. Results are written after each fit (evidence/decision_support/p5/a5/).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

T0 = time.perf_counter()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import p5_budget_run as runner  # noqa: E402

from hospitalos.decision_support.snapshot import load_profile  # noqa: E402
from hospitalos.p5 import a5, integrity  # noqa: E402
from hospitalos.p5.pilot import RuntimeRefused, check_runtime, running_environment  # noqa: E402

P5 = ROOT / "evidence" / "decision_support" / "p5"
OUT = P5 / "a5"
SAFETY_S = 1.5  # kept free for interpreter exit and result writing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", required=True, choices=a5.FAMILIES)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"A5_{args.family}.json"
    try:
        a5.output_guard(out_path)
        a5.check_threads()
        commitment = integrity.verify(integrity.effective_commitment())
        env = running_environment()
        records = runner.base.read_ledger(runner.LEDGER)
        check_runtime(env, runner.approved_environments(records))
    except (a5.A5Error, integrity.IntegrityError, RuntimeRefused) as error:
        print(f"refused before any fit: {error}", file=sys.stderr)
        return 3
    status = runner.status()
    lot_remaining = float(status["lots"]["P5.2"]["cap"]) - float(status["lots"]["P5.2"]["used"])
    command_cap = min(runner.PER_COMMAND_S, lot_remaining)

    t = time.perf_counter()
    seeds = json.loads((P5 / "SEEDS_SEALED.json").read_text())["partitions"]["P5a_dev"][:2]
    pilot = [json.loads(x) for x in (P5 / "pilot" / "pilot_parents.jsonl").read_text().splitlines()]
    data = a5.development_rows(pilot, seeds, load_profile())
    X, y = a5.tile(data[args.family], data["y"])
    prep_s = time.perf_counter() - t

    import sklearn  # noqa: E402
    import threadpoolctl  # noqa: E402
    from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402

    body = {
        "schema": "HOSPITALOS_P5_A5_1",
        "family": args.family,
        "authorisation": "D15 (adopted 2026-11-14)",
        "commitment": {"stage": commitment["stage"], "ledger_record_sha256": commitment["ledger_record_sha256"]},
        "environment": {**env, "sklearn": sklearn.__version__,
                        "threadpools": [{k: p.get(k) for k in ("user_api", "internal_api", "num_threads", "version")}
                                        for p in threadpoolctl.threadpool_info()]},
        "matrix": {
            "source": "historical E0 pilot parents (P5a_dev structures 0-1), public snapshots regenerated, labels = recorded R1 mean U",
            "parents": data["parents"],
            "distinct_rows": int(len(data["y"])),
            "tiled_rows": int(len(y)),
            "features": int(X.shape[1]),
            "distinct_sha256": a5.fingerprint(data[args.family], data["y"]),
            "tiled_sha256": a5.fingerprint(X, y),
            "feature_names_sha256": hashlib.sha256("|".join(data[f"{args.family}_names"]).encode()).hexdigest(),
            "limitation": "tiled repeated rows; not the cost of a diverse corpus",
        },
        "params": {k: (v if v is not None else None) for k, v in a5.hgb_params(0).items() if k != "random_state"},
        "seeds": list(a5.SEEDS),
        "preparation_s": prep_s,
        "budget": {"lot_remaining_at_start_s": lot_remaining, "command_cap_s": command_cap, "safety_s": SAFETY_S},
        "results": [],
        "status": "RUNNING",
    }
    a5.write_json(out_path, body)

    def progress(row: dict) -> None:
        body["results"].append(row)
        a5.write_json(out_path, body)

    budget_s = command_cap - SAFETY_S - (time.perf_counter() - T0)
    summary = a5.run_family(args.family, X, y, lambda p: HistGradientBoostingRegressor(**p), budget_s, progress)
    body.update({k: summary[k] for k in ("complete", "seed_identity_within_tolerance", "tolerance", "stop")})
    body["fit_budget_s"] = budget_s
    body["status"] = "COMPLETE" if summary["complete"] else "STOPPED_BUDGET_RULE"
    body["models"] = "discarded"
    a5.write_json(out_path, body)
    print(json.dumps({k: body[k] for k in ("family", "status", "seed_identity_within_tolerance")} | {"results": body["results"]}))
    return 0 if summary["complete"] else 7


if __name__ == "__main__":
    raise SystemExit(main())
