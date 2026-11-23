"""P5b executor and selection logic (authorisation (iii), option A; P5-PROTO-2 § 6 as amended
by P5-PROTO-3 / 3.1).

* Parents are generated WITH twins (A, B: permuted logistic vectors). Every plan of each twin's
  complete public universe is evaluated under the private truth for each regime and replicate
  (keyed innovations shared by plans and twins). Train/validation: R1 only; reserved evaluation:
  R1 and R2, plus the v6 public planner (secondary comparator).
* Homologous plans across twins share the same sorted action-id key (stay and offer ids are
  unchanged by the twin permutation).
* Twin precheck (train, R1, K_precheck = 3): theta = structure -> parent -> plans weighted mean of
  mean(g)^2 - var(g)/K with g_k = [U_A,k(a) - U_A,k(hab)] - [U_B,k(a) - U_B,k(hab)]; informative iff
  the one-sided 95% bootstrap lower bound >= 25 staff-minutes^2.
* Plan choice from predictions: argmin prediction with OBJ-LEX-1 ties (tolerance 15, then fewer
  planned reinforcement hours, then fewer interventions, then lower prediction, then universe order).
Execution folders are named ``executions/`` (never ``runs/``, which the repository ignores).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from hospitalos.decision_support.planner import recommend as v6_recommend

from . import truth as T
from .eval_adapter import outcome as v6_outcome
from .features import SnapshotFeatures
from .generator import generate_structure
from .pilot import SELECTED, PilotStop, ResumeRefused, structure_id

TOLERANCE = 15.0
THETA_MIN = 25.0
FIELDS = ("U", "realised_hours", "lent_hours", "waiting", "beds", "peak", "above")


def plan_key(plan: Any) -> list[str]:
    return sorted(a.action_id for a in plan.actions)


def plan_descriptor(plan: Any) -> dict[str, Any]:
    coord = sorted(a.action_id for a in plan.actions if a.type == "coordinate_discharge")
    reinf = sorted(a.action_id for a in plan.actions if a.type == "reinforcement")
    cls = "H" if not plan.actions else ("CR" if coord and reinf else ("C" if coord else "R"))
    return {"plan_id": plan.plan_id, "key": plan_key(plan), "coord": coord, "reinf": reinf, "class": cls,
            "planned_hours": plan.reinforcement_hours, "interventions": plan.interventions}


# --------------------------------------------------------------------------- run folders


def open_execution(out_dir: Path, identity: Mapping[str, Any]) -> tuple[Path, set[tuple[str, int]]]:
    run_dir = out_dir / "executions" / str(identity["run_id"])
    ident_path = run_dir / "RUN_IDENTITY.json"
    records = run_dir / "parents.jsonl"
    if run_dir.exists():
        if not ident_path.exists() or json.loads(ident_path.read_text()) != dict(identity):
            raise ResumeRefused(f"execution directory {run_dir} holds another identity")
        if (run_dir / "FAILURE_RECEIPT.json").exists():
            raise ResumeRefused("this execution stopped on a failure receipt")
    else:
        run_dir.mkdir(parents=True)
        ident_path.write_text(json.dumps(dict(identity), indent=1, sort_keys=True) + "\n")
    done: set[tuple[str, int]] = set()
    if records.exists():
        for line in records.read_text().splitlines():
            r = json.loads(line)
            if r.get("run_id") != identity["run_id"]:
                raise ResumeRefused("record from another identity found")
            done.add((r["structure_id"], int(r["parent_index"])))
    return run_dir, done


def _stop(run_dir: Path, identity: Mapping[str, Any], reason: str, detail: Mapping[str, Any]) -> None:
    (run_dir / "FAILURE_RECEIPT.json").write_text(json.dumps(
        {"run_id": identity["run_id"], "reason": reason, "detail": dict(detail)}, indent=1, sort_keys=True) + "\n")
    raise PilotStop(f"{reason}: {json.dumps(detail, sort_keys=True)}")


# --------------------------------------------------------------------------- evaluation


def evaluate_twin(
    ep: Any, *, run_dir: Path, identity: Mapping[str, Any], where: Mapping[str, Any], profile: Mapping[str, Any],
    score: Mapping[str, Any] | None, with_planner: bool, settings: Any = None,
    recommend_fn: Callable[..., Any] = v6_recommend, outcome_fn: Callable[..., Any] = v6_outcome,
) -> dict[str, Any]:
    k, regimes = int(identity["K"]), tuple(identity["regimes"])
    ids = [p.plan_id for p in ep.plans]
    out: dict[str, Any] = {"n_plans": len(ep.plans), "universe_fingerprint": ep.universe_fingerprint,
                           "plans": [plan_descriptor(p) for p in ep.plans]}
    if out["plans"][0]["class"] != "H":
        _stop(run_dir, identity, "plan0_not_habitual", where)
    if with_planner:
        reco = recommend_fn(ep.snapshot, settings)
        reasons = tuple(getattr(reco, "reasons", ()))
        if reco.status == "INFEASIBLE" and "habitual_practice_invariant_failure" in reasons:
            _stop(run_dir, identity, "habitual_practice_invariant_failure", where)
        if reco.status in SELECTED:
            if reco.primary_plan_id not in ids:
                _stop(run_dir, identity, "recommended_plan_outside_public_universe", {**where, "primary": reco.primary_plan_id})
            out["planner"] = {"status": reco.status, "chosen_index": ids.index(reco.primary_plan_id), "abstention": False}
        else:
            out["planner"] = {"status": reco.status, "chosen_index": 0, "abstention": True}
    fp = ep.universe_fingerprint
    out["outcomes"] = {}
    for regime in regimes:
        res: dict[str, list[list[Any]]] = {f: [] for f in FIELDS}
        for rep in range(1, k + 1):
            real = T.realise(ep, regime, rep, str(identity["commitment_id"]))
            rows: dict[str, list[Any]] = {f: [] for f in FIELDS}
            for i, plan in enumerate(ep.plans):
                o = outcome_fn(ep.snapshot, plan, real, profile, score)
                if o.violations:
                    _stop(run_dir, identity, "invariant_or_admissibility_violation",
                          {**where, "plan_index": i, "regime": regime, "replicate": rep, "violations": list(o.violations)})
                for f, v in zip(FIELDS, (o.U, o.realised_reinforcement_hours, o.lent_hours_realised, o.waiting_patient_hours,
                                         o.beds_returned, o.peak_pressure, o.hours_above_threshold), strict=True):
                    rows[f].append(v)
            for f in FIELDS:
                res[f].append(rows[f])
            if ep.universe_fingerprint != fp:
                _stop(run_dir, identity, "universe_changed_across_realisations", where)
        out["outcomes"][regime] = res
    return out


def run_segment(
    *, out_dir: Path, identity: Mapping[str, Any], seeds: Sequence[int], indices: Sequence[int],
    profile: Mapping[str, Any], score: Mapping[str, Any] | None, with_planner: bool, settings: Any = None,
    recommend_fn: Callable[..., Any] = v6_recommend, outcome_fn: Callable[..., Any] = v6_outcome,
) -> dict[str, Any]:
    run_dir, done = open_execution(out_dir, identity)
    partition, n_parents = identity["partition"], int(identity["n_parents"])
    records, structures = run_dir / "parents.jsonl", run_dir / "structures.jsonl"
    seen = {json.loads(x)["structure_id"] for x in structures.read_text().splitlines()} if structures.exists() else set()
    new = 0
    t0 = time.perf_counter()
    for idx in indices:
        seed = seeds[idx]
        sid = structure_id(partition, seed)
        valid, every = generate_structure(partition, seed, n_parents, profile, twins=True)
        if sid not in seen:
            excl: dict[str, int] = {}
            for c in every:
                if c.excluded:
                    excl[c.excluded] = excl.get(c.excluded, 0) + 1
            with structures.open("a") as fh:
                fh.write(json.dumps({"run_id": identity["run_id"], "structure_id": sid, "structure_index": idx,
                                     "candidates": len(every), "valid": len(valid), "exclusions": excl}, sort_keys=True) + "\n")
            seen.add(sid)
        for cand in valid:
            if (sid, cand.parent_index) in done:
                continue
            where = {"structure_id": sid, "structure_index": idx, "parent_index": cand.parent_index}
            rec = {"run_id": identity["run_id"], **where, "twins": {}}
            for t in ("A", "B"):
                rec["twins"][t] = evaluate_twin(cand.episodes[t], run_dir=run_dir, identity=identity, where={**where, "twin": t},
                                                profile=profile, score=score, with_planner=with_planner, settings=settings,
                                                recommend_fn=recommend_fn, outcome_fn=outcome_fn)
            with records.open("a") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
            done.add((sid, cand.parent_index))
            new += 1
    return {"run_id": identity["run_id"], "new_parents": new, "total_parents": len(done), "seconds": time.perf_counter() - t0}


# --------------------------------------------------------------------------- twin precheck


def precheck_terms(rec: Mapping[str, Any], regime: str = "R1") -> list[float]:
    A, B = rec["twins"]["A"], rec["twins"]["B"]
    ia = {tuple(p["key"]): i for i, p in enumerate(A["plans"])}
    ib = {tuple(p["key"]): i for i, p in enumerate(B["plans"])}
    UA, UB = np.asarray(A["outcomes"][regime]["U"], float), np.asarray(B["outcomes"][regime]["U"], float)
    k = UA.shape[0]
    terms = []
    for key in sorted(set(ia) & set(ib)):
        if not key:
            continue
        g = (UA[:, ia[key]] - UA[:, 0]) - (UB[:, ib[key]] - UB[:, 0])
        terms.append(float(g.mean() ** 2 - g.var(ddof=1) / k))
    return terms


def precheck(records: Sequence[Mapping[str, Any]], seed: int, resamples: int = 2000) -> dict[str, Any]:
    by_s: dict[str, list[float]] = {}
    no_homologous = 0
    best_change = []
    for r in sorted(records, key=lambda r: (r["structure_index"], r["parent_index"])):
        terms = precheck_terms(r)
        if not terms:
            no_homologous += 1
            continue
        by_s.setdefault(r["structure_id"], []).append(float(np.mean(terms)))
        A, B = r["twins"]["A"], r["twins"]["B"]
        mA = np.asarray(A["outcomes"]["R1"]["U"], float).mean(axis=0)
        mB = np.asarray(B["outcomes"]["R1"]["U"], float).mean(axis=0)
        ia = {tuple(p["key"]): i for i, p in enumerate(A["plans"])}
        ib = {tuple(p["key"]): i for i, p in enumerate(B["plans"])}
        common = sorted(set(ia) & set(ib))
        best_change.append(min(common, key=lambda kk: (mA[ia[kk]], kk)) != min(common, key=lambda kk: (mB[ib[kk]], kk)))
    structs = [np.asarray(v) for v in by_s.values()]
    point = float(np.mean([s.mean() for s in structs]))
    rng = np.random.default_rng(seed)
    boot = np.empty(resamples)
    for b in range(resamples):
        means = []
        for i in rng.integers(0, len(structs), len(structs)):
            s = structs[int(i)]
            means.append(s[rng.integers(0, len(s), len(s))].mean())
        boot[b] = float(np.mean(means))
    lower = float(np.quantile(boot, 0.05))
    return {"theta_point": point, "theta_lower_one_sided_95": lower, "threshold": THETA_MIN,
            "informative": lower >= THETA_MIN, "rms_effect_difference_point": float(np.sqrt(max(point, 0.0))),
            "parents_used": int(sum(len(s) for s in structs)), "structures": len(structs),
            "parents_without_homologous_plan": no_homologous,
            "rate_best_homologous_plan_changes": float(np.mean(best_change)) if best_change else None}


# --------------------------------------------------------------------------- matrices and choice


def build_matrices(records: Sequence[Mapping[str, Any]], seed_of: Mapping[str, int], partition: str,
                   profile: Mapping[str, Any], n_parents: int, regime: str = "R1") -> dict[str, Any]:
    """Regenerates the public episodes (deterministic) and builds one row per (parent, twin, plan)."""
    rows = {"M_agg": [], "M_ent": []}
    y, w, index = [], [], []
    by_s: dict[str, list[Mapping[str, Any]]] = {}
    for r in records:
        by_s.setdefault(r["structure_id"], []).append(r)
    for sid in sorted(by_s, key=lambda s: by_s[s][0]["structure_index"]):
        valid, _ = generate_structure(partition, seed_of[sid], n_parents, profile, twins=True)
        eps = {c.parent_index: c.episodes for c in valid}
        n_valid = len(by_s[sid])
        for r in sorted(by_s[sid], key=lambda r: r["parent_index"]):
            for t in ("A", "B"):
                ep, tr = eps[r["parent_index"]][t], r["twins"][t]
                if [p.plan_id for p in ep.plans] != [p["plan_id"] for p in tr["plans"]] or ep.universe_fingerprint != tr["universe_fingerprint"]:
                    raise ValueError(f"universe mismatch at {sid}/{r['parent_index']}/{t}")
                feats = SnapshotFeatures(ep.snapshot, ep.sidecar, profile)
                U = np.asarray(tr["outcomes"][regime]["U"], float).mean(axis=0) if regime in tr["outcomes"] else None
                for i, plan in enumerate(ep.plans):
                    for fam in rows:
                        rows[fam].append(feats.row(plan, fam)[1])
                    y.append(float(U[i]) if U is not None else np.nan)
                    w.append((1.0 / len(ep.plans)) * (n_parents / n_valid))
                    index.append((sid, r["parent_index"], t, i))
    return {"M_agg": np.asarray(rows["M_agg"], float), "M_ent": np.asarray(rows["M_ent"], float),
            "y": np.asarray(y, float), "w": np.asarray(w, float), "index": index}


def choose(pred: Sequence[float], plans: Sequence[Mapping[str, Any]]) -> int:
    best = min(pred)
    cands = [i for i in range(len(pred)) if pred[i] <= best + TOLERANCE]
    return min(cands, key=lambda i: (plans[i]["planned_hours"], plans[i]["interventions"], pred[i], i))


def choices(pred: np.ndarray, index: Sequence[tuple], records: Sequence[Mapping[str, Any]]) -> dict[tuple, int]:
    rec = {(r["structure_id"], r["parent_index"]): r for r in records}
    groups: dict[tuple, list[tuple[int, float]]] = {}
    for row, (sid, p, t, i) in enumerate(index):
        groups.setdefault((sid, p, t), []).append((i, float(pred[row])))
    out = {}
    for key, items in groups.items():
        items.sort()
        plans = rec[(key[0], key[1])]["twins"][key[2]]["plans"]
        out[key] = choose([v for _, v in items], plans)
    return out


def realised_choice_value(chosen: Mapping[tuple, int], records: Sequence[Mapping[str, Any]], regime: str = "R1") -> float:
    """Structure-weighted mean (structure -> parent -> twin -> replicate) of realised U of chosen plans."""
    by_s: dict[str, list[float]] = {}
    for r in records:
        vals = []
        for t in ("A", "B"):
            U = np.asarray(r["twins"][t]["outcomes"][regime]["U"], float)
            vals.append(float(U[:, chosen[(r["structure_id"], r["parent_index"], t)]].mean()))
        by_s.setdefault(r["structure_id"], []).append(float(np.mean(vals)))
    return float(np.mean([np.mean(v) for v in by_s.values()]))


def weighted_mae(pred: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    return float(np.sum(w * np.abs(pred - y)) / np.sum(w))


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()
