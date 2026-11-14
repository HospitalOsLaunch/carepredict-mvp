"""v6 — targeted tests for re-audit finding V5-R01 (one lender capacity per snapshot and slot).

Complements the auditor's C01-C04 (test_v5_capacity_consistency.py, kept verbatim) by checking
the capacity value, its provenance, the reported conflict and the preserved commitments.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

from test_v4_resource_boundaries import loan_data, offer, only, snap

from hospitalos.decision_support.candidates import make_plan, reinforcement_action
from hospitalos.decision_support.planner import (
    ReviewStore,
    _reservation_requests,
    recommend,
    review,
    simulate,
)
from hospitalos.decision_support.resources import lender_capacities


def conflicting():
    obs, at, settings = loan_data(scheduled=4)
    offer(obs, "R2")["lending_unit_scheduled"] = 5  # same lender, skill and hours: 4 vs 5
    return snap(obs, at, settings), settings


def lend_requests(s, ident):
    o = next(x for x in s.reinforcements if x.option_id == ident)
    plan = make_plan(
        s, "auto", (reinforcement_action(s, o, s.as_of + timedelta(minutes=30)),), ident
    )
    return [r for r in _reservation_requests(plan.actions, s) if r[0].startswith("lend:")]


def test_v5r01_capacity_is_the_same_whichever_offer_is_approved():
    s, _ = conflicting()
    r1, r2 = lend_requests(s, "R1"), lend_requests(s, "R2")
    assert [(r[1], r[3], r[4]) for r in r1] == [(r[1], r[3], r[4]) for r in r2]
    assert {r[3] for r in r1} == {1}  # prudent: min(4, 5) - max(3, 3)
    assert all("prudent:min_scheduled-max_minimum:R1+R2" in r[4] for r in r1)
    assert all(r[4].startswith(f"snapshot:{s.fingerprint[:16]}") for r in r1)


def test_v5r01_conflict_is_reported_and_first_commitment_preserved():
    s, settings = conflicting()
    rec = recommend(s, settings)
    assert any(
        d.startswith("lending_declarations_conflict:U-LOAN:IDE:6h")
        and "prudent:min_scheduled-max_minimum:spare=1" in d
        for d in rec.diagnostics
    )
    for order in (("R1", "R2"), ("R2", "R1")):
        store = ReviewStore()
        first = review(simulate(s, only(order[0]), settings), "approve", s, s.as_of, "k1", store)
        held = deepcopy((store.ledger.by_key, store.ledger.used))
        second = review(simulate(s, only(order[1]), settings), "approve", s, s.as_of, "k2", store)
        assert (first.outcome, second.outcome) == ("APPROVED_IN_DEMO", "REFUSED")
        assert (store.ledger.by_key, store.ledger.used) == held
        assert {v for k, v in store.ledger.capacity_source.items() if k[0].startswith("lend:")} == {
            lend_requests(s, "R1")[0][4]
        }


def test_v5r01_zero_prudent_margin_refuses_even_a_single_offer():
    obs, at, settings = loan_data(scheduled=5)
    offer(obs, "R1")["lending_unit_scheduled"] = 3  # R1 declares no spare; R2 declares 2
    s = snap(obs, at, settings)
    caps = lender_capacities(s.reinforcements)
    assert {c.spare for c in caps.values()} == {0}
    rec = recommend(s, settings)
    assert all(
        "R2" not in {a.target for a in e.plan.actions if a.type == "reinforcement"}
        for e in rec.bundle.evaluations
    )
    assert rec.bundle.search.rejected["R2"].startswith("lending_unit_minimum_cumulative:U-LOAN")
