"""Independent regression tests for the delivered HospitalOS DS P0-P4 source.
Run from the source root, PYTHONPATH=src:.; no training or network access.
Nine tests are expected to fail against the delivered d7844ea source.
"""
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from hospitalos.decision_support.snapshot import build_snapshot, load_json
from hospitalos.decision_support.planner import Settings, recommend, simulate, review, ReviewStore
from hospitalos.decision_support.contracts import ScenarioLocks, LockedDischarge
from hospitalos.decision_support.reference_forecaster import (
    simulate as simulate_world, decisions_from_plan, SampledProvider,
)

@pytest.fixture
def setup():
    raw=load_json(Path('tests/decision_support/fixtures/nominal_auto.json'))
    settings=Settings.default()
    return raw, settings, datetime.fromisoformat(raw['as_of'])

def snapshot(setup, observations=None):
    raw,settings,at=setup
    return build_snapshot(observations if observations is not None else raw['observations'], at, settings.profile)

def observation_value(observations,kind,subject):
    return next(o['value'] for o in observations if o['kind']==kind and o['subject']==subject)

def locks(at='2026-11-17T09:00:00+00:00'):
    return ScenarioLocks(locks=(LockedDischarge(stay_id='S01',at=datetime.fromisoformat(at),basis='validated_instruction'),),search_complements=False)

def primary(recommendation):
    return next(e for e in recommendation.bundle.evaluations if e.plan.plan_id==recommendation.primary_plan_id)

def test_a01_known_readiness_contradiction_not_approvable(setup):
    raw,settings,_=setup;obs=copy.deepcopy(raw['observations'])
    v=observation_value(obs,'readiness_estimate','S01')
    v.update({'earliest':'2026-11-17T17:00:00+00:00','delay_hours':{'support':[0],'weights':[1]}})
    rec=simulate(snapshot(setup,obs),locks(),settings)
    assert not rec.approvable, 'A contradicted readiness assumption must remain hypothetical or infeasible'

def test_a02_observed_obstacle_not_bypassed_by_manual_lock(setup):
    raw,settings,_=setup;obs=copy.deepcopy(raw['observations'])
    obs.append({'obs_id':'audit-obstacle','kind':'obstacle','subject':'S01.audit','event_time':raw['as_of'],'available_at':raw['as_of'],'source':'independent_synthetic_probe','synthetic':True,'value':{'stay_id':'S01','code':'destination_unavailable','active':True}})
    rec=simulate(snapshot(setup,obs),locks(),settings)
    assert not rec.approvable, 'An active logistical obstacle must not disappear in manual mode'

def test_a03_aggregate_lending_unit_minimum(setup):
    raw,settings,_=setup;obs=copy.deepcopy(raw['observations'])
    for ident in ('R1','R2'):
        observation_value(obs,'reinforcement_option',ident).update({'source':'shared_unit','confirmation':'confirmed','lending_unit':'U-LOAN','lending_unit_scheduled':4,'lending_unit_minimum':3,'start':'2026-11-17T13:00:00+00:00','end':'2026-11-17T19:00:00+00:00'})
    rec=recommend(snapshot(setup,obs),settings)
    offenders=[e.plan.plan_id for e in rec.bundle.evaluations if e.admissible and {a.target for a in e.plan.actions if a.type=='reinforcement'}>={'R1','R2'}]
    assert not offenders, f'4 - 2 = 2 < minimum 3: {offenders}'

def test_a04_rejected_plan_reservations_are_atomic(setup):
    _,settings,at=setup;s=snapshot(setup);rec=recommend(s,settings);store=ReviewStore()
    a=next(a for a in primary(rec).plan.actions if a.type=='reinforcement' and a.target=='R1')
    store.ledger.capacity[(a.target,a.window_start.isoformat())]=1
    store.ledger.reserve(a.target,a.window_start.isoformat(),'external-holder')
    before=copy.deepcopy(store.ledger.by_key)
    out=review(rec,'approve',s,at,'audit-atomicity',store)
    assert out.outcome=='REFUSED'
    assert store.ledger.by_key==before, 'Rejected plan leaked reservations'

def test_a05_idempotency_conflicting_payload_not_success_replay(setup):
    _,settings,at=setup;s=snapshot(setup);rec=recommend(s,settings);store=ReviewStore()
    review(rec,'approve',s,at,'shared-key',store)
    try:
        out=review(rec,'reject',s,at,'shared-key',store)
    except ValueError:
        return  # explicit key/payload conflict is acceptable
    assert out.outcome!='APPROVED_IN_DEMO' and out.decision=='reject', 'Reject request returned cached approval'

def test_a06_minute_precision_not_silently_rounded_down(setup):
    _,settings,at=setup;s=snapshot(setup)
    try:
        rec=simulate(s,locks('2026-11-17T09:30:00+00:00'),settings)
    except (ValueError,ValidationError):
        return  # explicit refusal of unsupported time precision is acceptable
    if not rec.approvable:
        return
    e=primary(rec)
    r=simulate_world(s,settings.profile,at,24,decisions_from_plan(e.plan,s,at),SampledProvider(101))
    assert at+timedelta(hours=r.departures['S01'])==e.plan.actions[0].window_start, 'Locked 10:30, simulated 10:00 Paris'

def test_a07_unknown_cleaning_is_not_silent_one_hour_assumption(setup):
    raw,settings,_=setup;obs=copy.deepcopy(raw['observations'])
    observation_value(obs,'bed','L01').pop('cleaning_hours')
    rec=recommend(snapshot(setup,obs),settings)
    assert not rec.approvable or any(tag in s for s in (*rec.diagnostics,*rec.conditions,*rec.uncertainties) for tag in ('cleaning_duration_unknown:L01', 'assumed_cleaning_duration:L01')), 'Silent default replaces missing cleaning duration'

def test_a08_required_skill_roster_unknown_not_silent_zero(setup):
    raw,settings,_=setup;obs=copy.deepcopy(raw['observations'])
    o=copy.deepcopy(next(o for o in obs if o['kind']=='care_profile' and o['subject']=='S01.IDE'))
    o.update({'obs_id':'audit-AS','subject':'S01.AS'});o['value'].update({'skill':'AS','day_minutes_per_hour':15,'night_minutes_per_hour':15});obs.append(o)
    rec=recommend(snapshot(setup,obs),settings)
    assert not rec.approvable or any('roster_unknown:AS' in d for d in rec.diagnostics), 'AS care is declared but AS roster is unknown, not zero'

def test_a09_config_changes_change_document_identity(setup):
    _,settings,_=setup;s=snapshot(setup);first=recommend(s,settings)
    score=copy.deepcopy(settings.score);score['coefficients']['uncovered_minutes_divisor']=1500
    other=recommend(s,Settings(settings.profile,settings.objective,score))
    assert first.recommendation_id!=other.recommendation_id and first.bundle.bundle_id!=other.bundle.bundle_id, 'Same document ids for different calculated scores'

def test_a10_required_staff_does_not_depend_on_available_offers(setup):
    raw,settings,_=setup
    s1=snapshot(setup);s2=snapshot(setup,[o for o in raw['observations'] if o['kind']!='reinforcement_option'])
    r1,r2=recommend(s1,settings),recommend(s2,settings)
    e1=next(e for e in r1.bundle.evaluations if e.plan.is_baseline)
    e2=next(e for e in r2.bundle.evaluations if e.plan.is_baseline)
    assert [p.staff_required for p in e1.trajectory]==[p.staff_required for p in e2.trajectory]
