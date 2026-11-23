"""P5A-D02 RESUME — isolation check v2 for selection indices 47-49 (adopted; POST-FREEZE).

Method v2 (differs from the 47 historical receipts of v1, which stay unchanged):
the product checks are NOT conditioned on any effect on HABITUAL-1.

Truths: A = (R1, k=1); B in the fixed order (R2,3), (R2,2), (R2,1), (R1,3), (R1,2); no new draw.
A B whose private truth (values and presences) equals A's is flagged "identical_truth".

Assertions per resumed episode:
  T03-a  v6 public recommendation computed twice: identical JSON, and equal to the plan
         recorded by P5a for this parent (abstention only if recorded as habitual).
  T03-b  check_isolation(ReferenceForecaster) passes for EVERY plan of the reconstructed public
         universe against EVERY B (A vs B), whatever the existence of a sensitive witness.
  T04-a  witness search over the EXISTING public universe: B in the fixed order, plans in the
         universe order; signature = exactly the projection compared by check_isolation for an
         outcome backend: repr((departures, admissions, uncovered_unit, uncovered_waiting)) of
         PrivateOracle(truth).outcome(snapshot, plan, config). First (B, plan) whose signatures
         differ = witness: check_isolation(PrivateOracle) MUST raise LeakageError on it (else
         stop: false negative). No differing signature anywhere -> T04-a = NON_INFORMATIF for
         these truths and this projection (episode kept, no fictitious success, no replacement).
  T04-b  assert_product_backend(PrivateOracle) raises LeakageError; product_allowed is False.
  T04-c  recommend(snapshot, settings with PrivateOracle backend) raises LeakageError.
  T04-d  ReferenceForecaster.forecast on a non-PublicSnapshot input raises LeakageError.
Stops (receipt, no correction): universe/plan mismatch at reconstruction, T03-a mismatch,
T03-b dependence on truth, T04-a false negative, T04-b/c/d not blocked. The absence of a
sensitive witness is NOT a leak.
"""

from __future__ import annotations

from collections.abc import Mapping
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
from .isolation50 import TRUTH_A, TRUTH_B_ORDER, IsolationFailure

METHOD = "v2"
RESUME_INDICES = (47, 48, 49)


def oracle_signature(truth: Any, snapshot: Any, plan: Any, cfg: Any) -> str:
    """Exactly the projection compared by check_isolation for an outcome backend."""
    run = PrivateOracle(truth).outcome(snapshot, plan, cfg)
    return repr((run.departures, run.admissions, run.uncovered_unit, run.uncovered_waiting))


def _same_truth(a: Any, b: Any) -> bool:
    return dict(a.truth.values) == dict(b.truth.values) and dict(a.presence) == dict(b.presence)


def check_episode_v2(ep: Any, recorded: Mapping[str, Any], settings: Settings, commitment: str) -> dict[str, Any]:
    snap = ep.snapshot
    where = {"structure_id": recorded["structure_id"], "parent_index": recorded["parent_index"]}
    cfg = _config(settings, snap.as_of, 24)
    a = T.realise(ep, TRUTH_A[0], TRUTH_A[1], commitment)
    bs = [(key, T.realise(ep, key[0], key[1], commitment)) for key in TRUTH_B_ORDER]
    identical = [list(k) for k, b in bs if _same_truth(a, b)]
    # T03-a
    r1 = recommend(snap, settings).model_dump_json()
    r2 = recommend(snap, settings).model_dump_json()
    if r1 != r2:
        raise IsolationFailure("T03a_recommendation_differs", where)
    reco = recommend(snap, settings)
    chosen_recorded = recorded["plans"][recorded["chosen_index"]]["plan_id"]
    if reco.status in {"RECOMMENDATION_READY", "NO_ACTION_PREFERRED"}:
        if reco.primary_plan_id != chosen_recorded:
            raise IsolationFailure("T03a_choice_differs_from_record",
                                   {**where, "recorded": chosen_recorded, "now": reco.primary_plan_id})
    elif recorded["chosen_index"] != 0:
        raise IsolationFailure("T03a_abstention_differs_from_record", where)
    # T03-b: every plan x every B
    t03b = 0
    for i, plan in enumerate(ep.plans):
        for key, b in bs:
            try:
                check_isolation(lambda truth: ReferenceForecaster(), snap, plan, cfg, a.truth, b.truth)
            except LeakageError as error:
                raise IsolationFailure("T03b_product_backend_output_depends_on_truth",
                                       {**where, "plan_index": i, "truth_B": list(key), "error": str(error)}) from error
            t03b += 1
    # T04-a: witness search (fixed B order, universe order)
    witness = None
    examined = 0
    for key, b in bs:
        for i, plan in enumerate(ep.plans):
            examined += 1
            if oracle_signature(a.truth, snap, plan, cfg) != oracle_signature(b.truth, snap, plan, cfg):
                witness = (key, i)
                break
        if witness:
            break
    if witness is None:
        t04a = "NON_INFORMATIF"
    else:
        key, i = witness
        b = dict(bs)[key]
        try:
            check_isolation(PrivateOracle, snap, ep.plans[i], cfg, a.truth, b.truth)
        except LeakageError:
            t04a = "DETECTED"
        else:
            raise IsolationFailure("T04a_false_negative_on_distinct_signature", {**where, "plan_index": i, "truth_B": list(key)})
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
    return {**where, "method": METHOD, "n_plans": len(ep.plans), "truth_A": list(TRUTH_A),
            "truth_B_order": [list(k) for k in TRUTH_B_ORDER], "identical_truths": identical,
            "T03a": "pass", "recommend_status": reco.status, "chosen_plan_matches_record": True,
            "T03b_plan_truth_pairs_checked": t03b, "T03b": "pass",
            "T04a": t04a, "T04a_witness": None if witness is None else {"truth_B": list(witness[0]), "plan_index": witness[1]},
            "T04a_pairs_examined": examined,
            "T04b": "pass", "T04c": "pass", "T04d": "pass"}


def require_recorded_procedure(proc_path: Any, ledger: list[Mapping[str, Any]], kind: str, module_sha: str) -> tuple[bool, str]:
    """Clean refusal BEFORE any reconstruction or test (review: no uncaught FileNotFoundError)."""
    import json

    if not proc_path.exists():
        return False, "procedure_missing"
    proc = json.loads(proc_path.read_text())
    notes = [r for r in ledger if r.get("kind") == kind]
    if not notes:
        return False, "procedure_not_recorded"
    if notes[-1].get("payload") != proc:
        return False, "procedure_differs_from_ledger"
    if proc.get("module_sha256") != module_sha:
        return False, "module_changed_since_procedure"
    return True, "ok"
