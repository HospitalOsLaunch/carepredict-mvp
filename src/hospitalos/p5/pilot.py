"""Timed pilot with immutable run identity and stop rules (review P5L-02/P5L-03).

* Each run has an identity (effective commitment E_k, code hashes, partition, stable structure
  ids, parents, K, regimes, environment, pilot parameters) and lives in its own directory
  ``runs/<run_id>/``. A record is reused on resume only if it carries the same run identity;
  a directory whose identity differs is refused, never overwritten. Older runs (including the
  initial pilot ``pilot_parents.jsonl`` of E0) are kept untouched.
* Stop rules: an invariant/admissibility violation (including the habitual-practice invariant
  failure reported by v6), a universe that changes across realisations, or a recommended plan
  absent from the public universe stops the run and writes FAILURE_RECEIPT.json. Genuine
  abstentions are evaluated as HABITUAL-1 and counted (P5-PROTO-3.1).
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from importlib import metadata
from pathlib import Path
from typing import Any

from hospitalos.decision_support.planner import recommend as v6_recommend

from . import truth as T
from .analysis import hierarchical_bootstrap, structure_weighted_mean
from .eval_adapter import outcome as v6_outcome
from .features import SnapshotFeatures
from .generator import generate_structure, make_twin, realise_episode

PILOT_SCHEMA = "HOSPITALOS_P5_PILOT_RUN_2"
SELECTED = {"RECOMMENDATION_READY", "NO_ACTION_PREFERRED"}


class PilotStop(RuntimeError):
    """A stop rule fired; FAILURE_RECEIPT.json has been written."""


class RuntimeRefused(RuntimeError):
    """The running interpreter is not an approved (Python version, freeze) pair."""


def check_runtime(env: Mapping[str, Any], approved: set[tuple[str, str]]) -> None:
    """In-process control, before any scientific operation (review R-P5-01)."""
    pair = (str(env.get("python")), str(env.get("freeze_sha256")))
    if pair not in approved:
        raise RuntimeRefused(f"runtime not approved: python={pair[0]} freeze={pair[1]}")


class ResumeRefused(RuntimeError):
    """Existing records belong to another run identity: never mixed, never overwritten."""


def running_environment() -> dict[str, Any]:
    lines = sorted(
        (
            f"{d.metadata['Name']}=={d.version}"
            for d in metadata.distributions()
            if d.metadata["Name"].lower() not in {"pip", "setuptools"}
        ),
        key=lambda x: x.split("==")[0].lower(),
    )
    freeze = "\n".join(lines) + "\n"
    return {"python": sys.version.split()[0], "executable": sys.executable,
            "freeze_sha256": hashlib.sha256(freeze.encode()).hexdigest()}


def structure_id(partition: str, seed: int) -> str:
    return hashlib.sha256(f"{partition}|{seed}".encode()).hexdigest()[:16]


def run_identity(
    commitment: Mapping[str, Any],
    partition: str,
    seeds: Sequence[int],
    n_parents: int,
    k: int,
    regimes: Sequence[str],
    environment: Mapping[str, Any],
    pilot_code_sha256: str,
) -> dict[str, Any]:
    body = {
        "schema": PILOT_SCHEMA,
        "commitment_stage": commitment.get("stage"),
        "commitment_id": commitment["commitment_id"],
        "commitment_ledger_record": commitment.get("ledger_record_sha256"),
        "code_sha256": dict(sorted(commitment["code_sha256"].items())),
        "pilot_code_sha256": pilot_code_sha256,
        "partition": partition,
        "structures": [structure_id(partition, s) for s in seeds],
        "n_parents": n_parents,
        "K": k,
        "regimes": list(regimes),
        "environment": {"python": environment["python"], "freeze_sha256": environment["freeze_sha256"]},
    }
    body["run_id"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:20]
    return body


def _stop(run_dir: Path, identity: Mapping[str, Any], reason: str, detail: Mapping[str, Any]) -> None:
    receipt = {"run_id": identity["run_id"], "reason": reason, "detail": dict(detail), "identity": dict(identity)}
    (run_dir / "FAILURE_RECEIPT.json").write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n")
    raise PilotStop(f"{reason}: {json.dumps(detail, sort_keys=True)}")


def open_run(out_dir: Path, identity: Mapping[str, Any]) -> tuple[Path, set[tuple[str, int]]]:
    run_dir = out_dir / "runs" / str(identity["run_id"])
    ident_path = run_dir / "RUN_IDENTITY.json"
    records = run_dir / "pilot_parents.jsonl"
    if run_dir.exists():
        if not ident_path.exists() or json.loads(ident_path.read_text()) != dict(identity):
            raise ResumeRefused(f"run directory {run_dir} holds another identity")
        if (run_dir / "FAILURE_RECEIPT.json").exists():
            raise ResumeRefused("this run stopped on a failure receipt; a new identity is required")
    else:
        run_dir.mkdir(parents=True)
        ident_path.write_text(json.dumps(dict(identity), indent=1, sort_keys=True) + "\n")
    done: set[tuple[str, int]] = set()
    if records.exists():
        for line in records.read_text().splitlines():
            r = json.loads(line)
            if r.get("run_id") != identity["run_id"]:
                raise ResumeRefused("record from another run identity found")
            done.add((r["structure_id"], int(r["parent_index"])))
    return run_dir, done


def run_pilot(
    *,
    out_dir: Path,
    identity: Mapping[str, Any],
    seeds: Sequence[int],
    profile: Mapping[str, Any],
    settings: Any,
    recommend_fn: Callable[..., Any] = v6_recommend,
    outcome_fn: Callable[..., Any] = v6_outcome,
    bootstrap_seed: int = 12345,
) -> dict[str, Any]:
    run_dir, done = open_run(out_dir, identity)
    partition, k, regimes = identity["partition"], int(identity["K"]), tuple(identity["regimes"])
    records_path = run_dir / "pilot_parents.jsonl"
    for seed in seeds:
        sid = structure_id(partition, seed)
        t0 = time.perf_counter()
        valid, every = generate_structure(partition, seed, int(identity["n_parents"]), profile, twins=False)
        gen_s = time.perf_counter() - t0
        exclusions: dict[str, int] = {}
        for c in every:
            if c.excluded:
                exclusions[c.excluded] = exclusions.get(c.excluded, 0) + 1
        for cand in valid:
            if (sid, cand.parent_index) in done:
                continue
            ep = cand.episodes["A"]
            where = {"structure_id": sid, "parent_index": cand.parent_index}
            rec: dict[str, Any] = {"run_id": identity["run_id"], **where, "n_plans": len(ep.plans),
                                   "structure_candidates": len(every), "structure_exclusions": exclusions,
                                   "generation_s_per_parent": gen_s / len(every)}
            t = time.perf_counter()
            reco = recommend_fn(ep.snapshot, settings)
            rec["recommend_s"] = time.perf_counter() - t
            rec["recommend_status"] = reco.status
            ids = [p.plan_id for p in ep.plans]
            if reco.status == "INFEASIBLE" and "habitual_practice_invariant_failure" in tuple(getattr(reco, "reasons", ())):
                _stop(run_dir, identity, "habitual_practice_invariant_failure", where)
            if reco.status in SELECTED:
                if reco.primary_plan_id not in ids:
                    _stop(run_dir, identity, "recommended_plan_outside_public_universe",
                          {**where, "primary_plan_id": reco.primary_plan_id})
                chosen, abstention = ids.index(reco.primary_plan_id), False
            else:
                # genuine abstention (insufficient data, hypothetical only, invalidated, other
                # infeasibility) -> evaluated as HABITUAL-1 and counted; never an invariant failure
                chosen, abstention = 0, True
            rec["chosen_index"] = chosen
            rec["abstention_as_habitual"] = abstention
            universe_fp = ep.universe_fingerprint
            U: dict[str, list[list[int]]] = {}
            sims = 0
            t = time.perf_counter()
            for regime in regimes:
                U[regime] = []
                for rep in range(1, k + 1):
                    real = T.realise(ep, regime, rep, str(identity["commitment_id"]))
                    row = []
                    for i, plan in enumerate(ep.plans):
                        out = outcome_fn(ep.snapshot, plan, real, profile)
                        if out.violations:
                            _stop(run_dir, identity, "invariant_or_admissibility_violation",
                                  {**where, "plan_index": i, "regime": regime, "replicate": rep,
                                   "violations": list(out.violations)})
                        row.append(out.U)
                        sims += 1
                    U[regime].append(row)
                    if ep.universe_fingerprint != universe_fp:
                        _stop(run_dir, identity, "universe_changed_across_realisations", where)
            rec["truth_sim_s"] = time.perf_counter() - t
            rec["truth_sims"] = sims
            rec["U_dev_only"] = U
            t = time.perf_counter()
            feats = SnapshotFeatures(ep.snapshot, ep.sidecar, profile)
            rows = 0
            for plan in ep.plans:
                for fam in ("M_agg", "M_ent"):
                    feats.row(plan, fam)
                    rows += 1
            rec["extraction_s"] = time.perf_counter() - t
            rec["extraction_rows"] = rows
            t = time.perf_counter()
            twin = make_twin(ep.spec)
            if twin is not None:
                realise_episode(twin, profile)
            rec["twin_s"] = time.perf_counter() - t
            rec["twin_degenerate"] = twin is None
            with records_path.open("a") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
    records = [json.loads(x) for x in records_path.read_text().splitlines()]
    by_s: dict[str, list[dict[str, float]]] = {}
    for r in records:
        u = r["U_dev_only"][regimes[0]]
        hab = sum(row[0] for row in u) / len(u)
        plan_u = sum(row[r["chosen_index"]] for row in u) / len(u)
        by_s.setdefault(r["structure_id"], []).append({"gain": hab - plan_u})
    t = time.perf_counter()
    hierarchical_bootstrap(list(by_s.values()), lambda d: structure_weighted_mean(d, "gain"), 2000, bootstrap_seed)
    summary = {"run_id": identity["run_id"], "parents": len(records), "bootstrap_2000_s": time.perf_counter() - t,
               "note": "development data; timing deliverable; values are not results"}
    (run_dir / "pilot_bootstrap.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary
