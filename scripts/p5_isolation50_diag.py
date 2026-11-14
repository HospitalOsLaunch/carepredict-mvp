#!/usr/bin/env python3
"""Diagnosis of the recorded isolation50 failure (read-only; modifies no result, checks nothing new).

Reconstructs the failing episode from the sealed seeds, realises the 6 private truths of the
procedure, and reports which primitives differ and why the HABITUAL-1 truth-runs coincide.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import p5_budget_run as runner  # noqa: E402

from hospitalos.decision_support.planner import Settings, _config  # noqa: E402
from hospitalos.decision_support.reference_forecaster import PrivateOracle  # noqa: E402
from hospitalos.decision_support.snapshot import load_profile  # noqa: E402
from hospitalos.p5 import integrity  # noqa: E402
from hospitalos.p5 import isolation50 as I  # noqa: E402
from hospitalos.p5 import truth as T  # noqa: E402
from hospitalos.p5.pilot import check_runtime, running_environment, structure_id  # noqa: E402

P5 = ROOT / "evidence" / "decision_support" / "p5"
OUT = P5 / "p5a" / "isolation50"


def main() -> int:
    commitment = integrity.verify(integrity.effective_commitment())
    check_runtime(running_environment(), runner.approved_environments(runner.base.read_ledger(runner.LEDGER)))
    fail = json.loads((OUT / "ISOLATION_FAILURE.json").read_text())
    sid, p = fail["detail"]["structure_id"], int(fail["detail"]["parent_index"])
    run = P5 / "p5a" / "P5a_eval" / "runs" / "ece90db4e6159a03bf84" / "pilot_parents.jsonl"
    rec = next(r for r in map(json.loads, run.read_text().splitlines()) if r["structure_id"] == sid and r["parent_index"] == p)
    seeds = json.loads((P5 / "SEEDS_SEALED.json").read_text())["partitions"]["P5a_eval"]
    seed_of = {structure_id("P5a_eval", s): s for s in seeds}
    ep = I.reconstruct([(sid, p)], seed_of, {(sid, p): rec}, load_profile())[(sid, p)]
    cfg = _config(Settings.default(), ep.snapshot.as_of, 24)
    cid = commitment["commitment_id"]
    keys = [I.TRUTH_A, *I.TRUTH_B_ORDER]
    truths, runs = {}, {}
    for regime, k in keys:
        real = T.realise(ep, regime, k, cid)
        truths[f"{regime}k{k}"] = {"values": {m: dict(v) for m, v in real.truth.values.items()}, "presence": dict(real.presence)}
        r = PrivateOracle(real.truth).outcome(ep.snapshot, ep.plans[0], cfg)
        runs[f"{regime}k{k}"] = {"departures": r.departures, "admissions": r.admissions,
                                 "uncovered_total": sum(r.uncovered_unit) + sum(r.uncovered_waiting)}
    a = truths["R1k1"]["values"]
    differing = {name: sorted({f"{m}:{e}" for m in a for e in set(a[m]) | set(t["values"].get(m, {}))
                               if a[m].get(e) != t["values"].get(m, {}).get(e)})
                 for name, t in truths.items() if name != "R1k1"}
    snap = ep.snapshot
    body = {
        "failure": fail,
        "episode": {"structure_id": sid, "parent_index": p, "n_plans": len(ep.plans),
                    "universe_matches_record": True,
                    "stays": [{"stay_id": s.stay_id, "authorization": s.medical_authorization, "obstacles": list(s.obstacles),
                               "transport_need": s.transport_need} for s in snap.stays],
                    "beds": [{"bed_id": b.bed_id, "status": b.status} for b in snap.beds],
                    "admissions": [a_.request_id for a_ in snap.admissions]},
        "primitives_differing_from_truth_A": differing,
        "habitual_truth_runs": runs,
        "recorded_U_habitual": {reg: [row[0] for row in rec["outcomes"][reg]["U"]] for reg in ("R1", "R2")},
        "note": "read-only diagnosis; no check re-run; F_a and RESULTS unchanged",
    }
    (OUT / "ISOLATION_FAILURE_DIAGNOSIS.json").write_text(json.dumps(body, indent=1, sort_keys=True, default=str) + "\n")
    print(json.dumps({"differing": differing, "habitual_runs": runs, "recorded_U_habitual": body["recorded_U_habitual"]}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
