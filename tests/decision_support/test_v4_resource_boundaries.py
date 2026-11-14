"""Additional independent v4 tests. Synthetic only; no training, SIH action or network.

From the restored project root:
PYTHONPATH=src:. python -m pytest -q /path/to/test_v4_resource_boundaries.py
On bebb95b: B01-B03 fail, B04 passes. These do not replace A01-A10.
"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from hospitalos.decision_support.contracts import LockedReinforcement, ScenarioLocks
from hospitalos.decision_support.planner import ReviewStore, Settings, recommend, review, simulate
from hospitalos.decision_support.snapshot import build_snapshot, load_json


def data():
    raw = load_json(Path('tests/decision_support/fixtures/nominal_auto.json'))
    return deepcopy(raw['observations']), datetime.fromisoformat(raw['as_of']), Settings.default()


def offer(observations, ident):
    return next(o['value'] for o in observations
                if o['kind'] == 'reinforcement_option' and o['subject'] == ident)


def loan_data(scheduled=4):
    obs, at, settings = data()
    for ident in ('R1', 'R2'):
        offer(obs, ident).update({
            'source': 'shared_unit', 'confirmation': 'confirmed', 'lending_unit': 'U-LOAN',
            'lending_unit_scheduled': scheduled, 'lending_unit_minimum': 3,
            'start': '2026-11-17T13:00:00+00:00', 'end': '2026-11-17T19:00:00+00:00',
        })
    return obs, at, settings


def snap(obs, at, settings):
    return build_snapshot(obs, at, settings.profile)


def only(ident):
    return ScenarioLocks(locks=(LockedReinforcement(option_id=ident, include=True),),
                         search_complements=False)


def test_b01_offgrid_loan_overlap_is_blocked():
    obs, at, settings = loan_data()
    offer(obs, 'R2').update({'start': '2026-11-17T13:30:00+00:00',
                            'end': '2026-11-17T18:30:00+00:00'})
    try:
        rec = recommend(snap(obs, at, settings), settings)
    except ValueError:
        return  # Explicit unsupported precision is acceptable in an hourly prototype.
    if rec.bundle is None:
        assert not rec.approvable
        return
    offenders = [e.plan.plan_id for e in rec.bundle.evaluations if e.admissible
                 and {'R1', 'R2'} <= {a.target for a in e.plan.actions if a.type == 'reinforcement'}]
    assert not offenders, ('Simultaneous loans leave 4-2 < 3 during overlapping full hours; '
                           f'off-grid starts must not hide this: {offenders}')


def test_b02_shared_unit_requires_identified_lender():
    obs, at, settings = loan_data()
    for ident in ('R1', 'R2'):
        offer(obs, ident)['lending_unit'] = None
    try:
        rec = simulate(snap(obs, at, settings), only('R1'), settings)
    except ValueError:
        return  # Closed contract rejecting unknown identity is acceptable.
    assert not rec.approvable, 'An unidentified lender cannot have its cumulative margin checked.'


def test_b03_new_snapshot_reconciles_capacity_with_existing_holds():
    obs, at, settings = loan_data(scheduled=5)  # two loan slots initially
    s1 = snap(obs, at, settings)
    r1 = simulate(s1, only('R1'), settings)
    store = ReviewStore()
    assert review(r1, 'approve', s1, at, 'B03-first', store).outcome == 'APPROVED_IN_DEMO'
    holdings_before = deepcopy((store.ledger.by_key, store.ledger.used))
    new_obs = deepcopy(obs)
    for ident in ('R1', 'R2'):
        offer(new_obs, ident)['lending_unit_scheduled'] = 4  # now only one slot; already held
    s2 = snap(new_obs, at, settings)
    assert s2.fingerprint != s1.fingerprint
    r2 = simulate(s2, only('R2'), settings)
    out = review(r2, 'approve', s2, at, 'B03-second', store)
    assert out.outcome != 'APPROVED_IN_DEMO', (
        'Cached capacity 2 was retained although current spare capacity is 1 and already held.')
    assert (store.ledger.by_key, store.ledger.used) == holdings_before


def test_b04_positive_control_same_snapshot_second_loan_refused():
    obs, at, settings = loan_data()
    s = snap(obs, at, settings)
    r1 = simulate(s, only('R1'), settings)
    r2 = simulate(s, only('R2'), settings)
    store = ReviewStore()
    assert review(r1, 'approve', s, at, 'B04-first', store).outcome == 'APPROVED_IN_DEMO'
    holdings_before = deepcopy((store.ledger.by_key, store.ledger.used))
    assert review(r2, 'approve', s, at, 'B04-second', store).outcome == 'REFUSED'
    assert (store.ledger.by_key, store.ledger.used) == holdings_before
