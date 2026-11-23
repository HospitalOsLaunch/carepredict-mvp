"""Independent bounded checks of v6 canonical lender capacity.

No product changes, no training or network. Execute from the restored source root:
PYTHONPATH=src:.:tests/decision_support pytest -q <this_file>
"""
from copy import deepcopy
from datetime import datetime
from itertools import permutations

import pytest
from test_v4_resource_boundaries import loan_data, offer, snap, only
from hospitalos.decision_support.planner import ReviewStore, simulate, review
from hospitalos.decision_support.resources import lender_capacities, lending_violations


def approve(s, settings, ident, store):
    rec = simulate(s, only(ident), settings)
    return review(rec, 'approve', s, s.as_of, 'v6-independent-'+ident, store)


def loan_caps(s):
    """Inspect U-LOAN/IDE only; the base fixture also has unrelated lender R3."""
    return {k: c for k, c in lender_capacities(s.reinforcements).items()
            if k[0] == "U-LOAN" and k[1] == "IDE"}


def assert_one_approved(s, settings, order):
    store = ReviewStore()
    first = approve(s, settings, order[0], store)
    held = deepcopy((store.ledger.by_key, store.ledger.used))
    second = approve(s, settings, order[1], store)
    assert (first.outcome, second.outcome) == ('APPROVED_IN_DEMO', 'REFUSED')
    assert (store.ledger.by_key, store.ledger.used) == held


def test_d01_capacity_does_not_depend_on_offer_list_order():
    obs, at, settings = loan_data(scheduled=4)
    offer(obs, 'R2')['lending_unit_scheduled'] = 5
    s = snap(obs, at, settings)
    options = tuple(o for o in s.reinforcements if o.option_id in ('R1', 'R2'))
    ref = lender_capacities(options)
    for ordered in permutations(options):
        assert lender_capacities(ordered) == ref
    assert len(ref) == 6
    assert {c.spare for c in ref.values()} == {1}
    assert all(c.conflicting and c.sources == ('R1','R2') for c in ref.values())


@pytest.mark.parametrize('order',[('R1','R2'),('R2','R1')])
def test_d02_conflicting_minimum_also_uses_prudent_capacity(order):
    obs, at, settings = loan_data(scheduled=5)
    offer(obs,'R2')['lending_unit_minimum'] = 4
    s = snap(obs, at, settings)
    assert {c.spare for c in loan_caps(s).values()} == {1}
    assert_one_approved(s, settings, order)


@pytest.mark.parametrize('field',['lending_unit_scheduled','lending_unit_minimum'])
def test_d03_unknown_other_declaration_is_not_replaced_by_known_selected_offer(field):
    obs, at, settings = loan_data(scheduled=5)
    offer(obs,'R2')[field] = None
    s = snap(obs, at, settings)
    caps=loan_caps(s)
    assert all(c.spare is None and c.policy == 'unknown_commitment' for c in caps.values())
    rec=simulate(s,only('R1'),settings)
    assert not rec.approvable
    store=ReviewStore()
    assert review(rec,'approve',s,at,'unknown-'+field,store).outcome != 'APPROVED_IN_DEMO'
    assert not store.ledger.by_key


@pytest.mark.parametrize('order',[('R1','R2'),('R2','R1')])
def test_d04_partial_aligned_overlap_is_checked_per_hour(order):
    obs, at, settings=loan_data(scheduled=5)
    offer(obs,'R1')['end']='2026-11-17T17:00:00+00:00'
    offer(obs,'R2').update(start='2026-11-17T15:00:00+00:00',lending_unit_scheduled=4)
    s=snap(obs,at,settings);caps=loan_caps(s)
    assert {c.hour.hour:c.spare for c in caps.values()} == {13:2,14:2,15:1,16:1,17:1,18:1}
    chosen=[o for o in s.reinforcements if o.option_id in ('R1','R2')]
    issues=lending_violations(chosen,s.reinforcements)
    assert len(issues)==2
    assert_one_approved(s,settings,order)


def test_d05_distinct_lenders_are_not_conflated():
    obs,at,settings=loan_data(scheduled=4)
    offer(obs,'R2')['lending_unit']='U-OTHER'
    s=snap(obs,at,settings);store=ReviewStore()
    assert approve(s,settings,'R1',store).outcome=='APPROVED_IN_DEMO'
    assert approve(s,settings,'R2',store).outcome=='APPROVED_IN_DEMO'
    assert {k[0] for k in store.ledger.used if k[0].startswith('lend:')} == {'lend:U-LOAN:IDE','lend:U-OTHER:IDE'}


def test_d06_equivalent_timezone_notations_share_same_slots():
    obs,at,settings=loan_data(scheduled=4)
    offer(obs,'R2').update(start='2026-11-17T14:00:00+01:00',end='2026-11-17T20:00:00+01:00',lending_unit_scheduled=5)
    s=snap(obs,at,settings)
    caps=loan_caps(s)
    assert len(caps)==6 and {c.spare for c in caps.values()}=={1}
    assert_one_approved(s,settings,('R1','R2'))
