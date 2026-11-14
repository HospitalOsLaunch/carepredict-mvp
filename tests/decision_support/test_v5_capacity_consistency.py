"""Independent v5 regression cases: canonical lending capacity per snapshot and slot.

Synthetic tests only. Run from a restored source root with PYTHONPATH=src:.:<this_dir>.
C01 forward is RED on v5; reverse and the three positive controls are GREEN.
No model fitting, network, external action, or change to the product code.
"""
from copy import deepcopy
import pytest
from test_v4_resource_boundaries import loan_data, offer, snap, only
from hospitalos.decision_support.planner import ReviewStore, simulate, review


def approve(snapshot, settings, option_id, store, key):
    rec = simulate(snapshot, only(option_id), settings)
    return review(rec, 'approve', snapshot, snapshot.as_of, key, store)


@pytest.mark.parametrize('order', [('R1', 'R2'), ('R2', 'R1')])
def test_c01_conflicting_declarations_same_snapshot_do_not_depend_on_approval_order(order):
    obs, at, settings = loan_data(scheduled=4)
    offer(obs, 'R2')['lending_unit_scheduled'] = 5
    s = snap(obs, at, settings)
    store = ReviewStore()
    outcomes = [approve(s, settings, ident, store, f'C01-{ident}').outcome for ident in order]
    assert outcomes.count('APPROVED_IN_DEMO') <= 1, (
        'Same lender U-LOAN/IDE, same snapshot, same 6 hour slots: '
        '4 and 5 scheduled/minimum 3 conflict. Joint candidate is correctly refused; '
        f'separate approvals must not bypass that conservative policy. order={order}, outcomes={outcomes}'
    )
    assert all(len(keys) <= 1 for (resource, _), keys in store.ledger.used.items()
               if resource.startswith('lend:U-LOAN:IDE'))


def test_c02_consistent_two_slot_capacity_keeps_two_loans_allowed():
    obs, at, settings = loan_data(scheduled=5)
    s = snap(obs, at, settings)
    store = ReviewStore()
    assert approve(s, settings, 'R1', store, 'C02-1').outcome == 'APPROVED_IN_DEMO'
    assert approve(s, settings, 'R2', store, 'C02-2').outcome == 'APPROVED_IN_DEMO'


def test_c03_genuine_capacity_increase_in_new_snapshot_can_allow_second_loan():
    obs, at, settings = loan_data(scheduled=4)
    first = snap(obs, at, settings)
    store = ReviewStore()
    assert approve(first, settings, 'R1', store, 'C03-1').outcome == 'APPROVED_IN_DEMO'
    updated = deepcopy(obs)
    for ident in ('R1', 'R2'):
        offer(updated, ident)['lending_unit_scheduled'] = 5
    second = snap(updated, at, settings)
    assert first.fingerprint != second.fingerprint
    assert approve(second, settings, 'R2', store, 'C03-2').outcome == 'APPROVED_IN_DEMO'


def test_c04_different_capacity_on_disjoint_windows_is_not_a_conflict():
    obs, at, settings = loan_data(scheduled=4)
    offer(obs, 'R1').update(start='2026-11-17T07:00:00+00:00', end='2026-11-17T11:00:00+00:00')
    offer(obs, 'R2')['lending_unit_scheduled'] = 5
    s = snap(obs, at, settings)
    store = ReviewStore()
    assert approve(s, settings, 'R1', store, 'C04-1').outcome == 'APPROVED_IN_DEMO'
    assert approve(s, settings, 'R2', store, 'C04-2').outcome == 'APPROVED_IN_DEMO'
