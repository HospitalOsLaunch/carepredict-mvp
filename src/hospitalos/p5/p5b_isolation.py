"""P5b isolation check on 50 VALIDATION twin episodes, BEFORE F_b (method v2 for the models), and
the F_b freeze guard.

Selection (outcome-independent): episodes (structure, parent, twin) of P5b_val, structures ordered
by sha256("P5b-isolation50|<commitment>|<structure>") and episodes inside by
sha256("...|<structure>|<parent>|<twin>"), round-robin to 50.

Truths: A = (R1, k=1); B in the fixed order (R2,3), (R2,2), (R2,1), (R1,3), (R1,2); no new draw.
Assertions per episode:
  F1/T03  feature rows of every plan (M_agg and M_ent), the selected models' predictions and the
          resulting OBJ-LEX choices are IDENTICAL before any realisation and after realising A and
          each B (the model-based chooser reads public inputs only).
  T04-a   witness search over the public universe (B order, plan order) with the exact
          check_isolation projection; first differing signature -> PrivateOracle MUST be detected
          (else stop); none -> NON_INFORMATIF (named in advance, not a failure, not a success).
  T04-b/c/d  PrivateOracle refused as product backend, by recommend, and on non-public input.
Stops: reconstruction mismatch, any F1/T03 difference, T04-a false negative, T04-b/c/d not blocked.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from hospitalos.decision_support.planner import Settings, _config, recommend
from hospitalos.decision_support.reference_forecaster import (
    LeakageError,
    PrivateOracle,
    ReferenceForecaster,
    assert_product_backend,
    check_isolation,
)

from . import truth as T
from .features import SnapshotFeatures
from .generator import generate_structure
from .isolation50 import TRUTH_A, TRUTH_B_ORDER, IsolationFailure
from .isolation50_v2 import oracle_signature
from .p5b import choose, plan_descriptor

SALT = "P5b-isolation50"
N = 50
RULE = ("outcome-independent: structures by sha256(salt|commitment|structure), episodes by "
        "sha256(salt|commitment|structure|parent|twin), round-robin to 50 over P5b_val twin episodes")


class FreezeMissing(RuntimeError):
    pass


def require_freeze(records: Sequence[Mapping[str, Any]], current_sha: Mapping[str, str]) -> dict[str, Any]:
    notes = [r for r in records if r.get("kind") == "freeze_F_b"]
    if not notes:
        raise FreezeMissing("no F_b freeze recorded: reserved P5b generation/reading refused")
    payload = notes[-1]["payload"]
    diff = [f for f, h in payload["files_sha256"].items() if current_sha.get(f) != h]
    if diff:
        raise FreezeMissing(f"files changed since F_b: {diff}")
    return payload


def _h(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, (SALT, *parts))).encode()).hexdigest()


def select(episodes: Sequence[tuple[str, int, str]], commitment: str, n: int = N) -> list[tuple[str, int, str]]:
    by_s: dict[str, list[tuple[str, int, str]]] = {}
    for e in episodes:
        by_s.setdefault(e[0], []).append(e)
    order = sorted(by_s, key=lambda s: _h(commitment, s))
    for s in order:
        by_s[s].sort(key=lambda e: _h(commitment, e[0], e[1], e[2]))
    out: list[tuple[str, int, str]] = []
    rnd = 0
    while len(out) < n:
        progressed = False
        for s in order:
            if rnd < len(by_s[s]) and len(out) < n:
                out.append(by_s[s][rnd])
                progressed = True
        if not progressed:
            raise ValueError("not enough episodes")
        rnd += 1
    return out


def reconstruct(sid: str, p: int, t: str, seed_of: Mapping[str, int], record: Mapping[str, Any],
                profile: Mapping[str, Any], partition: str = "P5b_val", n_parents: int = 15) -> Any:
    valid, _ = generate_structure(partition, seed_of[sid], n_parents, profile, twins=True)
    ep = next((c.episodes[t] for c in valid if c.parent_index == p), None)
    tw = record["twins"][t]
    if ep is None or [x.plan_id for x in ep.plans] != [x["plan_id"] for x in tw["plans"]] or ep.universe_fingerprint != tw["universe_fingerprint"]:
        raise IsolationFailure("reconstruction_universe_mismatch", {"structure_id": sid, "parent_index": p, "twin": t})
    return ep


def _public_view(ep: Any, models: Mapping[str, Any], profile: Mapping[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], dict[str, int]]:
    feats = SnapshotFeatures(ep.snapshot, ep.sidecar, profile)
    plans = [plan_descriptor(p) for p in ep.plans]
    rows, preds, ch = {}, {}, {}
    for fam, model in models.items():
        rows[fam] = np.asarray([feats.row(p, fam)[1] for p in ep.plans], float)
        preds[fam] = np.asarray(model.predict(rows[fam]), float)
        ch[fam] = choose(list(preds[fam]), plans)
    return rows, preds, ch


def check_episode(ep: Any, models: Mapping[str, Any], profile: Mapping[str, Any], settings: Settings, commitment: str) -> dict[str, Any]:
    snap = ep.snapshot
    cfg = _config(settings, snap.as_of, 24)
    rows0, preds0, ch0 = _public_view(ep, models, profile)
    a = T.realise(ep, TRUTH_A[0], TRUTH_A[1], commitment)
    bs = [(key, T.realise(ep, key[0], key[1], commitment)) for key in TRUTH_B_ORDER]
    for label in ["A", *[f"{k[0]}k{k[1]}" for k, _ in bs]]:
        rows, preds, ch = _public_view(ep, models, profile)
        for fam in models:
            if not (np.array_equal(rows[fam], rows0[fam]) and np.array_equal(preds[fam], preds0[fam]) and ch[fam] == ch0[fam]):
                raise IsolationFailure("F1_T03_model_input_or_choice_changed", {"family": fam, "after_truth": label})
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
        try:
            check_isolation(PrivateOracle, snap, ep.plans[i], cfg, a.truth, dict(bs)[key].truth)
        except LeakageError:
            t04a = "DETECTED"
        else:
            raise IsolationFailure("T04a_false_negative_on_distinct_signature", {"plan_index": i, "truth_B": list(key)})
    oracle = PrivateOracle(a.truth)
    if oracle.info().product_allowed is not False:
        raise IsolationFailure("T04b_oracle_product_allowed", {})
    for name, call in (
        ("T04b_assert_product_backend", lambda: assert_product_backend(oracle)),
        ("T04c_recommend_with_oracle", lambda: recommend(snap, Settings(settings.profile, settings.objective, settings.score, oracle))),
        ("T04d_forecast_non_public_input", lambda: ReferenceForecaster().forecast({"stays": []}, ep.plans[0], cfg)),  # type: ignore[arg-type]
    ):
        try:
            call()
        except LeakageError:
            continue
        raise IsolationFailure(f"{name}_not_blocked", {})
    return {"n_plans": len(ep.plans), "F1_T03": "pass", "truths_compared": 1 + len(bs), "choices": ch0,
            "T04a": t04a, "T04a_witness": None if witness is None else {"truth_B": list(witness[0]), "plan_index": witness[1]},
            "T04a_pairs_examined": examined, "T04b": "pass", "T04c": "pass", "T04d": "pass"}
