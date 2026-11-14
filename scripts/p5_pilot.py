#!/usr/bin/env python3
"""P5.2 — timed pilot on 20 DEVELOPMENT parents (P5-PROTO-2 § 10). Timing is the deliverable.

Partition P5a_dev, first 2 committed structures x 10 parents, R1+R2, K=3, all plans of the
public universe under the private truth, v6 recommendation, M_agg/M_ent extraction for every
(parent, plan), twin construction timing, one full 2000-resample hierarchical bootstrap.
Fits are NOT timed: scikit-learn is not installed (D4 not authorised). Per-parent records are
appended as they are produced (resumable; a parent already recorded is skipped).

Development data are never read as a result (protocol § 2); values are kept only as
diagnostics (guardrails, exclusions, variance inputs for later precision projection).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hospitalos.decision_support.planner import Settings, recommend  # noqa: E402
from hospitalos.decision_support.snapshot import load_profile  # noqa: E402
from hospitalos.p5 import truth as T  # noqa: E402
from hospitalos.p5.analysis import hierarchical_bootstrap, structure_weighted_mean  # noqa: E402
from hospitalos.p5.eval_adapter import outcome  # noqa: E402
from hospitalos.p5.features import SnapshotFeatures  # noqa: E402
from hospitalos.p5.generator import generate_structure, make_twin, realise_episode  # noqa: E402

P5 = ROOT / "evidence" / "decision_support" / "p5"
OUT = P5 / "pilot"
RECORDS = OUT / "pilot_parents.jsonl"
N_STRUCTURES, N_PARENTS, K = 2, 10, 3


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    seeds = json.loads((P5 / "SEEDS_SEALED.json").read_text())["partitions"]["P5a_dev"][:N_STRUCTURES]
    commitment = json.loads((P5 / "COMMITMENT_E0.json").read_text())["seeds"]["commitment_id"]
    profile = load_profile()
    settings = Settings.default()
    done = set()
    if RECORDS.exists():
        done = {(r["structure"], r["parent_index"]) for r in map(json.loads, RECORDS.read_text().splitlines())}
    for s_idx, seed in enumerate(seeds):
        t0 = time.perf_counter()
        valid, every = generate_structure("P5a_dev", seed, N_PARENTS, profile, twins=False)
        gen_s = time.perf_counter() - t0
        exclusions = {}
        for c in every:
            if c.excluded:
                exclusions[c.excluded] = exclusions.get(c.excluded, 0) + 1
        for cand in valid:
            if (s_idx, cand.parent_index) in done:
                continue
            ep = cand.episodes["A"]
            rec: dict[str, object] = {"structure": s_idx, "parent_index": cand.parent_index,
                                      "n_plans": len(ep.plans), "structure_candidates": len(every),
                                      "structure_exclusions": exclusions,
                                      "generation_s_per_parent": gen_s / len(every)}
            t = time.perf_counter()
            reco = recommend(ep.snapshot, settings)
            rec["recommend_s"] = time.perf_counter() - t
            rec["recommend_status"] = reco.status
            ids = [p.plan_id for p in ep.plans]
            chosen = reco.primary_plan_id if reco.status in {"RECOMMENDATION_READY", "NO_ACTION_PREFERRED"} else ids[0]
            rec["chosen_in_universe"] = chosen in ids
            rec["abstention_as_habitual"] = reco.status not in {"RECOMMENDATION_READY", "NO_ACTION_PREFERRED"}
            universe_fp = ep.universe_fingerprint
            U: dict[str, list[list[int]]] = {}
            violations = 0
            sims = 0
            t = time.perf_counter()
            for regime in T.REGIMES:
                U[regime] = []
                for k in range(1, K + 1):
                    real = T.realise(ep, regime, k, commitment)
                    row = []
                    for plan in ep.plans:
                        out = outcome(ep.snapshot, plan, real, profile)
                        violations += bool(out.violations)
                        row.append(out.U)
                        sims += 1
                    U[regime].append(row)
            rec["truth_sim_s"] = time.perf_counter() - t
            rec["truth_sims"] = sims
            rec["violations"] = violations
            rec["universe_invariant"] = ep.universe_fingerprint == universe_fp
            rec["U_dev_only"] = U
            rec["chosen_index"] = ids.index(chosen) if chosen in ids else 0
            t = time.perf_counter()
            feats = SnapshotFeatures(ep.snapshot, ep.sidecar, profile)
            n_rows = 0
            for plan in ep.plans:
                for fam in ("M_agg", "M_ent"):
                    feats.row(plan, fam)
                    n_rows += 1
            rec["extraction_s"] = time.perf_counter() - t
            rec["extraction_rows"] = n_rows
            t = time.perf_counter()
            twin = make_twin(ep.spec)
            if twin is not None:
                realise_episode(twin, profile)
            rec["twin_s"] = time.perf_counter() - t
            rec["twin_degenerate"] = twin is None
            with RECORDS.open("a") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
    # one full bootstrap (2000 resamples) on the pilot development records — timing only
    records = [json.loads(x) for x in RECORDS.read_text().splitlines()]
    by_s: dict[int, list[dict[str, float]]] = {}
    for r in records:
        u = r["U_dev_only"]["R1"]
        hab = sum(row[0] for row in u) / len(u)
        plan = sum(row[r["chosen_index"]] for row in u) / len(u)
        by_s.setdefault(r["structure"], []).append({"gain": hab - plan})
    structures = list(by_s.values())
    t = time.perf_counter()
    hierarchical_bootstrap(structures, lambda d: structure_weighted_mean(d, "gain"), 2000, 12345)
    boot_s = time.perf_counter() - t
    summary = {
        "parents": len(records),
        "bootstrap_2000_s": boot_s,
        "bootstrap_parents": sum(len(s) for s in structures),
        "note": "development data; timing deliverable; values are not results",
    }
    (OUT / "pilot_bootstrap.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
