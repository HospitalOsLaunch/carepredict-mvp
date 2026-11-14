"""P5a executor (authorisation (ii); P5-PROTO-2 §§ 2-5 as amended by P5-PROTO-3 / 3.1).

For each parent episode of a partition: the v6 public planner recommends (no private input);
every plan of the complete public universe (<= 16, HABITUAL-1 included) is evaluated under the
private truth for each regime (R1, R2) and replicate k = 1..K_eval (=3), with keyed shared
innovations, through the evaluation adapter. Everything needed by the analysis is recorded per
(structure, parent, regime, replicate, plan): U, planned/realised reinforcement hours, lent
hours, waiting patient-hours, beds returned, PS-EXP-1 peak and hours above threshold.

Stop rules (receipt, never a silent abstention): habitual-practice invariant failure, any
violation under truth, universe changed across realisations, recommended plan outside the
universe. Genuine abstentions are evaluated as HABITUAL-1 and counted. Runs are segmented by
structure ranges (< 30 s per command), resumable only under the same run identity.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from hospitalos.decision_support.planner import recommend as v6_recommend

from . import truth as T
from .eval_adapter import outcome as v6_outcome
from .generator import generate_structure
from .pilot import SELECTED, PilotStop, ResumeRefused, _stop, open_run, structure_id

PLAN_CLASSES = ("H", "C", "R", "CR")


def plan_descriptor(plan: Any, start: Any) -> dict[str, Any]:
    coord = sorted(a.action_id for a in plan.actions if a.type == "coordinate_discharge")
    reinf = sorted(a.action_id for a in plan.actions if a.type == "reinforcement")
    cls = "H" if not plan.actions else ("CR" if coord and reinf else ("C" if coord else "R"))
    return {
        "plan_id": plan.plan_id,
        "coord": coord,
        "reinf": reinf,
        "class": cls,
        "planned_hours": plan.reinforcement_hours,
        "interventions": plan.interventions,
    }


def evaluate_parent(
    ep: Any,
    *,
    run_dir: Path,
    identity: Mapping[str, Any],
    where: Mapping[str, Any],
    profile: Mapping[str, Any],
    settings: Any,
    score: Mapping[str, Any] | None,
    recommend_fn: Callable[..., Any] = v6_recommend,
    outcome_fn: Callable[..., Any] = v6_outcome,
) -> dict[str, Any]:
    k, regimes = int(identity["K"]), tuple(identity["regimes"])
    t = time.perf_counter()
    reco = recommend_fn(ep.snapshot, settings)
    rec_s = time.perf_counter() - t
    ids = [p.plan_id for p in ep.plans]
    reasons = tuple(getattr(reco, "reasons", ()))
    if reco.status == "INFEASIBLE" and "habitual_practice_invariant_failure" in reasons:
        _stop(run_dir, identity, "habitual_practice_invariant_failure", where)
    if reco.status in SELECTED:
        if reco.primary_plan_id not in ids:
            _stop(run_dir, identity, "recommended_plan_outside_public_universe",
                  {**where, "primary_plan_id": reco.primary_plan_id})
        chosen, abstention = ids.index(reco.primary_plan_id), False
    else:
        chosen, abstention = 0, True
    universe_fp = ep.universe_fingerprint
    fields = ("U", "realised_hours", "lent_hours", "waiting", "beds", "peak", "above")
    out: dict[str, dict[str, list[list[Any]]]] = {}
    t = time.perf_counter()
    sims = 0
    for regime in regimes:
        out[regime] = {f: [] for f in fields}
        for rep in range(1, k + 1):
            real = T.realise(ep, regime, rep, str(identity["commitment_id"]))
            rows: dict[str, list[Any]] = {f: [] for f in fields}
            for i, plan in enumerate(ep.plans):
                o = outcome_fn(ep.snapshot, plan, real, profile, score)
                if o.violations:
                    _stop(run_dir, identity, "invariant_or_admissibility_violation",
                          {**where, "plan_index": i, "regime": regime, "replicate": rep,
                           "violations": list(o.violations)})
                rows["U"].append(o.U)
                rows["realised_hours"].append(o.realised_reinforcement_hours)
                rows["lent_hours"].append(o.lent_hours_realised)
                rows["waiting"].append(o.waiting_patient_hours)
                rows["beds"].append(o.beds_returned)
                rows["peak"].append(o.peak_pressure)
                rows["above"].append(o.hours_above_threshold)
                sims += 1
            for f in fields:
                out[regime][f].append(rows[f])
            if ep.universe_fingerprint != universe_fp:
                _stop(run_dir, identity, "universe_changed_across_realisations", where)
    return {
        "run_id": identity["run_id"],
        **where,
        "n_plans": len(ep.plans),
        "universe_fingerprint": universe_fp,
        "plans": [plan_descriptor(p, ep.snapshot.as_of) for p in ep.plans],
        "recommend_status": reco.status,
        "chosen_index": chosen,
        "abstention_as_habitual": abstention,
        "outcomes": out,
        "truth_sims": sims,
        "recommend_s": rec_s,
        "truth_s": time.perf_counter() - t,
    }


def run_segment(
    *,
    out_dir: Path,
    identity: Mapping[str, Any],
    seeds: Sequence[int],
    indices: Sequence[int],
    profile: Mapping[str, Any],
    settings: Any,
    score: Mapping[str, Any] | None,
    recommend_fn: Callable[..., Any] = v6_recommend,
    outcome_fn: Callable[..., Any] = v6_outcome,
) -> dict[str, Any]:
    """Evaluate the structures ``indices`` of the identity's partition; resumable."""
    run_dir, done = open_run(out_dir, identity)
    partition, n_parents = identity["partition"], int(identity["n_parents"])
    records = run_dir / "pilot_parents.jsonl"
    structures = run_dir / "structures.jsonl"
    seen_structures = set()
    if structures.exists():
        seen_structures = {json.loads(x)["structure_id"] for x in structures.read_text().splitlines()}
    new = 0
    for idx in indices:
        seed = seeds[idx]
        sid = structure_id(partition, seed)
        valid, every = generate_structure(partition, seed, n_parents, profile, twins=False)
        if sid not in seen_structures:
            exclusions: dict[str, int] = {}
            for c in every:
                if c.excluded:
                    exclusions[c.excluded] = exclusions.get(c.excluded, 0) + 1
            with structures.open("a") as fh:
                fh.write(json.dumps({"run_id": identity["run_id"], "structure_id": sid, "structure_index": idx,
                                     "candidates": len(every), "valid": len(valid), "exclusions": exclusions},
                                    sort_keys=True) + "\n")
            seen_structures.add(sid)
        for cand in valid:
            if (sid, cand.parent_index) in done:
                continue
            where = {"structure_id": sid, "structure_index": idx, "parent_index": cand.parent_index}
            rec = evaluate_parent(cand.episodes["A"], run_dir=run_dir, identity=identity, where=where,
                                  profile=profile, settings=settings, score=score,
                                  recommend_fn=recommend_fn, outcome_fn=outcome_fn)
            with records.open("a") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
            done.add((sid, cand.parent_index))
            new += 1
    return {"run_id": identity["run_id"], "new_parents": new, "total_parents": len(done)}


__all__ = ["PilotStop", "ResumeRefused", "PLAN_CLASSES", "evaluate_parent", "plan_descriptor", "run_segment"]


class FreezeMissing(RuntimeError):
    """No valid F_a: reserved P5a generation is refused."""


F_A_FILES = (
    "docs/decision_support/P5_PROTOCOL_v2.md",
    "docs/decision_support/P5_PROTOCOL_PARAMS_v2.json",
    "docs/decision_support/P5_PROTOCOL_v3.md",
    "docs/decision_support/P5_PROTOCOL_PARAMS_v3.json",
    "docs/decision_support/P5_PROTOCOL_v3_1.md",
    "docs/decision_support/P5_PROTOCOL_PARAMS_v3_1.json",
    "src/hospitalos/p5/generator.py",
    "src/hospitalos/p5/truth.py",
    "src/hospitalos/p5/eval_adapter.py",
    "src/hospitalos/p5/analysis.py",
    "src/hospitalos/p5/p5a.py",
    "src/hospitalos/p5/p5a_analysis.py",
    "src/hospitalos/p5/pilot.py",
    "scripts/p5_p5a.py",
    "configs/decision_support/UNIT_PROFILE.json",
    "configs/decision_support/OBJECTIVE_CONFIG.json",
    "configs/decision_support/PRESSURE_SCORE_CONFIG.json",
)


def require_freeze(records: Sequence[Mapping[str, Any]], current_sha: Mapping[str, str]) -> dict[str, Any]:
    """The last ``freeze_F_a`` ledger note must exist and match every frozen file."""
    notes = [r for r in records if r.get("kind") == "freeze_F_a"]
    if not notes:
        raise FreezeMissing("no F_a freeze recorded: reserved P5a generation refused")
    payload = notes[-1]["payload"]
    diff = [f for f, h in payload["files_sha256"].items() if current_sha.get(f) != h]
    if diff:
        raise FreezeMissing(f"files changed since F_a: {diff}")
    return payload
