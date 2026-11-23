"""P5A-D02 — T03/T04 isolation check on 50 already-evaluated P5a episodes (POST-FREEZE).

Adopted procedure (recorded in the ledger before execution; criteria not weakened):

Selection (independent of gains, regrets and any outcome): among the 300 reserved P5a_eval
parents, structures are ordered by sha256("P5a-isolation50|<commitment>|<structure_id>") and,
inside each structure, parents by sha256("P5a-isolation50|<commitment>|<structure_id>|<parent>").
Round-robin: first parent of every structure (30), then second parent of the first 20
structures in that order -> 50 parents.

Reconstruction: public snapshots regenerated from the sealed seeds and frozen sources; the plan
identifiers and the universe fingerprint must equal the recorded ones (otherwise stop).

Truth pair: A = realisation (R1, k=1); B = first of (R2,3), (R2,2), (R2,1), (R1,3), (R1,2) whose
truth-run of HABITUAL-1 differs from A's (the pair must give the leak detector something to
detect). No such pair -> failure.

Assertions per episode (all required):
  T03-a  the v6 public recommendation is computed twice (around the two truths): identical JSON;
         its chosen plan equals the plan recorded by P5a for this parent.
  T03-b  check_isolation(ReferenceForecaster) passes for EVERY plan of the universe under A and B
         (v6 T03 checks the habitual plan only).
  T04-a  check_isolation(PrivateOracle) raises LeakageError on HABITUAL-1 (and the number of plans
         of the universe on which it fires is recorded).
  T04-b  assert_product_backend(PrivateOracle) raises LeakageError; product_allowed is False.
  T04-c  recommend(snapshot, settings with the PrivateOracle backend) raises LeakageError.
  T04-d  ReferenceForecaster.forecast on a non-PublicSnapshot input raises LeakageError.
Any failed assertion stops the run with a failure receipt; nothing is corrected or substituted.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from hospitalos.decision_support.planner import Settings, _config, recommend
from hospitalos.decision_support.reference_forecaster import (
    LeakageError,
    PrivateOracle,
    ReferenceForecaster,
    assert_product_backend,
    check_isolation,
)

from . import truth as T
from .generator import generate_structure

SALT = "P5a-isolation50"
N_SELECT = 50
TRUTH_A = ("R1", 1)
TRUTH_B_ORDER = (("R2", 3), ("R2", 2), ("R2", 1), ("R1", 3), ("R1", 2))


class IsolationFailure(RuntimeError):
    def __init__(self, kind: str, detail: Mapping[str, Any]) -> None:
        super().__init__(f"{kind}: {dict(detail)}")
        self.kind = kind
        self.detail = dict(detail)


def _h(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, (SALT, *parts))).encode()).hexdigest()


def select(parents: Sequence[tuple[str, int]], commitment: str, n: int = N_SELECT) -> list[tuple[str, int]]:
    by_s: dict[str, list[int]] = {}
    for sid, p in parents:
        by_s.setdefault(sid, []).append(int(p))
    order = sorted(by_s, key=lambda s: _h(commitment, s))
    for s in order:
        by_s[s].sort(key=lambda p: _h(commitment, s, p))
    out: list[tuple[str, int]] = []
    rnd = 0
    while len(out) < n:
        progressed = False
        for s in order:
            if rnd < len(by_s[s]) and len(out) < n:
                out.append((s, by_s[s][rnd]))
                progressed = True
        if not progressed:
            raise ValueError("not enough parents to select from")
        rnd += 1
    return out


def reconstruct(
    selection: Sequence[tuple[str, int]],
    seed_of_structure: Mapping[str, int],
    recorded: Mapping[tuple[str, int], Mapping[str, Any]],
    profile: Mapping[str, Any],
    partition: str = "P5a_eval",
    n_parents: int = 10,
) -> dict[tuple[str, int], Any]:
    wanted: dict[str, set[int]] = {}
    for sid, p in selection:
        wanted.setdefault(sid, set()).add(p)
    episodes = {}
    for sid, parents in wanted.items():
        valid, _ = generate_structure(partition, seed_of_structure[sid], n_parents, profile, twins=False)
        by_p = {c.parent_index: c.episodes["A"] for c in valid}
        for p in sorted(parents):
            ep = by_p.get(p)
            rec = recorded[(sid, p)]
            if ep is None:
                raise IsolationFailure("reconstruction_missing_parent", {"structure_id": sid, "parent_index": p})
            if [x.plan_id for x in ep.plans] != [x["plan_id"] for x in rec["plans"]] or ep.universe_fingerprint != rec["universe_fingerprint"]:
                raise IsolationFailure("reconstruction_universe_mismatch", {"structure_id": sid, "parent_index": p})
            episodes[(sid, p)] = ep
    return episodes


def _habitual_run(truth: Any, ep: Any, cfg: Any) -> str:
    run = PrivateOracle(truth).outcome(ep.snapshot, ep.plans[0], cfg)
    return repr((run.departures, run.admissions, run.uncovered_unit, run.uncovered_waiting))


def check_episode(ep: Any, recorded: Mapping[str, Any], settings: Settings, commitment: str) -> dict[str, Any]:
    snap = ep.snapshot
    where = {"structure_id": recorded["structure_id"], "parent_index": recorded["parent_index"]}
    cfg = _config(settings, snap.as_of, 24)
    a = T.realise(ep, TRUTH_A[0], TRUTH_A[1], commitment)
    ha = _habitual_run(a.truth, ep, cfg)
    b = None
    for regime, k in TRUTH_B_ORDER:
        cand = T.realise(ep, regime, k, commitment)
        if _habitual_run(cand.truth, ep, cfg) != ha:
            b, b_key = cand, (regime, k)
            break
    if b is None:
        raise IsolationFailure("no_distinguishable_truth_pair", where)
    # T03-a
    r1 = recommend(snap, settings).model_dump_json()
    r2 = recommend(snap, settings).model_dump_json()
    if r1 != r2:
        raise IsolationFailure("T03a_recommendation_differs", where)
    reco = recommend(snap, settings)
    chosen_recorded = recorded["plans"][recorded["chosen_index"]]["plan_id"]
    if reco.status in {"RECOMMENDATION_READY", "NO_ACTION_PREFERRED"}:
        if reco.primary_plan_id != chosen_recorded:
            raise IsolationFailure("T03a_choice_differs_from_record", {**where, "recorded": chosen_recorded, "now": reco.primary_plan_id})
    elif recorded["chosen_index"] != 0:
        raise IsolationFailure("T03a_abstention_differs_from_record", where)
    # T03-b: product backend isolated on every plan
    for i, plan in enumerate(ep.plans):
        try:
            check_isolation(lambda truth: ReferenceForecaster(), snap, plan, cfg, a.truth, b.truth)
        except LeakageError as error:
            raise IsolationFailure("T03b_product_backend_output_depends_on_truth", {**where, "plan_index": i, "error": str(error)}) from error
    # T04-a: the detector catches a truth-reading backend
    fired = 0
    for plan in ep.plans:
        try:
            check_isolation(PrivateOracle, snap, plan, cfg, a.truth, b.truth)
        except LeakageError:
            fired += 1
    try:
        check_isolation(PrivateOracle, snap, ep.plans[0], cfg, a.truth, b.truth)
        raise IsolationFailure("T04a_oracle_not_detected_on_habitual", where)
    except LeakageError:
        pass
    # T04-b/c/d
    oracle = PrivateOracle(a.truth)
    if oracle.info().product_allowed is not False:
        raise IsolationFailure("T04b_oracle_product_allowed", where)
    for name, call in (
        ("T04b_assert_product_backend", lambda: assert_product_backend(oracle)),
        ("T04c_recommend_with_oracle", lambda: recommend(snap, Settings(settings.profile, settings.objective, settings.score, oracle))),
        ("T04d_forecast_non_public_input", lambda: ReferenceForecaster().forecast({"stays": []}, ep.plans[0], cfg)),  # type: ignore[arg-type]
    ):
        try:
            call()
        except LeakageError:
            continue
        raise IsolationFailure(f"{name}_not_blocked", where)
    return {**where, "n_plans": len(ep.plans), "truth_A": list(TRUTH_A), "truth_B": list(b_key),
            "T03a": "pass", "T03b_plans_checked": len(ep.plans), "T04a_detector_fired_on_plans": fired,
            "T04b": "pass", "T04c": "pass", "T04d": "pass", "recommend_status": reco.status,
            "chosen_plan_matches_record": True}
